from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "data" / "global_states.parquet"
OUTPUT = HERE / "deviation-data.js"
EARTH_RADIUS_KM = 6_371.0088
MIN_ENDPOINT_DISTANCE_KM = 25
MAX_STEP_DISTANCE_KM = 30


def unit_vector(latitude: float, longitude: float) -> tuple[float, float, float]:
    lat = math.radians(latitude)
    lon = math.radians(longitude)
    return (
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    )


def dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b))


def cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(value: tuple[float, ...]) -> float:
    return math.sqrt(dot(value, value))


def scale(value: tuple[float, ...], factor: float) -> tuple[float, ...]:
    return tuple(component * factor for component in value)


def subtract(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b))


def angular_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.acos(max(-1.0, min(1.0, dot(a, b))))


def distance_to_geodesic_arc(
    point: tuple[float, ...],
    start: tuple[float, ...],
    end: tuple[float, ...],
    arc_angle: float,
) -> float:
    normal = cross(start, end)
    normal_length = norm(normal)
    if normal_length < 1e-12:
        return min(angular_distance(point, start), angular_distance(point, end)) * EARTH_RADIUS_KM

    normal = scale(normal, 1 / normal_length)
    projected = subtract(point, scale(normal, dot(point, normal)))
    projected_length = norm(projected)
    if projected_length < 1e-12:
        return min(angular_distance(point, start), angular_distance(point, end)) * EARTH_RADIUS_KM

    projected = scale(projected, 1 / projected_length)
    if dot(projected, point) < 0:
        projected = scale(projected, -1)
    start_to_projection = angular_distance(start, projected)
    projection_to_end = angular_distance(projected, end)

    if abs(start_to_projection + projection_to_end - arc_angle) < 1e-7:
        cross_track_angle = abs(math.asin(max(-1.0, min(1.0, dot(point, normal)))))
        return cross_track_angle * EARTH_RADIUS_KM
    return min(angular_distance(point, start), angular_distance(point, end)) * EARTH_RADIUS_KM


table = pq.read_table(
    SOURCE,
    columns=["requested_time", "icao24", "callsign", "latitude", "longitude"],
)
snapshots = sorted(set(table.column("requested_time").to_pylist()))
tracks: dict[str, list[dict]] = defaultdict(list)
for row in table.to_pylist():
    tracks[row["icao24"]].append(row)

aircraft = []
excluded = {"incomplete": 0, "stationary": 0, "implausibleJump": 0}
for icao24, rows in tracks.items():
    rows.sort(key=lambda row: row["requested_time"])
    times = [row["requested_time"] for row in rows]
    has_complete_positions = all(
        row["latitude"] is not None and row["longitude"] is not None for row in rows
    )
    if times != snapshots or not has_complete_positions:
        excluded["incomplete"] += 1
        continue

    points = [unit_vector(row["latitude"], row["longitude"]) for row in rows]
    step_distances = [
        angular_distance(a, b) * EARTH_RADIUS_KM for a, b in zip(points, points[1:])
    ]
    endpoint_angle = angular_distance(points[0], points[-1])
    endpoint_distance = endpoint_angle * EARTH_RADIUS_KM
    if endpoint_distance < MIN_ENDPOINT_DISTANCE_KM:
        excluded["stationary"] += 1
        continue
    if max(step_distances) > MAX_STEP_DISTANCE_KM:
        excluded["implausibleJump"] += 1
        continue

    deviations = [
        distance_to_geodesic_arc(point, points[0], points[-1], endpoint_angle)
        for point in points
    ]
    path_distance = sum(step_distances)
    callsign = next((row["callsign"].strip() for row in rows if row["callsign"]), icao24.upper())
    aircraft.append(
        {
            "icao24": icao24,
            "callsign": callsign,
            "endpointKm": round(endpoint_distance, 2),
            "pathKm": round(path_distance, 2),
            "excessKm": round(path_distance - endpoint_distance, 2),
            "efficiencyPct": round(100 * endpoint_distance / path_distance, 2),
            "rmsDeviationKm": round(math.sqrt(sum(value * value for value in deviations) / len(deviations)), 2),
            "maxDeviationKm": round(max(deviations), 2),
        }
    )

payload = {
    "capture": {"first": snapshots[0], "last": snapshots[-1], "snapshots": len(snapshots)},
    "filters": {
        "minEndpointDistanceKm": MIN_ENDPOINT_DISTANCE_KM,
        "maxStepDistanceKm": MAX_STEP_DISTANCE_KM,
    },
    "excluded": excluded,
    "aircraft": aircraft,
}
OUTPUT.write_text(
    "window.GEODESIC_DEVIATION_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n",
    encoding="ascii",
)
print(f"Wrote {OUTPUT} with {len(aircraft)} aircraft")
