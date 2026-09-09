#!/usr/bin/env python3
"""Parallel ensemble and reduced-law comparison for the validated solver."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import platform
import time
from dataclasses import asdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from energy_consistent_solver import Config, run
from reduced_law_analysis import fit_reduced_laws


def plot_runs(runs: list[dict[str, object]], output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    seen: set[float] = set()
    for result in runs:
        epsilon = float(result["config"]["epsilon"])
        label = f"epsilon={epsilon:g}" if epsilon not in seen else "_nolegend_"
        seen.add(epsilon)
        records = result["records"]
        times = [row["time"] for row in records]
        axes[0].plot(times, [row["smooth_length"] for row in records], label=label, alpha=0.8)
        axes[1].plot(
            times,
            [row["inverse_flux_half_forcing"] for row in records],
            label=label,
            alpha=0.65,
        )
    axes[0].set(title="Energy-weighted scale", xlabel="time", ylabel="L_E")
    axes[1].axhline(0, color="black", linewidth=0.7)
    axes[1].set(title="Inverse transfer into k <= k_f/2", xlabel="time", ylabel="rate")
    axes[0].legend()
    fig.suptitle("Energy-consistent inverse-cascade ensemble")
    fig.savefig(output, dpi=170)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--n", type=int, default=256)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--seeds-per-epsilon", type=int, default=4)
    parser.add_argument(
        "--epsilons", type=float, nargs="+", default=[0.001, 0.002, 0.004, 0.008]
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    scale = args.n / 128
    configs: list[Config] = []
    seed = 1
    for epsilon in args.epsilons:
        for _ in range(args.seeds_per_epsilon):
            configs.append(
                Config(
                    n=args.n,
                    seed=seed,
                    epsilon=epsilon,
                    k_force=12.0 * scale,
                    hyperviscosity=3.0e-13 / scale**8,
                    max_dt=0.00125 / scale,
                    duration=args.duration,
                    sample_interval=0.1,
                )
            )
            seed += 1

    started = time.perf_counter()
    runs: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run, config): config for config in configs}
        for future in concurrent.futures.as_completed(futures):
            config = futures[future]
            try:
                runs.append(future.result())
            except Exception as exc:
                errors.append({"config": asdict(config), "error": repr(exc)})
    runs.sort(key=lambda result: int(result["config"]["seed"]))

    reduced_laws = fit_reduced_laws(runs) if len(runs) >= 4 else None
    maximum_balance_error = max(
        (abs(result["relative_energy_balance_residual"]) for result in runs),
        default=float("inf"),
    )
    maximum_injection_error = max(
        (
            abs(result["realized_injection"] - result["target_injection"])
            / result["target_injection"]
            for result in runs
        ),
        default=float("inf"),
    )
    summary = {
        "scope_warning": (
            "Finite-box exploratory computation; reduced laws are conjectures, not proofs."
        ),
        "environment": {
            "python": platform.python_version(),
            "elapsed_seconds": time.perf_counter() - started,
        },
        "requested_runs": len(configs),
        "completed_runs": len(runs),
        "errors": errors,
        "maximum_relative_energy_balance_residual": maximum_balance_error,
        "maximum_relative_injection_error": maximum_injection_error,
        "reduced_laws": reduced_laws,
        "runs": runs,
    }
    (args.output / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if runs:
        plot_runs(runs, args.output / "diagnostics.png")
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}, indent=2))
    if len(runs) != len(configs) or maximum_balance_error >= 0.01:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
