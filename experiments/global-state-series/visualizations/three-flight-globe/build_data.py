from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "data" / "global_states.parquet"
OUTPUT = HERE / "flight-data.js"
FLIGHTS = {
    "aa9093": {"color": "#55e6ff", "label": "NORTH ATLANTIC"},
    "a6aab5": {"color": "#ffbe55", "label": "NORTH PACIFIC"},
    "e0b14a": {"color": "#ff5fa2", "label": "SOUTH AMERICA"},
}


def haversine_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(
        math.radians, (a["lat"], a["lng"], b["lat"], b["lng"])
    )
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6_371 * 2 * math.asin(math.sqrt(value))


table = pq.read_table(
    SOURCE,
    filters=[("icao24", "in", list(FLIGHTS))],
    columns=[
        "icao24",
        "callsign",
        "origin_country",
        "requested_time",
        "latitude",
        "longitude",
        "baro_altitude",
        "velocity",
        "true_track",
        "vertical_rate",
    ],
)
rows = table.to_pylist()
payload = []
for icao24, display in FLIGHTS.items():
    selected = sorted(
        (row for row in rows if row["icao24"] == icao24),
        key=lambda row: row["requested_time"],
    )
    points = [
        {
            "t": row["requested_time"],
            "lat": round(row["latitude"], 5),
            "lng": round(row["longitude"], 5),
            "altFt": round((row["baro_altitude"] or 0) * 3.28084),
            "speedKt": round((row["velocity"] or 0) * 1.94384),
            "heading": round(row["true_track"] or 0),
            "verticalFpm": round((row["vertical_rate"] or 0) * 196.8504),
        }
        for row in selected
        if row["latitude"] is not None and row["longitude"] is not None
    ]
    distance = sum(haversine_km(a, b) for a, b in zip(points, points[1:]))
    payload.append(
        {
            "icao24": icao24,
            "callsign": next(row["callsign"] for row in selected if row["callsign"]),
            "country": selected[0]["origin_country"],
            "label": display["label"],
            "color": display["color"],
            "distanceKm": round(distance),
            "points": points,
        }
    )

OUTPUT.write_text(
    "window.FLIGHT_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n",
    encoding="ascii",
)
print(f"Wrote {OUTPUT} with {sum(len(f['points']) for f in payload)} points")
