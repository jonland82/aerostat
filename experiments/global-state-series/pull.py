from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


EXPERIMENT_DIR = Path(__file__).resolve().parent
ROOT = EXPERIMENT_DIR.parents[1]
sys.path.insert(0, str(ROOT))

from app import ApiError, QuotaLedger  # noqa: E402


TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"
CREDENTIALS_PATH = ROOT / "credentials.json"
QUOTA_PATH = ROOT / "data" / "quota.json"
GLOBAL_REQUEST_CREDITS = 4
STATE_FIELDS = (
    "icao24",
    "callsign",
    "origin_country",
    "time_position",
    "last_contact",
    "longitude",
    "latitude",
    "baro_altitude",
    "on_ground",
    "velocity",
    "true_track",
    "vertical_rate",
    "sensors",
    "geo_altitude",
    "squawk",
    "spi",
    "position_source",
    "category",
)


def load_credentials() -> tuple[str, str]:
    try:
        credentials = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        return credentials["clientId"], credentials["clientSecret"]
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing credentials file: {CREDENTIALS_PATH}") from exc
    except (KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("credentials.json must contain clientId and clientSecret") from exc


def get_token() -> str:
    client_id, client_secret = load_credentials()
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)["access_token"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenSky authentication failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach OpenSky authentication") from exc


def requested_timestamps(samples: int, interval: int) -> list[int]:
    # Stay just behind real time and fetch oldest first. OpenSky permits authenticated
    # state-vector requests only within the preceding hour.
    newest = (int(time.time()) // 5) * 5 - 10
    return [newest - interval * offset for offset in reversed(range(samples))]


def fetch_snapshot(token: str, requested_time: int) -> tuple[dict[str, Any], int | None]:
    url = f"{STATES_URL}?{urllib.parse.urlencode({'time': requested_time})}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Aerostat-State-Series-Experiment/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            remaining = response.headers.get("X-Rate-Limit-Remaining")
            return json.load(response), int(remaining) if remaining else None
    except urllib.error.HTTPError as exc:
        retry = exc.headers.get("X-Rate-Limit-Retry-After-Seconds")
        detail = f"; retry after {retry}s" if retry else ""
        raise RuntimeError(f"State request failed with HTTP {exc.code}{detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Could not reach the OpenSky states API") from exc


def normalize_row(requested_time: int, snapshot_time: int, state: list[Any]) -> dict[str, Any]:
    values = list(state[: len(STATE_FIELDS)])
    values.extend([None] * (len(STATE_FIELDS) - len(values)))
    row = dict(zip(STATE_FIELDS, values))
    row["callsign"] = (row["callsign"] or "").strip() or None
    row["sensors"] = json.dumps(row["sensors"]) if row["sensors"] is not None else None
    return {"requested_time": requested_time, "snapshot_time": snapshot_time, **row}


def write_raw(path: Path, payload: dict[str, Any]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as output:
        json.dump(payload, output, separators=(",", ":"))


def iso_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def run(samples: int, interval: int, output_dir: Path) -> dict[str, Any]:
    if samples < 1 or interval < 5:
        raise ValueError("samples must be positive and interval must be at least 5 seconds")
    if (samples - 1) * interval >= 3_600:
        raise ValueError("the requested series must fit inside OpenSky's one-hour history window")

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    quota = QuotaLedger(QUOTA_PATH)
    total_credits = samples * GLOBAL_REQUEST_CREDITS
    quota.require(total_credits)
    token = get_token()
    timestamps = requested_timestamps(samples, interval)
    parquet_path = output_dir / "global_states.parquet"
    writer: pq.ParquetWriter | None = None
    counts: Counter[str] = Counter()
    total_rows = 0
    remaining: int | None = None

    try:
        for index, requested_time in enumerate(timestamps, start=1):
            payload, remaining = fetch_snapshot(token, requested_time)
            quota.record(GLOBAL_REQUEST_CREDITS, str(remaining) if remaining is not None else None)
            snapshot_time = int(payload["time"])
            raw_path = raw_dir / f"states-{requested_time}.json.gz"
            write_raw(raw_path, payload)
            rows = [
                normalize_row(requested_time, snapshot_time, state)
                for state in (payload.get("states") or [])
            ]
            if rows:
                table = pa.Table.from_pylist(rows)
                if writer is None:
                    writer = pq.ParquetWriter(parquet_path, table.schema, compression="zstd")
                writer.write_table(table)
                counts.update(row["icao24"] for row in rows if row["icao24"])
                total_rows += len(rows)
            print(
                f"[{index:02d}/{samples}] {iso_time(requested_time)}: "
                f"{len(rows):,} states; {remaining if remaining is not None else '?'} credits remain",
                flush=True,
            )
    finally:
        if writer is not None:
            writer.close()

    if not parquet_path.exists():
        raise RuntimeError("OpenSky returned no state vectors")

    top_ids = [icao24 for icao24, _ in counts.most_common(500)]
    full_table = pq.read_table(parquet_path)
    top_table = full_table.filter(pc.is_in(full_table["icao24"], value_set=pa.array(top_ids)))
    top_path = output_dir / "top_500_states.parquet"
    pq.write_table(top_table, top_path, compression="zstd")

    manifest = {
        "created_at": iso_time(int(time.time())),
        "sample_count": samples,
        "interval_seconds": interval,
        "first_requested_time": timestamps[0],
        "first_requested_at": iso_time(timestamps[0]),
        "last_requested_time": timestamps[-1],
        "last_requested_at": iso_time(timestamps[-1]),
        "credits_spent": total_credits,
        "opensky_credits_remaining": remaining,
        "rows": total_rows,
        "distinct_aircraft": len(counts),
        "top_500_rows": top_table.num_rows,
        "top_500_aircraft": len(top_ids),
        "complete_aircraft": sum(1 for count in counts.values() if count == samples),
        "files": {
            "full_parquet": parquet_path.name,
            "top_500_parquet": top_path.name,
            "raw_snapshots": "raw/states-<requested-time>.json.gz",
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull a bounded OpenSky global state-vector series.")
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--interval", type=int, default=60, help="Seconds between samples")
    parser.add_argument("--output", type=Path, default=EXPERIMENT_DIR / "data")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    try:
        result = run(arguments.samples, arguments.interval, arguments.output.resolve())
    except (ApiError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, indent=2))
