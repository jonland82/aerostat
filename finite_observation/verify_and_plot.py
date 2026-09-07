"""Verify the note's numerical example and regenerate its publication figure.

Run with Python, NumPy, SciPy and Matplotlib. Generated files are placed beside
this script, regardless of the working directory. No source files are edited.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp

OUTPUT = Path(__file__).resolve().parent
A, OMEGA, DELTA = 1.0, 1.0, 1.0 / 400.0
T, N, SIGMA, J = 10.0, 100, 0.1, 1.0
T_STAR = math.pi / (2 * DELTA)


def hamilton_rhs(t, state):
    q, p, hidden_q, hidden_p = state
    return [p, -(OMEGA**2 + DELTA**2)*q - 2*OMEGA*DELTA*hidden_q,
            hidden_p, -(OMEGA**2 + DELTA**2)*hidden_q - 2*OMEGA*DELTA*q]


def main():
    times = np.linspace(0, T_STAR, 10001)
    solution = solve_ivp(hamilton_rhs, (0, T_STAR), [A, 0, 0, 0],
                         t_eval=times, rtol=1e-10, atol=1e-12)
    if not solution.success:
        raise RuntimeError(solution.message)
    q, p, hidden_q, hidden_p = solution.y
    exact_q = A*np.cos(OMEGA*times)*np.cos(DELTA*times)
    energy = (p**2 + hidden_p**2 + (OMEGA**2 + DELTA**2)
              *(q**2 + hidden_q**2))/2 + 2*OMEGA*DELTA*q*hidden_q
    flow_error = float(np.max(np.abs(q-exact_q)))
    energy_error = float(np.max(np.abs(energy-energy[0])))

    def forced_rhs(t, state):
        base_q, base_p, q, p, hidden_q, hidden_p = state
        force = (J/T)*math.sin(0.7*t)
        return [base_p, -OMEGA**2*base_q + force, p,
                -(OMEGA**2 + DELTA**2)*q - 2*OMEGA*DELTA*hidden_q + force,
                hidden_p, -(OMEGA**2 + DELTA**2)*hidden_q - 2*OMEGA*DELTA*q]

    forced_times = np.linspace(0, T, 10001)
    forced = solve_ivp(forced_rhs, (0, T), [A, 0, A, 0, 0, 0],
                       t_eval=forced_times, rtol=1e-11, atol=1e-13)
    if not forced.success:
        raise RuntimeError(forced.message)
    forced_difference = float(np.max(np.abs(forced.y[2]-forced.y[0])))
    b0 = A*DELTA**2*T**2/2
    bj = DELTA**2*(A*T**2/2 + J*T**3/6)
    tv0 = math.sqrt(N)*b0/(2*SIGMA)
    tvj = math.sqrt(N)*bj/(2*SIGMA)

    # Check the impulse response independently of the forced trajectory.
    def response(frequency):
        return np.sin(frequency*forced_times)/frequency
    response_error = float(np.max(np.abs(
        (response(OMEGA+DELTA)+response(OMEGA-DELTA))/2-response(OMEGA))))
    sign_times = np.linspace(0, 0.99*T_STAR, 100001)
    base = A*np.cos(OMEGA*sign_times)
    extended = base*np.cos(DELTA*sign_times)
    sign_mismatches = int(np.count_nonzero((base >= 0) != (extended >= 0)))
    checks = {
        "independent_ODE_matches_exact": flow_error < 3e-9,
        "energy_conservation": energy_error < 8e-9,
        "late_full_amplitude_difference": abs(float(q[-1])) < 1e-8,
        "forced_discrepancy_bound": forced_difference < bj,
        "impulse_response_bound": response_error <= DELTA**2*T**3/6,
        "sign_records_agree_before_envelope_zero": sign_mismatches == 0,
    }
    report = {
        "parameters": {"A": A, "omega": OMEGA, "delta": DELTA,
                       "T": T, "n": N, "sigma": SIGMA, "J": J},
        "T_star": T_STAR, "initial_energy": float(energy[0]),
        "ODE_max_error": flow_error, "energy_max_drift": energy_error,
        "passive_position_bound": b0, "passive_TV_bound": tv0,
        "equal_prior_success_upper_bound": (1+tv0)/2,
        "late_extended_position_numerical": float(q[-1]),
        "forced_position_difference": forced_difference,
        "forced_position_bound": bj, "forced_TV_bound": tvj,
        "impulse_response_difference": response_error, "checks": checks,
    }
    if not all(checks.values()):
        print(json.dumps(report, indent=2))
        raise SystemExit("Numerical verification failed.")

    plt.rcParams.update({"font.family": "serif", "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.30), constrained_layout=True)
    early = np.linspace(0, T, 1601)
    axes[0].plot(early, A*np.cos(OMEGA*early), color="0.6", lw=2.5,
                 label="Isolated")
    axes[0].plot(early, A*np.cos(OMEGA*early)*np.cos(DELTA*early),
                 color="black", lw=1, ls="--", label="Coupled")
    axes[0].set(xlabel=r"Time $t$", ylabel=r"Observed position $q/A$",
                title="The available record", xlim=(0, T), ylim=(-1.13, 1.13))
    axes[0].legend(loc="lower left", fontsize=8, frameon=True, ncol=2,
                   facecolor="white", edgecolor="none", framealpha=0.95)
    # At these times the isolated oscillator is exactly at its positive maximum.
    strobes = 2*math.pi*np.arange(201)/OMEGA
    axes[1].axhline(1, color="0.6", lw=2.2)
    axes[1].plot(strobes/T_STAR, np.cos(DELTA*strobes), color="black", lw=1.2)
    axes[1].axvspan(0, T/T_STAR, color="0.80", zorder=0)
    axes[1].axhline(0, color="0.85", lw=0.6, zorder=0)
    axes[1].scatter([1, 2], [0, -1], color="black", s=12, zorder=3)
    axes[1].set(xlabel=r"Time $t/T_*$ (one reading per carrier period)",
                title="The later context", xlim=(0, 2.04), ylim=(-1.13, 1.13))
    axes[1].set_xticks([0, 1, 2])
    for ax in axes:
        ax.tick_params(labelsize=8)
    fig.savefig(OUTPUT / "finite_observation_figure.pdf", bbox_inches="tight")
    fig.savefig(OUTPUT / "finite_observation_figure.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    (OUTPUT / "verification_results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
