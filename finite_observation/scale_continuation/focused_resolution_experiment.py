#!/usr/bin/env python3
"""Focused resolution test of the spectral premise behind L(t) growth."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import platform
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from energy_consistent_solver import Config, run


def analyze_run(result: dict[str, object]) -> dict[str, float]:
    config = result["config"]
    records = result["records"]
    duration = float(config["duration"])
    late = [row for row in records if row["time"] >= 0.6 * duration]
    spectra = np.asarray([row["energy_spectrum"] for row in late], dtype=float)
    transfers = np.asarray(
        [row["cumulative_nonlinear_transfer"] for row in late], dtype=float
    )
    mean_spectrum = spectra.mean(axis=0)
    mean_transfer = transfers.mean(axis=0)
    k_force = float(config["k_force"])
    k = np.arange(len(mean_spectrum), dtype=float)
    fit = (k >= 2) & (k <= k_force - 4) & (mean_spectrum > 0)
    x = np.log(k[fit])
    y = np.log(mean_spectrum[fit])
    slope, intercept = np.polyfit(x, y, 1)
    prediction = intercept + slope * x
    r2 = 1.0 - np.sum((y - prediction) ** 2) / np.sum((y - y.mean()) ** 2)
    plateau = (k >= 2) & (k <= k_force / 2)
    plateau_values = mean_transfer[plateau]
    epsilon = float(config["epsilon"])
    return {
        "spectral_slope": float(slope),
        "spectral_slope_error_from_minus_five_thirds": float(abs(slope + 5 / 3)),
        "spectral_fit_r2": float(r2),
        "inverse_transfer_mean_over_epsilon": float(plateau_values.mean() / epsilon),
        "inverse_transfer_flatness_cv": float(
            plateau_values.std() / max(abs(plateau_values.mean()), 1.0e-15)
        ),
        "length_growth_factor": float(
            result["final"]["smooth_length"] / result["initial"]["smooth_length"]
        ),
        "mean_spectrum": mean_spectrum.tolist(),
        "mean_cumulative_transfer": mean_transfer.tolist(),
    }


def plot_summary(runs: list[dict[str, object]], output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    colors = {n: color for n, color in zip(sorted({r["config"]["n"] for r in runs}), ["C0", "C3"])}
    seen: set[int] = set()
    for result in runs:
        n = int(result["config"]["n"])
        analysis = result["analysis"]
        spectrum = np.asarray(analysis["mean_spectrum"])
        k = np.arange(len(spectrum))
        valid = (k > 0) & (spectrum > 0)
        label = f"N={n}" if n not in seen else "_nolegend_"
        seen.add(n)
        axes[0].loglog(k[valid], spectrum[valid], color=colors[n], alpha=0.75, label=label)
        records = result["records"]
        axes[1].plot(
            [row["time"] for row in records],
            [row["smooth_length"] for row in records],
            color=colors[n], alpha=0.75, label=label,
        )
    reference_k = np.asarray([2.0, 12.0])
    anchor = max(r["analysis"]["mean_spectrum"][2] for r in runs)
    axes[0].loglog(reference_k, anchor * (reference_k / 2) ** (-5 / 3), "k--", label=r"$k^{-5/3}$")
    axes[0].axvline(float(runs[0]["config"]["k_force"]), color="0.5", linestyle=":")
    axes[0].set(title="Late-time energy spectrum", xlabel="k", ylabel="E(k)")
    axes[1].set(title="Characteristic-scale growth", xlabel="time", ylabel="L_E")
    axes[0].legend()
    axes[1].legend()
    fig.savefig(output, dpi=170)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolutions", type=int, nargs="+", default=[256, 512])
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--duration", type=float, default=2.5)
    parser.add_argument("--epsilon", type=float, default=0.004)
    parser.add_argument("--k-force", type=float, default=16.0)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    configs = []
    for n in args.resolutions:
        scale = n / 128
        for seed in args.seeds:
            configs.append(
                Config(
                    n=n,
                    seed=seed,
                    epsilon=args.epsilon,
                    k_force=args.k_force,
                    hyperviscosity=3.0e-13 / scale**8,
                    max_dt=0.00125 / scale,
                    duration=args.duration,
                    sample_interval=args.sample_interval,
                    record_spectra=True,
                )
            )

    started = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        runs = list(executor.map(run, configs))
    runs.sort(key=lambda r: (r["config"]["n"], r["config"]["seed"]))
    for result in runs:
        result["analysis"] = analyze_run(result)

    by_resolution: dict[str, dict[str, float]] = {}
    for n in args.resolutions:
        selected = [r for r in runs if r["config"]["n"] == n]
        by_resolution[str(n)] = {
            key: float(np.mean([r["analysis"][key] for r in selected]))
            for key in (
                "spectral_slope",
                "spectral_slope_error_from_minus_five_thirds",
                "spectral_fit_r2",
                "inverse_transfer_mean_over_epsilon",
                "inverse_transfer_flatness_cv",
                "length_growth_factor",
            )
        }
    summary = {
        "scope_warning": "Short transient diagnostic, not an asymptotic scaling test.",
        "environment": {"python": platform.python_version(), "elapsed_seconds": time.perf_counter() - started},
        "requested_runs": len(configs),
        "completed_runs": len(runs),
        "maximum_relative_energy_balance_residual": max(abs(r["relative_energy_balance_residual"]) for r in runs),
        "maximum_relative_injection_error": max(abs(r["realized_injection"] - r["target_injection"]) / r["target_injection"] for r in runs),
        "by_resolution": by_resolution,
        "runs": runs,
    }
    (args.output / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    plot_summary(runs, args.output / "diagnostics.png")
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}, indent=2))
    if summary["maximum_relative_energy_balance_residual"] >= 0.01:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
