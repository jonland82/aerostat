"""Reduced-law comparisons for energy-consistent inverse-cascade runs."""

from __future__ import annotations

import numpy as np


def fit_reduced_laws(runs: list[dict[str, object]]) -> dict[str, object]:
    """Compare physically motivated reduced laws with run-level holdouts."""
    rows: list[dict[str, float | int]] = []
    for group, run in enumerate(runs):
        records = run["records"]
        t = np.asarray([row["time"] for row in records], dtype=float)
        length = np.asarray([row["smooth_length"] for row in records], dtype=float)
        if len(t) < 15:
            continue
        window = max(5, int(round(1.0 / np.median(np.diff(t)))))
        if window % 2 == 0:
            window += 1
        kernel = np.ones(window) / window
        smooth_length = np.convolve(
            np.pad(length, window // 2, mode="edge"), kernel, mode="valid"
        )
        rate = np.gradient(smooth_length, t)
        flux = np.asarray([row["edge_flux"] for row in records], dtype=float)
        smooth_flux = np.convolve(
            np.pad(flux, window // 2, mode="edge"), kernel, mode="valid"
        )
        epsilon = float(run["config"]["epsilon"])
        for index in range(len(t)):
            if not (
                0.15 * t[-1] <= t[index] <= 0.85 * t[-1]
                and rate[index] > 1.0e-7
                and smooth_flux[index] > 1.0e-9
                and length[index] < 0.30
            ):
                continue
            rows.append(
                {
                    "group": group,
                    "epsilon": epsilon,
                    "length": length[index],
                    "rate": rate[index],
                    "flux": smooth_flux[index],
                    "infrared_fraction": max(
                        float(records[index]["infrared_fraction"]), 1.0e-9
                    ),
                    "spectral_width": max(
                        float(records[index]["spectral_log_width"]), 1.0e-9
                    ),
                    "enstrophy": max(float(records[index]["enstrophy"]), 1.0e-9),
                }
            )

    y = np.log(np.asarray([row["rate"] for row in rows]))
    groups = np.asarray([row["group"] for row in rows])
    epsilon_groups = np.asarray([row["epsilon"] for row in rows])
    log_epsilon = np.log(np.asarray([row["epsilon"] for row in rows]))
    log_length = np.log(np.asarray([row["length"] for row in rows]))
    log_flux = np.log(np.asarray([row["flux"] for row in rows]))
    log_fraction = np.log(np.asarray([row["infrared_fraction"] for row in rows]))
    log_width = np.log(np.asarray([row["spectral_width"] for row in rows]))
    log_enstrophy = np.log(np.asarray([row["enstrophy"] for row in rows]))

    specifications = {
        "canonical": {
            "names": ["intercept"],
            "x": np.ones((len(y), 1)),
            "offset": (log_epsilon + log_length) / 3.0,
        },
        "free_epsilon_length": {
            "names": ["intercept", "log_epsilon", "log_length"],
            "x": np.column_stack([np.ones(len(y)), log_epsilon, log_length]),
            "offset": np.zeros(len(y)),
        },
        "flux_length": {
            "names": ["intercept", "log_edge_flux", "log_length"],
            "x": np.column_stack([np.ones(len(y)), log_flux, log_length]),
            "offset": np.zeros(len(y)),
        },
        "rich": {
            "names": [
                "intercept",
                "log_epsilon",
                "log_length",
                "log_edge_flux",
                "log_infrared_fraction",
                "log_spectral_width",
                "log_enstrophy",
            ],
            "x": np.column_stack(
                [
                    np.ones(len(y)),
                    log_epsilon,
                    log_length,
                    log_flux,
                    log_fraction,
                    log_width,
                    log_enstrophy,
                ]
            ),
            "offset": np.zeros(len(y)),
        },
    }

    results: dict[str, object] = {"samples": len(y), "models": {}}
    for name, specification in specifications.items():
        x = specification["x"]
        offset = specification["offset"]
        beta, *_ = np.linalg.lstsq(x, y - offset, rcond=None)
        prediction = offset + x @ beta
        r2 = 1.0 - np.sum((y - prediction) ** 2) / np.sum((y - y.mean()) ** 2)

        run_errors: list[float] = []
        for held_out in np.unique(groups):
            train = groups != held_out
            test = ~train
            fold_beta, *_ = np.linalg.lstsq(
                x[train], y[train] - offset[train], rcond=None
            )
            run_errors.extend(
                (y[test] - offset[test] - x[test] @ fold_beta).tolist()
            )

        epsilon_errors: list[float] = []
        for held_out in np.unique(epsilon_groups):
            train = epsilon_groups != held_out
            test = ~train
            fold_beta, *_ = np.linalg.lstsq(
                x[train], y[train] - offset[train], rcond=None
            )
            epsilon_errors.extend(
                (y[test] - offset[test] - x[test] @ fold_beta).tolist()
            )

        results["models"][name] = {
            "coefficients": {
                key: float(value)
                for key, value in zip(specification["names"], beta)
            },
            "multiplicative_C": float(np.exp(beta[0])),
            "in_sample_r2_log_rate": float(r2),
            "leave_one_run_out_rmse_log_rate": float(
                np.sqrt(np.mean(np.square(run_errors)))
            ),
            "holdout_epsilon_rmse_log_rate": float(
                np.sqrt(np.mean(np.square(epsilon_errors)))
            ),
        }
    return results
