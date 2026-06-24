from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
DATA_PATH = HERE.parents[1] / "visualizations" / "geodesic-deviation" / "deviation-data.js"
STATE_PATH = HERE.parents[1] / "data" / "global_states.parquet"
OUTPUT_PATH = HERE / "rms-deviation-distribution.pdf"
SEQUENTIAL_OUTPUT_PATH = HERE / "sequential-boundary-detection.pdf"
EARTH_RADIUS_KM = 6_371.0088
MIN_ENDPOINT_DISTANCE_KM = 25
MAX_STEP_DISTANCE_KM = 30
BOUNDARY_RMS_KM = 0.1
BOOTSTRAP_REPS = 300


raw = DATA_PATH.read_text(encoding="utf-8")
payload = json.loads(raw[raw.index("{") :].rstrip().rstrip(";"))
deviations = np.asarray([row["rmsDeviationKm"] for row in payload["aircraft"]], dtype=float)
positive = deviations[deviations > 0]
log_deviations = np.log(positive)

cyan = "#24a8c7"
cyan_light = "#9fefff"
orange = "#d88735"
ink = "#18313b"
grid = "#d8e6ea"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 8.2,
        "axes.labelcolor": ink,
        "axes.edgecolor": "#86a3ad",
        "xtick.color": "#526b74",
        "ytick.color": "#526b74",
    }
)

fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.65), constrained_layout=True)

# Match the application's displayed 1st--99th percentile window and 38 bins.
upper = np.ceil(np.quantile(deviations, 0.99) / 5) * 5
bins = np.linspace(0, upper, 39)
display_deviations = np.minimum(deviations, np.nextafter(upper, -np.inf))
axes[0].hist(display_deviations, bins=bins, color=cyan, edgecolor="#087992", linewidth=0.35)
median = float(np.median(deviations))
axes[0].axvline(median, color=orange, linewidth=1.4, linestyle=(0, (3, 2)))
axes[0].text(
    median + upper * 0.025,
    axes[0].get_ylim()[1] * 0.91,
    f"median {median:.1f} km",
    color=orange,
    fontsize=7.4,
    weight="bold",
)
axes[0].set(title="Observed RMS deviation", xlabel="RMS distance to endpoint geodesic (km)", ylabel="Aircraft")

mu = float(log_deviations.mean())
sigma = float(log_deviations.std())
counts, log_bins, _ = axes[1].hist(
    log_deviations,
    bins=38,
    color=cyan_light,
    edgecolor=cyan,
    linewidth=0.4,
)
x = np.linspace(log_bins[0], log_bins[-1], 500)
bin_width = log_bins[1] - log_bins[0]
normal_counts = (
    len(log_deviations)
    * bin_width
    * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    / (sigma * np.sqrt(2 * np.pi))
)
axes[1].plot(x, normal_counts, color=orange, linewidth=1.6, label="moment-matched normal")
axes[1].legend(frameon=False, fontsize=7.1, loc="upper left")
axes[1].set(title="The same cohort in log space", xlabel=r"$\log(D / 1\,\mathrm{km})$", ylabel="Aircraft")

for axis in axes:
    axis.set_axisbelow(True)
    axis.grid(axis="y", color=grid, linewidth=0.55)
    axis.spines[["top", "right"]].set_visible(False)
    axis.title.set_color(ink)
    axis.title.set_fontweight("bold")
    axis.title.set_fontsize(9.2)

fig.savefig(OUTPUT_PATH, bbox_inches="tight")
print(f"Wrote {OUTPUT_PATH}")


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


def empirical_w2(left: np.ndarray, right: np.ndarray, grid_size: int = 1_000) -> float:
    probabilities = (np.arange(grid_size) + 0.5) / grid_size
    left_quantiles = np.quantile(left, probabilities)
    right_quantiles = np.quantile(right, probabilities)
    return float(np.sqrt(np.mean((left_quantiles - right_quantiles) ** 2)))


def sequential_deviation_matrix() -> np.ndarray:
    table = pq.read_table(
        STATE_PATH,
        columns=["requested_time", "icao24", "latitude", "longitude"],
    )
    snapshots = sorted(set(table.column("requested_time").to_pylist()))
    tracks: dict[str, list[dict]] = defaultdict(list)
    for row in table.to_pylist():
        tracks[row["icao24"]].append(row)

    rows_out = []
    for rows in tracks.values():
        rows.sort(key=lambda row: row["requested_time"])
        times = [row["requested_time"] for row in rows]
        has_complete_positions = all(
            row["latitude"] is not None and row["longitude"] is not None for row in rows
        )
        if times != snapshots or not has_complete_positions:
            continue

        points = [unit_vector(row["latitude"], row["longitude"]) for row in rows]
        step_distances = [
            angular_distance(a, b) * EARTH_RADIUS_KM for a, b in zip(points, points[1:])
        ]
        endpoint_angle = angular_distance(points[0], points[-1])
        endpoint_distance = endpoint_angle * EARTH_RADIUS_KM
        if endpoint_distance < MIN_ENDPOINT_DISTANCE_KM:
            continue
        if max(step_distances) > MAX_STEP_DISTANCE_KM:
            continue

        rows_out.append(
            [
                distance_to_geodesic_arc(point, points[0], points[-1], endpoint_angle)
                for point in points
            ]
        )

    return np.asarray(rows_out, dtype=float)


deviation_matrix = sequential_deviation_matrix()
prefix_counts = np.arange(2, deviation_matrix.shape[1] + 1)
prefix_rms = np.sqrt(np.cumsum(deviation_matrix**2, axis=1)[:, 1:] / prefix_counts)
full_rms = prefix_rms[:, -1]
boundary_mask = full_rms <= BOUNDARY_RMS_KM
ordinary_mask = ~boundary_mask

posterior = []
recall = []
for column in range(prefix_rms.shape[1]):
    hits_boundary = int(np.sum(prefix_rms[boundary_mask, column] <= BOUNDARY_RMS_KM))
    hits_ordinary = int(np.sum(prefix_rms[ordinary_mask, column] <= BOUNDARY_RMS_KM))
    posterior.append(hits_boundary / (hits_boundary + hits_ordinary))
    recall.append(hits_boundary / int(np.sum(boundary_mask)))

log_prefix = np.log(np.maximum(prefix_rms, 1e-4))
w2_curve = []
critical_curve = []
rng = np.random.default_rng(20260622)
for column in range(log_prefix.shape[1]):
    boundary_values = log_prefix[boundary_mask, column]
    ordinary_values = log_prefix[ordinary_mask, column]
    w2_curve.append(empirical_w2(boundary_values, ordinary_values))

    bootstrap_radii = []
    for _ in range(BOOTSTRAP_REPS):
        boundary_sample = rng.choice(boundary_values, size=len(boundary_values), replace=True)
        ordinary_sample = rng.choice(ordinary_values, size=len(ordinary_values), replace=True)
        bootstrap_radii.append(
            empirical_w2(boundary_sample, boundary_values, grid_size=300)
            + empirical_w2(ordinary_sample, ordinary_values, grid_size=300)
        )
    critical_curve.append(float(np.quantile(bootstrap_radii, 0.95)))

minutes = prefix_counts - 1
posterior = np.asarray(posterior)
recall = np.asarray(recall)
w2_curve = np.asarray(w2_curve)
critical_curve = np.asarray(critical_curve)

fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.35), constrained_layout=True)

axes[0].plot(minutes, posterior, color=cyan, linewidth=1.7, label="posterior confidence")
axes[0].plot(minutes, recall, color=orange, linewidth=1.2, linestyle=(0, (3, 2)), label="boundary recall")
axes[0].axhline(0.95, color="#788d95", linewidth=0.8, linestyle=":")
crossings = np.flatnonzero(posterior >= 0.95)
if len(crossings):
    crossing_minute = int(minutes[crossings[0]])
    axes[0].axvline(crossing_minute, color=ink, linewidth=0.8, alpha=0.75)
    axes[0].annotate(
        f"{crossing_minute} min",
        xy=(crossing_minute, 0.95),
        xytext=(-32, -24),
        textcoords="offset points",
        color=ink,
        fontsize=7.3,
        weight="bold",
        arrowprops={"arrowstyle": "-", "color": ink, "linewidth": 0.65},
    )
axes[0].set(
    title="Posterior boundary evidence",
    xlabel="Elapsed minutes",
    ylabel="Probability",
    ylim=(-0.02, 1.04),
)
axes[0].legend(
    frameon=False,
    fontsize=7.0,
    loc="upper center",
    bbox_to_anchor=(0.5, -0.22),
    ncol=2,
    handlelength=1.8,
    columnspacing=1.0,
)

axes[1].plot(minutes, w2_curve, color=cyan, linewidth=1.7, label=r"$W_2(P_{0,n},P_{1,n})$")
axes[1].plot(
    minutes,
    critical_curve,
    color=orange,
    linewidth=1.2,
    linestyle=(0, (3, 2)),
    label="bootstrap uncertainty",
)
axes[1].fill_between(minutes, 0, critical_curve, color="#e9f5f8", alpha=0.85)
axes[1].set(
    title="Sequential Wasserstein gap",
    xlabel="Elapsed minutes",
    ylabel=r"log-RMS $W_2$",
)
axes[1].legend(
    frameon=False,
    fontsize=7.0,
    loc="upper center",
    bbox_to_anchor=(0.5, -0.22),
    ncol=2,
    handlelength=1.8,
    columnspacing=1.0,
)

for axis in axes:
    axis.set_axisbelow(True)
    axis.grid(axis="y", color=grid, linewidth=0.55)
    axis.spines[["top", "right"]].set_visible(False)
    axis.title.set_color(ink)
    axis.title.set_fontweight("bold")
    axis.title.set_fontsize(9.2)

fig.savefig(SEQUENTIAL_OUTPUT_PATH, bbox_inches="tight")
print(f"Wrote {SEQUENTIAL_OUTPUT_PATH}")
