#!/usr/bin/env python3
"""Generate the paper's restrained, publication-style SVG figure set."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle
import numpy as np


BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "figures_refined"

INK = "#17212b"
MUTED = "#64717d"
NAVY = "#174a6e"
TEAL = "#247a78"
AMBER = "#b96532"
PALE = "#edf2f5"
PALE_TEAL = "#e4f0ef"
RULE = "#cbd3d9"

# Figures are displayed below their native width in the HTML.  These sizes are
# deliberately larger than Matplotlib's defaults so labels remain readable there.
READABLE_TICK = 10.5
READABLE_LABEL = 12.5
READABLE_LEGEND = 10.5
READABLE_PANEL = 11.5

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans"],
        "mathtext.fontset": "stix",
        "font.size": 9.5,
        "axes.titlesize": 10,
        "axes.labelsize": 9.5,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "axes.linewidth": 0.8,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "lines.linewidth": 1.8,
        # Outline text so scientific glyphs render identically without local STIX fonts.
        "svg.fonttype": "path",
        "svg.hashsalt": "scale-continuation-publication-figures",
    }
)


def finish(fig: plt.Figure, filename: str) -> None:
    OUTPUT.mkdir(exist_ok=True)
    svg_path = OUTPUT / filename
    fig.savefig(
        svg_path,
        format="svg",
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": "publication_figures.py", "Date": None},
    )
    # Matplotlib writes trailing spaces inside multiline SVG path data.  Remove
    # them so generated assets pass repository whitespace checks reproducibly.
    svg_text = svg_path.read_text(encoding="utf-8")
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_text.splitlines()) + "\n",
        encoding="utf-8",
    )
    fig.savefig(
        OUTPUT / filename.replace(".svg", ".png"),
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": "publication_figures.py"},
    )
    plt.close(fig)


def panel_label(
    ax: plt.Axes, label: str, subtitle: str | None = None, fontsize: float = 9,
) -> None:
    text = label if subtitle is None else f"{label}  {subtitle}"
    ax.text(
        0.0,
        1.04,
        text,
        transform=ax.transAxes,
        color=INK,
        fontsize=fontsize,
        fontweight="bold",
        va="bottom",
    )


def clean_axes(ax: plt.Axes, grid: bool = False) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    if grid:
        ax.grid(True, color=RULE, linewidth=0.55, alpha=0.65)
        ax.set_axisbelow(True)


def readable_axes(
    ax: plt.Axes, labelsize: float = READABLE_LABEL, ticksize: float = READABLE_TICK,
) -> None:
    """Apply the shared, HTML-safe type scale used by Figures 7--11."""
    ax.tick_params(axis="both", labelsize=ticksize)
    ax.xaxis.label.set_size(labelsize)
    ax.yaxis.label.set_size(labelsize)


def figure_1() -> None:
    fig, axes = plt.subplots(
        2, 1, figsize=(7.6, 4.25), gridspec_kw={"height_ratios": [1, 1.2]},
        constrained_layout=True,
    )
    ax = axes[0]
    x = np.geomspace(0.5, 32, 400)
    eta = 0.15 + 0.9 * np.exp(-0.5 * (np.log2(x / 2) / 1.15) ** 2)
    ax.plot(x, eta, color=NAVY)
    ax.axvline(8, color=AMBER, linestyle=(0, (3, 2)), linewidth=1.2)
    ax.set(xscale="log", xlim=(0.5, 32), ylim=(0, 1.25), ylabel=r"$\eta(L)$")
    ax.set_xticks([0.5, 1, 2, 4, 8, 16, 32], [r"$L_{\min}$", "1", "2", "4", "8", "16", "32"])
    ax.set_yticks([0, 1])
    clean_axes(ax)
    panel_label(ax, "a", "Intensity per unit log scale")
    ax.text(8.25, 1.12, r"observation limit $R$", color=AMBER, va="top")

    ax = axes[1]
    ax.set_xscale("log")
    ax.set_xlim(0.5, 32)
    ax.set_ylim(-0.2, 1.0)
    ax.axvspan(0.5, 8, color=PALE)
    ax.axvline(8, color=AMBER, linestyle=(0, (3, 2)), linewidth=1.2)
    observed = np.asarray([0.58, 0.78, 1.15, 1.42, 1.55, 2.0, 2.35, 3.25, 4.1, 5.0, 5.35, 6.3])
    tail = np.asarray([9.2, 11.5, 16.5, 22.0, 28.0])
    ax.scatter(observed, np.full_like(observed, 0.2), s=18, color=NAVY, zorder=3)
    ax.scatter(tail, np.full_like(tail, 0.2), s=18, facecolor="white", edgecolor=MUTED, zorder=3)
    ax.set_xticks([0.5, 1, 2, 4, 8, 16, 32], [r"$L_{\min}$", "1", "2", "4", "8", "16", "32"])
    ax.set_yticks([])
    ax.set_xlabel("physical scale $L$  (logarithmic)")
    clean_axes(ax)
    panel_label(ax, "b", "Observed scales and unobserved tail")
    ax.text(1.7, 0.62, "observed", color=NAVY, ha="center", fontweight="bold")
    ax.text(16, 0.62, "unobserved", color=MUTED, ha="center", fontweight="bold")
    ax.plot([10.5, 22], [0.42, 0.42], color=MUTED, lw=1.0)
    ax.plot([10.5, 10.5], [0.36, 0.48], color=MUTED, lw=1.0)
    ax.plot([22, 22], [0.36, 0.48], color=MUTED, lw=1.0)
    ax.text(15.2, 0.54, r"$N(R,S)$", color=INK, ha="center")
    finish(fig, "fig-01-scale-point-process.svg")


def figure_2() -> None:
    fig, ax = plt.subplots(figsize=(7.4, 2.65), constrained_layout=True)
    ax.set(xlim=(-0.15, 4.75), ylim=(-0.65, 1.15))
    ax.axis("off")
    ax.plot([0, 4.2], [0, 0], color=INK, linewidth=1.1)
    bounds = [0, 1, 2, 3, 4]
    labels = ["8", "16", "32", "64", "128"]
    outcomes = [True, False, True, False]
    intervals = ["(8, 16]", "(16, 32]", "(32, 64]", "(64, 128]"]
    for x, label in zip(bounds, labels):
        ax.plot([x, x], [-0.08, 0.08], color=INK, linewidth=1.0)
        ax.text(x, -0.16, label, ha="center", va="top", color=MUTED, fontsize=9.5)
    for index, (hit, interval) in enumerate(zip(outcomes, intervals)):
        x = index + 0.5
        ax.scatter(
            [x], [0.52], s=125, facecolor=NAVY if hit else "white",
            edgecolor=NAVY if hit else MUTED, linewidth=1.2,
        )
        ax.text(x, 0.77, r"$p=1/2$", ha="center", color=INK, fontsize=10.5)
        ax.text(
            x, 0.28, "hit" if hit else "miss", ha="center",
            color=NAVY if hit else MUTED, fontsize=9.5,
        )
        ax.text(x, -0.42, interval + " m", ha="center", color=INK, fontsize=9.5)
    ax.text(
        4.38, 0.61, r"$P(\mathrm{at\ least\ one\ hit})$", color=AMBER,
        ha="left", fontsize=10.5,
    )
    ax.text(
        4.38, 0.38, r"$=1-(1/2)^4=0.9375$", color=AMBER,
        ha="left", fontsize=10.5, fontweight="bold",
    )
    finish(fig, "fig-02-coin-flip.svg")


def figure_3() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.15), constrained_layout=True, sharey=True)
    x = np.geomspace(0.08, 1600, 500)
    for ax, model in zip(axes, ("A", "B")):
        y = np.ones_like(x) if model == "A" else np.where(x <= 8, 1, (8 / x) ** 2)
        ax.axvspan(0.08, 8, color=PALE)
        ax.plot(x, y, color=NAVY)
        ax.axvline(8, color=AMBER, linestyle=(0, (3, 2)), linewidth=1.2)
        obs = np.geomspace(0.12, 7.4, 12)
        tail = np.geomspace(11, 1000, 7)
        ax.scatter(obs, np.full_like(obs, 0.0015), s=11, color=NAVY, zorder=3)
        ax.scatter(tail, np.full_like(tail, 0.0015), s=14, facecolor="white", edgecolor=MUTED, linewidth=0.7)
        ax.set(xscale="log", yscale="log", xlim=(0.08, 1600), ylim=(8e-4, 2.2), xlabel="$L$")
        clean_axes(ax, grid=True)
        ax.tick_params(axis="both", labelsize=9.5)
        ax.xaxis.label.set_size(10.5)
        ax.text(0.1, 1.38, "observed", color=NAVY, fontsize=9.5)
        ax.text(11, 1.38, "assumed tail", color=MUTED, fontsize=9.5)
        ax.text(7.4, 1.72, "$R=8$ m", color=AMBER, fontsize=9.5, ha="right")
    axes[0].set_ylabel(r"intensity $\eta(L)$")
    axes[0].yaxis.label.set_size(10.5)
    panel_label(axes[0], "a", r"Model A: $\eta_A(L)=1$", fontsize=10.25)
    panel_label(axes[1], "b", r"Model B: $\eta_B(L)=(8/L)^2$ for $L>8$", fontsize=10.25)
    finish(fig, "fig-03-decaying-tail.svg")


def flat_box(ax: plt.Axes, xy: tuple[float, float], width: float, height: float,
             text: str, edge: str = NAVY, fill: str = "white") -> Rectangle:
    box = Rectangle(xy, width, height, facecolor=fill, edgecolor=edge, linewidth=1.2)
    ax.add_patch(box)
    ax.text(xy[0] + width / 2, xy[1] + height / 2, text, ha="center", va="center", color=INK)
    return box


def arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float],
          color: str = MUTED, style: str = "-") -> None:
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=9,
                                 color=color, linewidth=1.2, linestyle=style))


def figure_4() -> None:
    fig, ax = plt.subplots(figsize=(7.6, 3.1), constrained_layout=True)
    ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis("off")
    flat_box(ax, (0.03, 0.37), 0.22, 0.25, "all observations\nwith " + r"$L\leq8$ m", fill=PALE)
    flat_box(ax, (0.36, 0.66), 0.14, 0.14, "Model A", edge=AMBER)
    flat_box(ax, (0.36, 0.20), 0.14, 0.14, "Model B", edge=AMBER)
    arrow(ax, (0.25, 0.52), (0.36, 0.73), INK)
    arrow(ax, (0.25, 0.47), (0.36, 0.27), INK)
    ax.plot([0.52, 0.52], [0.08, 0.92], color=MUTED, linestyle=(0, (3, 3)), linewidth=1)
    ax.text(0.52, 0.95, "$R=8$ m", ha="center", color=MUTED)
    arrow(ax, (0.50, 0.73), (0.78, 0.73), AMBER)
    arrow(ax, (0.50, 0.27), (0.78, 0.27), AMBER)
    ax.text(0.81, 0.73, "unbounded scales\nalmost surely", va="center", color=INK)
    ax.text(0.81, 0.27, "positive probability of\nno larger structure", va="center", color=INK)
    ax.text(0.68, 0.04, "identical observations; incompatible tails", ha="center", color=MUTED)
    finish(fig, "fig-04-finite-data-tail.svg")


def figure_5() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.25), constrained_layout=True)
    ax.set(xlim=(0, 10.5), ylim=(0, 2.35))
    ax.axvspan(1.2, 8.8, color=PALE_TEAL)
    ax.axvline(1.2, color=AMBER, linestyle=(0, (3, 2)), linewidth=1.2)
    ax.axvline(8.8, color=MUTED, linestyle=(0, (3, 2)), linewidth=1.2)
    x = np.linspace(1.2, 8.3, 100)
    ax.plot(x, 0.25 + 0.2 * x, color=NAVY, linewidth=2.7)
    ax.annotate(
        r"$\langle F_\ell\rangle\approx2\varepsilon\ell$",
        xy=(6.4, 1.53), xytext=(4.0, 1.98), color=NAVY, fontsize=18,
        arrowprops={"arrowstyle": "-", "color": NAVY, "lw": 1.1},
    )
    ax.annotate("energy transfer toward larger lengths", xy=(7.7, 0.35), xytext=(2.0, 0.35),
                color=TEAL, va="center", fontsize=12.5,
                arrowprops={"arrowstyle": "-|>", "color": TEAL, "lw": 1.7})
    ax.set_xticks([0, 1.2, 8.8], ["0", "$L_f$", r"$\ell_\alpha$"])
    ax.set_yticks([])
    ax.set_xlabel(r"separation length $\ell$")
    ax.set_ylabel("mean flux")
    clean_axes(ax)
    ax.tick_params(axis="x", labelsize=12)
    ax.xaxis.label.set_size(13.5)
    ax.yaxis.label.set_size(13.5)
    ax.text(
        1.2, -0.2, "forcing", color=AMBER, ha="center", fontsize=11.5,
        transform=ax.get_xaxis_transform(),
    )
    ax.text(
        8.8, -0.2, "range limit", color=MUTED, ha="center", fontsize=11.5,
        transform=ax.get_xaxis_transform(),
    )
    finish(fig, "fig-05-inverse-flux.svg")


def eddy(
    ax: plt.Axes,
    center: tuple[float, float],
    radius: float,
    color: str = NAVY,
    direction: int = 1,
    phase: float = 0.0,
    rings: int = 1,
    linewidth: float = 1.15,
    linestyle: str = "-",
) -> None:
    """Draw a compact vortex glyph with a legible tangential arrowhead."""
    for ring in range(rings):
        scale = 1.0 - 0.31 * ring
        theta = np.linspace(phase + 0.28, phase + 2 * np.pi - 0.28, 110)
        if direction < 0:
            theta = theta[::-1]
        x = center[0] + radius * scale * np.cos(theta)
        y = center[1] + 1.18 * radius * scale * np.sin(theta)
        alpha = 1.0 if ring == 0 else 0.58
        width = linewidth if ring == 0 else 0.85 * linewidth
        ax.plot(x, y, color=color, linewidth=width, linestyle=linestyle, alpha=alpha)
        ax.add_patch(
            FancyArrowPatch(
                (x[-9], y[-9]), (x[-1], y[-1]), arrowstyle="-|>",
                mutation_scale=7.5 + 18 * radius, color=color,
                linewidth=width, alpha=alpha,
            )
        )


def figure_6() -> None:
    fig, ax = plt.subplots(figsize=(8.0, 3.35), constrained_layout=True)
    ax.set(xlim=(0, 1), ylim=(0, 0.55)); ax.axis("off")

    # A quiet field boundary and subtle scale bands organize the flow without
    # turning the illustration into a collection of presentation-style boxes.
    ax.add_patch(Rectangle((0.025, 0.09), 0.95, 0.38, facecolor="#fbfcfd", edgecolor=RULE, linewidth=0.9))
    ax.add_patch(Rectangle((0.025, 0.09), 0.245, 0.38, facecolor=PALE, edgecolor="none"))
    ax.add_patch(Rectangle((0.27, 0.09), 0.565, 0.38, facecolor=PALE_TEAL, edgecolor="none", alpha=0.42))

    small = [
        (0.065, 0.17), (0.105, 0.145), (0.155, 0.17), (0.215, 0.145),
        (0.080, 0.245), (0.130, 0.235), (0.185, 0.255), (0.235, 0.225),
        (0.060, 0.325), (0.115, 0.335), (0.170, 0.325), (0.225, 0.350),
        (0.090, 0.405), (0.150, 0.405), (0.215, 0.415),
    ]
    for index, center in enumerate(small):
        radius = (0.014, 0.017, 0.020)[index % 3]
        eddy(
            ax, center, radius, direction=1 if index % 2 == 0 else -1,
            phase=0.45 * (index % 4), linewidth=1.05,
        )

    medium = [
        ((0.325, 0.18), 0.032), ((0.405, 0.17), 0.041), ((0.505, 0.19), 0.047),
        ((0.315, 0.34), 0.038), ((0.415, 0.35), 0.046), ((0.535, 0.35), 0.054),
    ]
    for index, (center, radius) in enumerate(medium):
        eddy(
            ax, center, radius, color=NAVY if index < 3 else TEAL,
            direction=-1 if index % 2 else 1, phase=0.6 * index,
            linewidth=1.25,
        )

    eddy(ax, (0.675, 0.285), 0.105, NAVY, direction=1, phase=0.4, rings=2, linewidth=1.55)
    eddy(
        ax, (0.915, 0.285), 0.085, MUTED, direction=-1, phase=1.0,
        rings=2, linewidth=1.25, linestyle=(0, (5, 3)),
    )

    ax.plot([0.835, 0.835], [0.09, 0.47], color=AMBER, linestyle=(0, (3, 2)), linewidth=1.25)
    ax.text(0.82, 0.495, r"observation limit  $R=8\,\mathrm{m}$", ha="right", color=AMBER, fontsize=10.5)
    ax.text(0.145, 0.495, r"forcing  $L_f=1\,\mathrm{m}$", ha="center", color=AMBER, fontsize=10.5)

    ax.text(0.145, 0.112, "$L_f$", ha="center", color=MUTED, fontsize=10.5)
    ax.text(0.405, 0.112, r"$2L_f\ \mathrm{to}\ 4L_f$", ha="center", color=MUTED, fontsize=10.5)
    ax.text(0.675, 0.112, "$R=8L_f$", ha="center", color=MUTED, fontsize=10.5)
    ax.text(0.915, 0.112, r"$L>R$?", ha="center", color=MUTED, fontsize=10.5)

    arrow(ax, (0.17, 0.045), (0.76, 0.045), TEAL)
    ax.text(
        0.465, 0.058, "inverse transfer: coherent scale increases", ha="center",
        va="bottom", color=TEAL, fontsize=11.5, fontweight="bold",
    )
    finish(fig, "fig-06-inverse-cascade-flow.svg")


def figure_7() -> None:
    rng = np.random.default_rng(17)
    n = 1500
    t = np.geomspace(1, 1e4, n)
    signal = 0.82 + rng.normal(0, 0.75, n)
    running = np.cumsum(signal) / np.arange(1, n + 1)
    fig, ax = plt.subplots(figsize=(7.1, 3.55), constrained_layout=True)
    ax.plot(t, signal, color=RULE, linewidth=0.65, alpha=0.82, label="instantaneous flux")
    ax.plot(t, running, color=NAVY, linewidth=2.4, label="running average")
    ax.axhline(0.82, color=AMBER, linestyle=(0, (4, 3)), linewidth=1.4, label="ensemble mean")
    ax.set(xscale="log", xlabel="averaging time $T$", ylabel="flux", ylim=(-2.1, 3.2))
    clean_axes(ax, grid=True)
    readable_axes(ax)
    ax.legend(
        ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.02),
        fontsize=READABLE_LEGEND, handlelength=2.5,
    )
    ax.text(8e3, 1.02, r"$\langle F_\ell\rangle>0$", color=AMBER, ha="right", fontsize=14)
    finish(fig, "fig-07-ergodicity.svg")


def figure_8() -> None:
    fig, ax = plt.subplots(figsize=(7.25, 3.85), constrained_layout=True)
    k = np.linspace(0, 8, 600)
    e = 0.24 * np.exp(-0.34 * k) + 0.94 * np.exp(-0.5 * ((k - 1.55) / 0.82) ** 2)
    cumulative = np.r_[0.0, np.cumsum(0.5 * (e[1:] + e[:-1]) * np.diff(k))]
    theta = 0.60
    kt = float(np.interp(theta * cumulative[-1], cumulative, k))
    left = k <= kt

    ax.fill_between(k, e, color=PALE, alpha=0.72, linewidth=0)
    ax.fill_between(k[left], e[left], color=PALE_TEAL, linewidth=0)
    ax.plot(k, e, color=NAVY, linewidth=2.7)
    ax.axvline(kt, color=AMBER, linestyle=(0, (3, 2)), linewidth=1.5)
    ax.set(xlim=(0, 8), ylim=(0, 1.38), xlabel="wave number $k$", ylabel="energy spectrum $E(k,t)$")
    ax.set_xticks([0, kt, 4, 8], ["0", r"$k_{\theta}(t)$", "4", "8"])
    ax.set_yticks([0, 0.5, 1.0])
    clean_axes(ax, grid=True)
    readable_axes(ax, labelsize=13, ticksize=11)

    ax.text(
        0.90, 0.72, "shaded area\n= energy fraction " + r"$\theta$", color=TEAL,
        fontsize=12.5, ha="center", va="center", fontweight="bold", linespacing=1.25,
    )
    ax.text(
        4.18, 1.15,
        r"$\int_0^{k_{\theta}(t)}E(k,t)\,dk$"
        "\n" r"$=\theta\!\int_0^\infty E(k,t)\,dk$",
        color=INK, fontsize=14.5, linespacing=1.35,
    )
    ax.text(
        4.18, 0.27,
        r"smaller $k_{\theta}(t)$  $\Longleftrightarrow$  larger $L(t)=k_{\theta}(t)^{-1}$",
        color=NAVY, fontsize=12.5,
    )
    finish(fig, "fig-08-large-scale.svg")


def figure_9() -> None:
    t = np.linspace(0, 120, 400)
    length = (1 + t / 15) ** 1.5
    fig, ax = plt.subplots(figsize=(7.1, 3.75), constrained_layout=True)
    ax.plot(t, length, color=NAVY, linewidth=2.7)
    ax.axhline(8, color=AMBER, linestyle=(0, (4, 3)), linewidth=1.4)
    ax.scatter([0, 45, 120], [1, 8, 27], color=AMBER, s=38, zorder=3)
    ax.annotate("$(0,1)$", (0, 1), xytext=(7, 1.9), color=MUTED, fontsize=11.5)
    ax.annotate("$(45,8)$", (45, 8), xytext=(38, 10.1), color=AMBER, fontsize=11.5)
    ax.annotate("$(120,27)$", (120, 27), xytext=(103, 28.2), color=AMBER, fontsize=11.5)
    ax.text(118, 8.7, "observation limit", color=AMBER, ha="right", fontsize=12)
    ax.text(7, 25.2, r"$L(t)=1\,\mathrm{m}\,(1+t/15\,\mathrm{s})^{3/2}$", color=INK, fontsize=15)
    ax.text(78, 18.0, "conditional growth", color=NAVY, fontsize=12.5)
    ax.set(xlim=(0, 122), ylim=(0, 30), xlabel="time $t$ (s)", ylabel="large scale $L(t)$ (m)")
    clean_axes(ax, grid=True)
    readable_axes(ax)
    finish(fig, "fig-09-conditional-growth.svg")


def figure_10() -> None:
    source = json.loads((BASE / "focused_resolution_results" / "results.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.55), constrained_layout=True)
    for n, color in ((256, NAVY), (512, AMBER)):
        runs = [r for r in source["runs"] if int(r["config"]["n"]) == n]
        spectra = np.asarray([r["analysis"]["mean_spectrum"] for r in runs])
        mean = spectra.mean(axis=0); low = spectra.min(axis=0); high = spectra.max(axis=0)
        k = np.arange(len(mean)); valid = (k > 0) & (mean > 0)
        axes[0].fill_between(k[valid], low[valid], high[valid], color=color, alpha=0.12, linewidth=0)
        axes[0].loglog(k[valid], mean[valid], color=color, label=f"$N={n}$")
        times = np.asarray([row["time"] for row in runs[0]["records"]])
        lengths = np.asarray([[row["smooth_length"] for row in r["records"]] for r in runs])
        axes[1].fill_between(times, lengths.min(axis=0), lengths.max(axis=0), color=color, alpha=0.12, linewidth=0)
        axes[1].plot(times, lengths.mean(axis=0), color=color, label=f"$N={n}$")
    ref_k = np.asarray([2.0, 12.0]); anchor = 5.5e-5
    axes[0].loglog(ref_k, anchor * (ref_k / 2) ** (-5 / 3), color=INK, linestyle=(0, (4, 3)), label="$k^{-5/3}$")
    axes[0].axvspan(15, 17, color=AMBER, alpha=0.10)
    axes[0].set(xlabel="wave number $k$", ylabel="spectrum $E_N(k)$")
    clean_axes(axes[0]); readable_axes(axes[0], labelsize=12, ticksize=10)
    panel_label(axes[0], "a", "Short-run spectrum", fontsize=READABLE_PANEL)
    axes[0].legend(fontsize=READABLE_LEGEND, handlelength=2.4)
    axes[1].set(xlabel="time", ylabel="characteristic scale $L_E$")
    clean_axes(axes[1], grid=True); readable_axes(axes[1], labelsize=12, ticksize=10)
    panel_label(axes[1], "b", "Characteristic-scale growth", fontsize=READABLE_PANEL)
    axes[1].legend(fontsize=READABLE_LEGEND, handlelength=2.4)
    finish(fig, "fig-10-resolution.svg")


def figure_11() -> None:
    source = json.loads((BASE / "time-maturity-analysis.json").read_text())
    times = np.asarray([2.5, 5.0, 10.0, 15.0])
    keys = [str(t) for t in times]
    run_spectra = np.asarray(
        [[r["checkpoints"][i]["mean_spectrum"] for r in source["runs"]] for i in range(4)]
    )
    spectra = run_spectra.mean(axis=1)
    colors = ["#a9bbc7", "#648da5", TEAL, NAVY]
    fig = plt.figure(figsize=(7.8, 6.45), constrained_layout=True)
    axes = fig.subplot_mosaic([["spectrum", "slope"], ["flux", "flux"]])
    ax = axes["spectrum"]
    for time, spectrum, color in zip(times, spectra, colors):
        k = np.arange(len(spectrum)); valid = (k > 0) & (spectrum > 0)
        ax.loglog(k[valid], spectrum[valid], color=color, label=f"$t={time:g}$")
    ax.axvspan(4, 12, color=TEAL, alpha=0.07)
    ax.axvspan(15, 17, color=AMBER, alpha=0.10)
    fit_k = np.arange(4, 13, dtype=float)
    amp = np.exp(np.mean(np.log(spectra[-1, 4:13]) + (5 / 3) * np.log(fit_k)))
    ax.loglog(fit_k, amp * fit_k ** (-5 / 3), color=INK, linestyle=(0, (4, 3)), label="$k^{-5/3}$")
    ax.set(xlabel="wave number $k$", ylabel="spectrum $E_N(k)$"); clean_axes(ax)
    readable_axes(ax, labelsize=11.5, ticksize=9.75)
    panel_label(ax, "a", "Spectrum through time", fontsize=READABLE_PANEL)
    ax.legend(ncol=2, fontsize=10, handlelength=2.3)

    ax = axes["slope"]
    broad = np.asarray([source["aggregate"][key]["shell_slope"]["mean"] for key in keys])
    broad_e = np.asarray([source["aggregate"][key]["shell_slope"]["standard_deviation"] for key in keys])
    interior = np.asarray([source["aggregate"][key]["interior_shell_slope_k4_k12"]["mean"] for key in keys])
    interior_e = np.asarray([source["aggregate"][key]["interior_shell_slope_k4_k12"]["standard_deviation"] for key in keys])
    ax.errorbar(times, broad, yerr=broad_e, color=MUTED, marker="o", capsize=2.5, label=r"$k=2\ldots12$")
    ax.errorbar(times, interior, yerr=interior_e, color=NAVY, marker="o", capsize=2.5, label=r"$k=4\ldots12$")
    ax.axhline(-5 / 3, color=AMBER, linestyle=(0, (4, 3)), linewidth=1.2, label="$-5/3$")
    ax.set(xlabel="time", ylabel="fitted slope"); clean_axes(ax, grid=True)
    readable_axes(ax, labelsize=11.5, ticksize=9.75)
    panel_label(ax, "b", "Low-$k$ slope", fontsize=READABLE_PANEL)
    ax.legend(fontsize=10, handlelength=2.3)

    ax = axes["flux"]
    flux = np.asarray([source["aggregate"][key]["interior_transfer_mean_over_epsilon_k6_k12"]["mean"] for key in keys])
    flux_e = np.asarray([source["aggregate"][key]["interior_transfer_mean_over_epsilon_k6_k12"]["standard_deviation"] for key in keys])
    cv = np.asarray([source["aggregate"][key]["interior_transfer_flatness_cv_k6_k12"]["mean"] for key in keys])
    ax.errorbar(times, flux, yerr=flux_e, color=NAVY, marker="o", capsize=2.5, label=r"mean $\Pi_{\leq K}/\varepsilon$")
    ax.plot(times, cv, color=TEAL, marker="o", label="plateau CV")
    ax.axhline(1, color=AMBER, linestyle=(0, (4, 3)), linewidth=1.2, label="unit flux")
    ax.set(xlabel="time", ylabel="dimensionless diagnostic", ylim=(0, 1.38)); clean_axes(ax, grid=True)
    readable_axes(ax, labelsize=11.5, ticksize=9.75)
    panel_label(ax, "c", r"Flux plateau, $K=6\ldots12$", fontsize=READABLE_PANEL)
    ax.legend(ncol=3, fontsize=10, handlelength=2.3)
    finish(fig, "fig-11-maturity.svg")


def figure_12() -> None:
    fig, ax = plt.subplots(figsize=(7.8, 3.35), constrained_layout=True)
    ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis("off")

    ax.add_patch(Rectangle((0.035, 0.43), 0.35, 0.34, facecolor=PALE, edgecolor=NAVY, linewidth=1.35))
    ax.add_patch(Rectangle((0.615, 0.43), 0.35, 0.34, facecolor=PALE_TEAL, edgecolor=AMBER, linewidth=1.35))
    ax.text(0.055, 0.81, "ESTABLISHED", color=NAVY, fontsize=10.5, fontweight="bold")
    ax.text(0.635, 0.81, "TARGET THEOREM", color=AMBER, fontsize=10.5, fontweight="bold")
    ax.text(
        0.21, 0.63, "positive inverse flux", ha="center", va="center",
        color=INK, fontsize=13, fontweight="bold",
    )
    ax.text(
        0.21, 0.52, "under a growing-box limit", ha="center", va="center",
        color=MUTED, fontsize=11.5,
    )
    ax.text(0.79, 0.66, r"one flow on $\mathbb{R}^2$", ha="center", color=INK, fontsize=12)
    ax.text(
        0.79, 0.535, r"$\mathbb{P}\{L(t)\to\infty\}=1$", ha="center",
        color=INK, fontsize=15,
    )

    ax.plot([0.395, 0.605], [0.60, 0.60], color=MUTED, linestyle=(0, (4, 4)), linewidth=1.4)
    ax.add_patch(Circle((0.50, 0.60), 0.052, facecolor="white", edgecolor=AMBER, linewidth=1.3, zorder=3))
    ax.text(0.50, 0.60, "?", ha="center", va="center", color=AMBER, fontsize=18, fontweight="bold", zorder=4)
    ax.text(0.50, 0.76, "missing logical bridge", ha="center", color=MUTED, fontsize=11.5, fontweight="bold")
    ax.text(
        0.50, 0.405, "uniform control in time, scale,\nand one realization",
        ha="center", va="top", color=MUTED, fontsize=10.5, linespacing=1.25,
    )

    ax.text(0.5, 0.255, "possible stopping mechanisms", ha="center", color=MUTED, fontsize=10.5)
    blockers = [(0.07, "drag"), (0.38, "finite forcing time"), (0.69, "finite domain / condensate")]
    for x, label in blockers:
        ax.add_patch(Rectangle((x, 0.08), 0.24, 0.115, facecolor="white", edgecolor=RULE, linewidth=1.0))
        ax.text(x + 0.12, 0.1375, label, ha="center", va="center", color=INK, fontsize=10.5)
    finish(fig, "fig-12-open-problem.svg")


def main() -> None:
    for make in (
        figure_1, figure_2, figure_3, figure_4, figure_5, figure_6,
        figure_7, figure_8, figure_9, figure_10, figure_11, figure_12,
    ):
        make()
    print(f"wrote 12 SVG figures to {OUTPUT}")


if __name__ == "__main__":
    main()
