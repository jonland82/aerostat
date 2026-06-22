from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
DATA_PATH = HERE.parents[1] / "visualizations" / "geodesic-deviation" / "deviation-data.js"
OUTPUT_PATH = HERE / "rms-deviation-distribution.pdf"


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

fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.35), constrained_layout=True)

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
