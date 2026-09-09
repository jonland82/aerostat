#!/usr/bin/env python3
"""Energy-consistent validation solver for forced 2-D vorticity dynamics."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Config:
    n: int = 64
    seed: int = 1
    epsilon: float = 0.002
    k_force: float = 12.0
    shell_width: float = 2.0
    initial_energy: float = 0.02
    hyperviscosity: float = 3.0e-13
    drag: float = 0.0
    max_dt: float = 0.01
    cfl: float = 0.3
    duration: float = 5.0
    sample_interval: float = 0.1
    record_spectra: bool = False


def grid(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    one_d = np.fft.fftfreq(n, d=1.0 / n)
    kx, ky = np.meshgrid(one_d, one_d, indexing="ij")
    k2 = kx * kx + ky * ky
    radius = np.sqrt(k2)
    # The square two-thirds truncation makes the pseudospectral products exact
    # on the retained modes for quadratic nonlinearities.
    dealias = (np.abs(kx) <= n / 3) & (np.abs(ky) <= n / 3)
    dealias[0, 0] = False
    return kx, ky, k2, radius, dealias


def modal_energy(omega: np.ndarray, k2: np.ndarray) -> np.ndarray:
    inverse = np.zeros_like(k2)
    np.divide(1.0, k2, out=inverse, where=k2 > 0)
    return 0.5 * np.abs(omega) ** 2 * inverse / omega.size**2


def energy(omega: np.ndarray, k2: np.ndarray) -> float:
    return float(modal_energy(omega, k2).sum())


def enstrophy(omega: np.ndarray) -> float:
    return float(0.5 * (np.abs(omega) ** 2).sum() / omega.size**2)


def initialise(config: Config, radius: np.ndarray, k2: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(config.seed)
    omega = np.fft.fft2(rng.standard_normal((config.n, config.n)))
    omega *= np.abs(radius - config.k_force) <= config.shell_width / 2
    omega *= np.sqrt(config.initial_energy / energy(omega, k2))
    return omega


def nonlinear(
    omega: np.ndarray,
    kx: np.ndarray,
    ky: np.ndarray,
    k2: np.ndarray,
    dealias: np.ndarray,
) -> tuple[np.ndarray, float]:
    inverse = np.zeros_like(k2)
    np.divide(1.0, k2, out=inverse, where=k2 > 0)
    u = np.fft.ifft2(1j * ky * inverse * omega).real
    v = np.fft.ifft2(-1j * kx * inverse * omega).real
    omega_x = np.fft.ifft2(1j * kx * omega).real
    omega_y = np.fft.ifft2(1j * ky * omega).real

    # Average advective and conservative forms. They are analytically equal
    # for incompressible flow, while the average is discretely skew-symmetric.
    advective = u * omega_x + v * omega_y
    conservative = (
        np.fft.ifft2(1j * kx * np.fft.fft2(u * np.fft.ifft2(omega).real)).real
        + np.fft.ifft2(1j * ky * np.fft.fft2(v * np.fft.ifft2(omega).real)).real
    )
    result = -np.fft.fft2(0.5 * (advective + conservative))
    result *= dealias
    return result, float(np.sqrt(u * u + v * v).max())


def integrating_factor_rk4(
    omega: np.ndarray,
    dt: float,
    damping: np.ndarray,
    kx: np.ndarray,
    ky: np.ndarray,
    k2: np.ndarray,
    dealias: np.ndarray,
) -> np.ndarray:
    half = np.exp(-0.5 * damping * dt)
    full = half * half
    n1, _ = nonlinear(omega, kx, ky, k2, dealias)
    a = half * (omega + 0.5 * dt * n1)
    n2, _ = nonlinear(a, kx, ky, k2, dealias)
    b = half * omega + 0.5 * dt * n2
    n3, _ = nonlinear(b, kx, ky, k2, dealias)
    c = full * omega + dt * half * n3
    n4, _ = nonlinear(c, kx, ky, k2, dealias)
    advanced = full * omega + (dt / 6.0) * (
        full * n1 + 2.0 * half * n2 + 2.0 * half * n3 + n4
    )
    advanced *= dealias
    return advanced


def exact_random_energy_kick(
    omega: np.ndarray,
    injected_energy: float,
    rng: np.random.Generator,
    shell: np.ndarray,
    k2: np.ndarray,
    dealias: np.ndarray,
) -> np.ndarray:
    """Add a random shell increment orthogonal to omega with exact energy."""
    if injected_energy <= 0:
        return omega
    omega_shell = omega * shell
    norm_omega = 2.0 * energy(omega_shell, k2)
    for _ in range(4):
        direction = np.fft.fft2(rng.standard_normal(omega.shape)) * shell * dealias
        # The energy inner product contains 1/k^2.
        weighted_inner = float(
            np.sum(
                np.real(np.conj(omega_shell) * direction) / np.where(k2 > 0, k2, 1.0)
            )
            / omega.size**2
        )
        if norm_omega > 0:
            direction -= (weighted_inner / norm_omega) * omega_shell
        direction_energy = energy(direction, k2)
        if direction_energy > 1.0e-20:
            direction *= np.sqrt(injected_energy / direction_energy)
            kicked = (omega + direction) * dealias
            return kicked
    raise FloatingPointError("could not construct a nondegenerate forcing direction")


def diagnostics(
    omega: np.ndarray,
    radius: np.ndarray,
    k2: np.ndarray,
    nonlinear_tendency: np.ndarray | None = None,
    k_force: float | None = None,
) -> dict[str, float]:
    modes = modal_energy(omega, k2)
    total = float(modes.sum())
    active = radius > 0
    length = float((modes[active] / radius[active]).sum() / total)
    log_k = np.log(radius[active])
    mean_log_k = float((modes[active] * log_k).sum() / total)
    result = {
        "energy": total,
        "enstrophy": enstrophy(omega),
        "smooth_length": length,
        "spectral_log_width": float(
            np.sqrt((modes[active] * (log_k - mean_log_k) ** 2).sum() / total)
        ),
    }
    if k_force is not None:
        infrared = float(modes[radius < k_force].sum())
        result["infrared_energy"] = infrared
        result["infrared_fraction"] = infrared / total
    if nonlinear_tendency is not None and k_force is not None:
        transfer = np.zeros_like(k2)
        np.divide(
            np.real(np.conj(omega) * nonlinear_tendency),
            k2 * omega.size**2,
            out=transfer,
            where=k2 > 0,
        )
        order = np.argsort(radius.ravel())
        cumulative = np.cumsum(modes.ravel()[order])
        index = min(int(np.searchsorted(cumulative, 0.25 * total)), order.size - 1)
        k_edge = float(radius.ravel()[order[index]])
        result["quantile_length"] = 1.0 / k_edge
        result["edge_flux"] = float(transfer[radius <= k_edge].sum())
        result["inverse_flux_half_forcing"] = float(
            transfer[radius <= k_force / 2].sum()
        )
    return result


def spectral_snapshot(
    omega: np.ndarray,
    radius: np.ndarray,
    k2: np.ndarray,
    nonlinear_tendency: np.ndarray,
) -> dict[str, list[float]]:
    """Return shell-integrated energy and nonlinear transfer spectra."""
    shell = np.floor(radius + 0.5).astype(int)
    size = int(shell.max()) + 1
    modes = modal_energy(omega, k2)
    transfer = np.zeros_like(k2)
    np.divide(
        np.real(np.conj(omega) * nonlinear_tendency),
        k2 * omega.size**2,
        out=transfer,
        where=k2 > 0,
    )
    energy_shell = np.bincount(shell.ravel(), weights=modes.ravel(), minlength=size)
    transfer_shell = np.bincount(
        shell.ravel(), weights=transfer.ravel(), minlength=size
    )
    return {
        "energy_spectrum": energy_shell.tolist(),
        "cumulative_nonlinear_transfer": np.cumsum(transfer_shell).tolist(),
    }


def run(config: Config) -> dict[str, object]:
    kx, ky, k2, radius, dealias = grid(config.n)
    shell = np.abs(radius - config.k_force) <= config.shell_width / 2
    damping = config.hyperviscosity * k2**4 + config.drag
    omega = initialise(config, radius, k2)
    rng = np.random.default_rng(config.seed + 10_000)
    initial = diagnostics(omega, radius, k2, k_force=config.k_force)
    records: list[dict[str, float]] = []
    time_value = 0.0
    next_sample = 0.0
    injected = 0.0
    integrated_dissipation = 0.0
    minimum_dt = config.max_dt
    steps = 0

    while time_value < config.duration - 1.0e-14:
        _, max_speed = nonlinear(omega, kx, ky, k2, dealias)
        cfl_dt = config.cfl * (2.0 * np.pi / config.n) / max(max_speed, 1.0e-12)
        dt = min(config.max_dt, cfl_dt, config.duration - time_value)
        minimum_dt = min(minimum_dt, dt)
        modes_before = modal_energy(omega, k2)
        dissipation_before = float(2.0 * (damping * modes_before).sum())
        deterministic = integrating_factor_rk4(omega, dt, damping, kx, ky, k2, dealias)
        modes_after = modal_energy(deterministic, k2)
        dissipation_after = float(2.0 * (damping * modes_after).sum())
        integrated_dissipation += 0.5 * dt * (dissipation_before + dissipation_after)
        before_kick = energy(deterministic, k2)
        omega = exact_random_energy_kick(
            deterministic, config.epsilon * dt, rng, shell, k2, dealias
        )
        realized = energy(omega, k2) - before_kick
        injected += realized
        time_value += dt
        steps += 1
        if not np.all(np.isfinite(omega)):
            raise FloatingPointError(f"non-finite state at t={time_value}")
        if time_value + 1.0e-12 >= next_sample:
            sample_nonlinear, _ = nonlinear(omega, kx, ky, k2, dealias)
            row = diagnostics(
                omega, radius, k2, sample_nonlinear, config.k_force
            )
            if config.record_spectra:
                row.update(spectral_snapshot(omega, radius, k2, sample_nonlinear))
            row["time"] = time_value
            records.append(row)
            next_sample += config.sample_interval

    final_nonlinear, _ = nonlinear(omega, kx, ky, k2, dealias)
    final = diagnostics(omega, radius, k2, final_nonlinear, config.k_force)
    if config.record_spectra:
        final.update(spectral_snapshot(omega, radius, k2, final_nonlinear))
    energy_residual = final["energy"] - initial["energy"] - injected + integrated_dissipation
    return {
        "config": asdict(config),
        "initial": initial,
        "final": final,
        "steps": steps,
        "minimum_dt": minimum_dt,
        "realized_injection": injected,
        "target_injection": config.epsilon * config.duration,
        "integrated_dissipation": integrated_dissipation,
        "energy_balance_residual": energy_residual,
        "relative_energy_balance_residual": energy_residual / max(injected, initial["energy"]),
        "relative_energy_drift": (final["energy"] - initial["energy"]) / initial["energy"],
        "relative_enstrophy_drift": (final["enstrophy"] - initial["enstrophy"]) / initial["enstrophy"],
        "records": records,
    }


def validation_suite() -> dict[str, object]:
    invariant_runs = [
        run(Config(epsilon=0.0, hyperviscosity=0.0, duration=3.0, max_dt=dt))
        for dt in (0.01, 0.005)
    ]
    seeds = range(1, 7)
    coarse_configs = [Config(seed=seed, duration=3.0, max_dt=0.01) for seed in seeds]
    fine_configs = [Config(seed=seed, duration=3.0, max_dt=0.005) for seed in seeds]
    resolution_configs = [
        Config(n=96, seed=seed, duration=3.0, max_dt=0.005) for seed in seeds
    ]
    all_configs = coarse_configs + fine_configs + resolution_configs
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        all_runs = list(executor.map(run, all_configs))
    forced_runs = {
        "coarse_dt": all_runs[:6],
        "fine_dt": all_runs[6:12],
        "higher_resolution": all_runs[12:],
    }
    coarse_lengths = np.asarray([r["final"]["smooth_length"] for r in forced_runs["coarse_dt"]])
    fine_lengths = np.asarray([r["final"]["smooth_length"] for r in forced_runs["fine_dt"]])
    resolution_lengths = np.asarray([
        r["final"]["smooth_length"] for r in forced_runs["higher_resolution"]
    ])
    convergence = {
        "ensemble_size": len(coarse_lengths),
        "coarse_length_mean_std": [float(coarse_lengths.mean()), float(coarse_lengths.std(ddof=1))],
        "fine_length_mean_std": [float(fine_lengths.mean()), float(fine_lengths.std(ddof=1))],
        "higher_resolution_length_mean_std": [
            float(resolution_lengths.mean()), float(resolution_lengths.std(ddof=1))
        ],
        "timestep_mean_length_relative_difference": float(
            abs(coarse_lengths.mean() - fine_lengths.mean()) / fine_lengths.mean()
        ),
        "resolution_mean_length_relative_difference": float(
            abs(resolution_lengths.mean() - fine_lengths.mean()) / fine_lengths.mean()
        ),
    }
    all_forced = sum(forced_runs.values(), [])
    accepted = (
        max(abs(r["relative_energy_drift"]) for r in invariant_runs) < 1.0e-5
        and max(abs(r["relative_enstrophy_drift"]) for r in invariant_runs) < 1.0e-5
        and max(abs(r["relative_energy_balance_residual"]) for r in all_forced) < 0.01
        and convergence["timestep_mean_length_relative_difference"] < 0.05
        and convergence["resolution_mean_length_relative_difference"] < 0.10
    )
    return {
        "acceptance_thresholds": {
            "inviscid_relative_drift": 1.0e-5,
            "forced_relative_energy_balance_residual": 0.01,
            "timestep_ensemble_mean_length_difference": 0.05,
            "resolution_ensemble_mean_length_difference": 0.10,
        },
        "accepted": accepted,
        "invariant_runs": invariant_runs,
        "forced_runs": forced_runs,
        "convergence": convergence,
    }


def high_forcing_suite(
    epsilons: tuple[float, ...] = (0.004, 0.008),
    coarse_dt: float = 0.005,
    fine_dt: float = 0.0025,
) -> dict[str, object]:
    seeds = (1, 2)
    coarse_configs = [
        Config(n=128, seed=seed, epsilon=epsilon, duration=15.0, max_dt=coarse_dt)
        for epsilon in epsilons for seed in seeds
    ]
    fine_configs = [
        Config(n=128, seed=seed, epsilon=epsilon, duration=15.0, max_dt=fine_dt)
        for epsilon in epsilons for seed in seeds
    ]
    configs = coarse_configs + fine_configs
    errors: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run, config): config for config in configs}
        for future in concurrent.futures.as_completed(futures):
            config = futures[future]
            try:
                completed.append(future.result())
            except Exception as exc:
                errors.append({"config": asdict(config), "error": repr(exc)})
    completed.sort(key=lambda item: (item["config"]["max_dt"], item["config"]["epsilon"], item["config"]["seed"]))

    comparisons: dict[str, object] = {}
    for epsilon in epsilons:
        coarse = [r for r in completed if r["config"]["epsilon"] == epsilon and r["config"]["max_dt"] == coarse_dt]
        fine = [r for r in completed if r["config"]["epsilon"] == epsilon and r["config"]["max_dt"] == fine_dt]
        if len(coarse) != len(seeds) or len(fine) != len(seeds):
            continue
        coarse_length = np.mean([r["final"]["smooth_length"] for r in coarse])
        fine_length = np.mean([r["final"]["smooth_length"] for r in fine])
        late_flux = []
        for result in fine:
            records = result["records"]
            late_flux.extend(
                row["inverse_flux_half_forcing"] for row in records[len(records) // 2:]
            )
        comparisons[str(epsilon)] = {
            "coarse_mean_length": float(coarse_length),
            "fine_mean_length": float(fine_length),
            "relative_timestep_difference": float(abs(coarse_length - fine_length) / fine_length),
            "fine_mean_late_inverse_flux": float(np.mean(late_flux)),
        }

    max_balance = max(
        (abs(r["relative_energy_balance_residual"]) for r in completed),
        default=float("inf"),
    )
    max_injection_error = max(
        (
            abs(r["realized_injection"] - r["target_injection"])
            / r["target_injection"]
            for r in completed
        ),
        default=float("inf"),
    )
    accepted = (
        len(completed) == len(configs)
        and not errors
        and max_balance < 0.01
        and max_injection_error < 1.0e-10
        and len(comparisons) == len(epsilons)
        and all(item["relative_timestep_difference"] < 0.05 for item in comparisons.values())
        and all(item["fine_mean_late_inverse_flux"] > 0 for item in comparisons.values())
    )
    return {
        "accepted": accepted,
        "coarse_dt": coarse_dt,
        "fine_dt": fine_dt,
        "requested_runs": len(configs),
        "completed_runs": len(completed),
        "errors": errors,
        "maximum_relative_energy_balance_residual": max_balance,
        "maximum_relative_injection_error": max_injection_error,
        "comparisons": comparisons,
        "runs": completed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("energy_consistent_validation.json"),
    )
    parser.add_argument(
        "--suite",
        choices=("standard", "high-forcing", "high-refinement"),
        default="standard",
    )
    args = parser.parse_args()
    if args.suite == "standard":
        result = validation_suite()
    elif args.suite == "high-forcing":
        result = high_forcing_suite()
    else:
        result = high_forcing_suite((0.008,), 0.0025, 0.00125)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.suite == "standard":
        report = {
            "accepted": result["accepted"],
            "convergence": result["convergence"],
            "invariant_drift": [
                {
                    "dt": run_result["config"]["max_dt"],
                    "energy": run_result["relative_energy_drift"],
                    "enstrophy": run_result["relative_enstrophy_drift"],
                }
                for run_result in result["invariant_runs"]
            ],
            "maximum_forced_balance_residual": max(
                abs(run_result["relative_energy_balance_residual"])
                for run_result in sum(result["forced_runs"].values(), [])
            ),
        }
    else:
        report = {key: value for key, value in result.items() if key != "runs"}
    print(json.dumps(report, indent=2))
    if not result["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
