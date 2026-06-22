from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "data" / "global_states.parquet"
OUTPUT = HERE / "histogram-data.js"
BIN_WIDTH_FT = 1_000
MIN_ALTITUDE_FT = -1_000
MAX_ALTITUDE_FT = 60_000
METERS_TO_FEET = 3.28084


table = pq.read_table(
    SOURCE,
    columns=["requested_time", "baro_altitude"],
)

snapshots: dict[int, list[float | None]] = {}
for row in table.to_pylist():
    snapshots.setdefault(row["requested_time"], []).append(row["baro_altitude"])

frames = []
for requested_time, altitudes_m in sorted(snapshots.items()):
    bins = [0] * ((MAX_ALTITUDE_FT - MIN_ALTITUDE_FT) // BIN_WIDTH_FT)
    known_altitudes = []
    below_range = 0
    above_range = 0

    for altitude_m in altitudes_m:
        if altitude_m is None:
            continue
        altitude_ft = altitude_m * METERS_TO_FEET
        known_altitudes.append(altitude_ft)
        if altitude_ft < MIN_ALTITUDE_FT:
            below_range += 1
        elif altitude_ft >= MAX_ALTITUDE_FT:
            above_range += 1
        else:
            index = math.floor(
                (altitude_ft - MIN_ALTITUDE_FT) / BIN_WIDTH_FT
            )
            bins[index] += 1

    known_altitudes.sort()
    middle = len(known_altitudes) // 2
    if len(known_altitudes) % 2:
        median_ft = known_altitudes[middle]
    else:
        median_ft = (known_altitudes[middle - 1] + known_altitudes[middle]) / 2

    frames.append(
        {
            "time": requested_time,
            "total": len(altitudes_m),
            "known": len(known_altitudes),
            "missing": len(altitudes_m) - len(known_altitudes),
            "medianFt": round(median_ft),
            "belowRange": below_range,
            "aboveRange": above_range,
            "bins": bins,
        }
    )

payload = {
    "binWidthFt": BIN_WIDTH_FT,
    "minAltitudeFt": MIN_ALTITUDE_FT,
    "maxAltitudeFt": MAX_ALTITUDE_FT,
    "frames": frames,
}
OUTPUT.write_text(
    "window.ALTITUDE_HISTOGRAM_DATA = "
    + json.dumps(payload, separators=(",", ":"))
    + ";\n",
    encoding="ascii",
)
print(f"Wrote {OUTPUT} with {len(frames)} frames")
