#!/usr/bin/env python3
"""Analyze whether a low-wavenumber spectrum matures during a long run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from energy_consistent_solver import grid


def checkpoint_metrics(
    run: dict[str, object], checkpoint: float, window: float
) -> dict[str, object]:
    records = [
        row
        for row in run["records"]
        if checkpoint - window < float(row["time"]) <= checkpoint + 1.0e-10
    ]
    if not records:
        raise ValueError(f"no samples for checkpoint {checkpoint}")
    spectrum = np.asarray([row["energy_spectrum"] for row in records]).mean(axis=0)
    transfer = np.asarray(
        [row["cumulative_nonlinear_transfer"] for row in records]
    ).mean(axis=0)
    n = int(run["config"]["n"])
    radius = grid(n)[3]
    shell = np.floor(radius + 0.5).astype(int)
    counts = np.bincount(shell.ravel(), minlength=len(spectrum))[: len(spectrum)]
    k = np.arange(len(spectrum), dtype=float)
    fit = (k >= 2) & (k <= 12) & (spectrum > 0) & (counts > 0)
    shell_fit = np.polyfit(np.log(k[fit]), np.log(spectrum[fit]), 1)
    shell_slope = float(shell_fit[0])
    per_mode = spectrum / counts
    per_mode_slope = float(
        np.polyfit(np.log(k[fit]), np.log(per_mode[fit]), 1)[0]
    )
    plateau = (k >= 2) & (k <= 8)
    plateau_values = transfer[plateau]
    interior_fit = (k >= 4) & (k <= 12) & (spectrum > 0)
    interior_x = np.log(k[interior_fit])
    interior_y = np.log(spectrum[interior_fit])
    interior_slope = float(np.polyfit(interior_x, interior_y, 1)[0])
    interior_r2 = float(np.corrcoef(interior_x, interior_y)[0, 1] ** 2)
    interior_plateau = transfer[(k >= 6) & (k <= 12)]
    epsilon = float(run["config"]["epsilon"])
    nearest = min(run["records"], key=lambda row: abs(float(row["time"]) - checkpoint))
    return {
        "checkpoint": checkpoint,
        "shell_slope": shell_slope,
        "interior_shell_slope_k4_k12": interior_slope,
        "interior_shell_slope_r2_k4_k12": interior_r2,
        "per_mode_slope": per_mode_slope,
        "inverse_transfer_mean_over_epsilon": float(
            plateau_values.mean() / epsilon
        ),
        "inverse_transfer_flatness_cv": float(
            plateau_values.std() / max(abs(plateau_values.mean()), 1.0e-15)
        ),
        "interior_transfer_mean_over_epsilon_k6_k12": float(
            interior_plateau.mean() / epsilon
        ),
        "interior_transfer_flatness_cv_k6_k12": float(
            interior_plateau.std()
            / max(abs(interior_plateau.mean()), 1.0e-15)
        ),
        "smooth_length": float(nearest["smooth_length"]),
        "mean_spectrum": spectrum.tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=int)
    parser.add_argument(
        "--checkpoints", type=float, nargs="+", default=[2.5, 5.0, 10.0, 15.0]
    )
    parser.add_argument("--window", type=float, default=1.0)
    args = parser.parse_args()

    source = json.loads(args.results.read_text(encoding="utf-8"))
    source_runs = source["runs"]
    if args.resolution is not None:
        source_runs = [
            run for run in source_runs if int(run["config"]["n"]) == args.resolution
        ]
    resolutions = {int(run["config"]["n"]) for run in source_runs}
    if not source_runs or len(resolutions) != 1:
        raise ValueError("select exactly one available resolution with --resolution")
    analyzed_runs = []
    for run in source_runs:
        analyzed_runs.append(
            {
                "n": run["config"]["n"],
                "seed": run["config"]["seed"],
                "checkpoints": [
                    checkpoint_metrics(run, checkpoint, args.window)
                    for checkpoint in args.checkpoints
                ],
            }
        )

    aggregate = {}
    for index, checkpoint in enumerate(args.checkpoints):
        rows = [run["checkpoints"][index] for run in analyzed_runs]
        aggregate[str(checkpoint)] = {
            key: {
                "mean": float(np.mean([row[key] for row in rows])),
                "standard_deviation": float(np.std([row[key] for row in rows], ddof=1)),
            }
            for key in (
                "shell_slope",
                "interior_shell_slope_k4_k12",
                "interior_shell_slope_r2_k4_k12",
                "per_mode_slope",
                "inverse_transfer_mean_over_epsilon",
                "inverse_transfer_flatness_cv",
                "interior_transfer_mean_over_epsilon_k6_k12",
                "interior_transfer_flatness_cv_k6_k12",
                "smooth_length",
            )
        }

    output = {
        "scope_warning": "Two-seed transient diagnostic; not an asymptotic exponent estimate.",
        "window": args.window,
        "aggregate": aggregate,
        "runs": analyzed_runs,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "maturity_analysis.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )

    fig = plt.figure(figsize=(10, 7.6), constrained_layout=True)
    axes = fig.subplot_mosaic([["spectrum", "slope"], ["flux", "flux"]])
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, len(args.checkpoints)))
    for index, (checkpoint, color) in enumerate(zip(args.checkpoints, colors)):
        spectra = np.asarray(
            [run["checkpoints"][index]["mean_spectrum"] for run in analyzed_runs]
        )
        spectrum = spectra.mean(axis=0)
        k = np.arange(len(spectrum))
        valid = (k > 0) & (spectrum > 0)
        axes["spectrum"].loglog(
            k[valid], spectrum[valid], color=color, label=f"t={checkpoint:g}"
        )
    reference_k = np.asarray([4.0, 12.0])
    final_spectrum = np.asarray(
        [run["checkpoints"][-1]["mean_spectrum"] for run in analyzed_runs]
    ).mean(axis=0)
    fit_k = np.arange(4, 13, dtype=float)
    reference_amplitude = np.exp(
        np.mean(np.log(final_spectrum[4:13]) + (5 / 3) * np.log(fit_k))
    )
    axes["spectrum"].loglog(
        reference_k,
        reference_amplitude * reference_k ** (-5 / 3),
        "k--",
        label=r"$k^{-5/3}$",
    )
    axes["spectrum"].axvline(16, color="0.5", linestyle=":")
    axes["spectrum"].set(title="Spectrum through time", xlabel="k", ylabel="E(k)")
    axes["spectrum"].legend()

    times = np.asarray(args.checkpoints)
    shell_slopes = [aggregate[str(t)]["shell_slope"]["mean"] for t in times]
    shell_errors = [
        aggregate[str(t)]["shell_slope"]["standard_deviation"] for t in times
    ]
    interior_slopes = [
        aggregate[str(t)]["interior_shell_slope_k4_k12"]["mean"] for t in times
    ]
    interior_errors = [
        aggregate[str(t)]["interior_shell_slope_k4_k12"]["standard_deviation"]
        for t in times
    ]
    axes["slope"].errorbar(
        times, shell_slopes, yerr=shell_errors, fmt="o-", capsize=3,
        label=r"broad fit, $k=2\ldots12$",
    )
    axes["slope"].errorbar(
        times, interior_slopes, yerr=interior_errors, fmt="o-", capsize=3,
        label=r"interior fit, $k=4\ldots12$",
    )
    axes["slope"].axhline(-5 / 3, color="black", linestyle="--", label=r"$-5/3$")
    axes["slope"].axhline(0, color="0.5", linewidth=0.8)
    axes["slope"].set(
        title="Low-k slope evolution", xlabel="time", ylabel="log-log slope"
    )
    axes["slope"].legend()
    flux_ratios = [
        aggregate[str(t)]["interior_transfer_mean_over_epsilon_k6_k12"]["mean"]
        for t in times
    ]
    flux_errors = [
        aggregate[str(t)]["interior_transfer_mean_over_epsilon_k6_k12"]["standard_deviation"]
        for t in times
    ]
    flux_cvs = [
        aggregate[str(t)]["interior_transfer_flatness_cv_k6_k12"]["mean"]
        for t in times
    ]
    axes["flux"].errorbar(
        times, flux_ratios, yerr=flux_errors, fmt="o-", capsize=3,
        label=r"mean $\Pi_{\leq K}/\varepsilon$",
    )
    axes["flux"].plot(times, flux_cvs, "o-", label="plateau CV")
    axes["flux"].axhline(1, color="black", linestyle="--", label="unit flux")
    axes["flux"].set(
        title=r"Flux over $k=6\ldots12$", xlabel="time", ylabel="dimensionless value"
    )
    axes["flux"].legend()
    fig.savefig(args.output / "maturity_diagnostics.png", dpi=170)
    plt.close(fig)
    print(json.dumps({"aggregate": aggregate}, indent=2))


if __name__ == "__main__":
    main()
