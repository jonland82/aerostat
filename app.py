from __future__ import annotations

import gzip
import json
import mimetypes
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
CREDENTIALS_PATH = ROOT / "credentials.json"
QUOTA_PATH = DATA_DIR / "quota.json"

OPEN_SKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
OPEN_SKY_STATES_URL = "https://opensky-network.org/api/states/all"

# Manual refresh is intentional. Do not add a scheduler without implementing the
# quota-aware polling design documented in README.md.
MIN_REFRESH_SECONDS = 15
LOCAL_DAILY_BUDGET = 3_000


class ApiError(Exception):
    def __init__(self, status: int, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


@dataclass
class Token:
    value: str
    expires_at: float


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def credit_cost(bounds: dict[str, float] | None) -> int:
    if bounds is None:
        return 4
    area = abs(bounds["lamax"] - bounds["lamin"]) * abs(
        bounds["lomax"] - bounds["lomin"]
    )
    if area <= 25:
        return 1
    if area <= 100:
        return 2
    if area <= 400:
        return 3
    return 4


def normalize_state(row: list[Any]) -> dict[str, Any] | None:
    def item(index: int) -> Any:
        return row[index] if index < len(row) else None

    longitude, latitude = item(5), item(6)
    if longitude is None or latitude is None:
        return None
    return {
        "icao24": item(0),
        "callsign": (item(1) or "").strip() or None,
        "country": item(2),
        "timePosition": item(3),
        "lastContact": item(4),
        "longitude": longitude,
        "latitude": latitude,
        "baroAltitude": item(7),
        "onGround": bool(item(8)),
        "velocity": item(9),
        "trueTrack": item(10),
        "verticalRate": item(11),
        "geoAltitude": item(13),
        "squawk": item(14),
        "positionSource": item(16),
        "category": item(17),
    }


class QuotaLedger:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            state = {}
        if state.get("day") != utc_day():
            state = {"day": utc_day(), "spent": 0, "openskyRemaining": None}
        return state

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            if self.state.get("day") != utc_day():
                self.state = {"day": utc_day(), "spent": 0, "openskyRemaining": None}
                self._save()
            return {
                **self.state,
                "budget": LOCAL_DAILY_BUDGET,
                "available": max(0, LOCAL_DAILY_BUDGET - self.state["spent"]),
            }

    def require(self, cost: int) -> None:
        available = self.snapshot()["available"]
        if cost > available:
            raise ApiError(
                HTTPStatus.TOO_MANY_REQUESTS,
                "The dashboard's conservative daily credit budget is exhausted.",
            )

    def record(self, cost: int, remaining: str | None) -> None:
        with self.lock:
            if self.state.get("day") != utc_day():
                self.state = {"day": utc_day(), "spent": 0, "openskyRemaining": None}
            self.state["spent"] += cost
            if remaining is not None:
                try:
                    self.state["openskyRemaining"] = int(remaining)
                except ValueError:
                    pass
            self._save()


class OpenSkyClient:
    def __init__(self, credentials_path: Path):
        self.credentials_path = credentials_path
        self.token: Token | None = None
        self.lock = threading.Lock()

    def _credentials(self) -> tuple[str, str]:
        try:
            data = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            return data["clientId"], data["clientSecret"]
        except FileNotFoundError as exc:
            raise ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "credentials.json is missing.") from exc
        except (KeyError, json.JSONDecodeError) as exc:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "credentials.json must contain clientId and clientSecret.",
            ) from exc

    def _get_token(self) -> str:
        with self.lock:
            if self.token and self.token.expires_at > time.time() + 30:
                return self.token.value
            client_id, client_secret = self._credentials()
            body = urllib.parse.urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
            ).encode()
            request = urllib.request.Request(
                OPEN_SKY_TOKEN_URL,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                raise ApiError(exc.code, "OpenSky authentication failed.") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raise ApiError(HTTPStatus.BAD_GATEWAY, "Could not reach OpenSky authentication.") from exc
            self.token = Token(
                payload["access_token"],
                time.time() + int(payload.get("expires_in", 1_800)),
            )
            return self.token.value

    def states(self, bounds: dict[str, float] | None = None) -> tuple[dict[str, Any], str | None]:
        query = urllib.parse.urlencode(bounds) if bounds else ""
        url = f"{OPEN_SKY_STATES_URL}?{query}" if query else OPEN_SKY_STATES_URL
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Accept": "application/json",
                "User-Agent": "OpenSky-Globe-Dashboard/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
                remaining = response.headers.get("X-Rate-Limit-Remaining")
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.UNAUTHORIZED:
                self.token = None
            retry_after = exc.headers.get("X-Rate-Limit-Retry-After-Seconds")
            message = "OpenSky rate limit reached." if exc.code == 429 else "OpenSky request failed."
            raise ApiError(exc.code, message, retry_after) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, "Could not reach the OpenSky states API.") from exc
        return payload, remaining


class DashboardState:
    def __init__(self):
        self.client = OpenSkyClient(CREDENTIALS_PATH)
        self.quota = QuotaLedger(QUOTA_PATH)
        self.refresh_lock = threading.Lock()
        self.snapshot: dict[str, Any] | None = None
        self.last_attempt = 0.0

    def status(self) -> dict[str, Any]:
        snapshot = self.snapshot
        return {
            "manualOnly": True,
            "autoRefresh": False,
            "requiresRefreshKey": False,
            "minimumRefreshSeconds": MIN_REFRESH_SECONDS,
            "hasSnapshot": snapshot is not None,
            "snapshotUrl": "/api/aircraft" if snapshot else None,
            "lastRefresh": snapshot.get("fetchedAt") if snapshot else None,
            "aircraftCount": snapshot.get("count", 0) if snapshot else 0,
            "quota": self.quota.snapshot(),
        }

    def refresh(self) -> dict[str, Any]:
        if not self.refresh_lock.acquire(blocking=False):
            raise ApiError(HTTPStatus.CONFLICT, "A refresh is already in progress.")
        try:
            elapsed = time.monotonic() - self.last_attempt
            if self.last_attempt and elapsed < MIN_REFRESH_SECONDS:
                wait = max(1, int(MIN_REFRESH_SECONDS - elapsed + 0.999))
                raise ApiError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    f"Please wait {wait} seconds before another manual refresh.",
                    str(wait),
                )
            cost = credit_cost(None)
            self.quota.require(cost)
            self.last_attempt = time.monotonic()
            payload, remaining = self.client.states()
            aircraft = []
            for row in payload.get("states") or []:
                normalized = normalize_state(row)
                if normalized:
                    aircraft.append(normalized)
            self.quota.record(cost, remaining)
            self.snapshot = {
                "sourceTime": payload.get("time"),
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "count": len(aircraft),
                "requestCost": cost,
                "aircraft": aircraft,
            }
            return self.snapshot
        finally:
            self.refresh_lock.release()


STATE = DashboardState()


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "OpenSkyDashboard/0.1"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if urllib.parse.urlparse(self.path).path.endswith((".html", ".css", ".js")):
            self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "img-src 'self' data:; style-src 'self'; "
            "connect-src 'self'; worker-src blob:",
        )
        super().end_headers()

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        use_gzip = "gzip" in self.headers.get("Accept-Encoding", "") and len(raw) > 1_024
        body = gzip.compress(raw, compresslevel=5) if use_gzip else raw
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: ApiError) -> None:
        payload = {"error": error.message}
        if error.retry_after:
            payload["retryAfter"] = error.retry_after
        self._json(payload, error.status)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            self._json(STATE.status())
            return
        if path == "/api/aircraft":
            if STATE.snapshot is None:
                self._json({"error": "No snapshot yet. Use manual refresh."}, HTTPStatus.NOT_FOUND)
            else:
                self._json(STATE.snapshot)
            return
        if path == "/healthz":
            self._json({"status": "ok"})
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/aircraft/refresh":
            self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return
        try:
            self._json({"snapshot": STATE.refresh(), "status": STATE.status()})
        except ApiError as error:
            self._error(error)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def run() -> None:
    host = os.environ.get("OPEN_SKY_HOST", "127.0.0.1")
    port = int(os.environ.get("OPEN_SKY_PORT", "8000"))
    mimetypes.add_type("application/javascript", ".js")
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"OpenSky Globe: http://{host}:{port}")
    print("Aircraft data refreshes only when the Refresh aircraft button is clicked.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
