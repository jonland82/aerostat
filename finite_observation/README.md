# Finite Observation and Broader Physical Processes

A standalone note in the visual style of `../relational_shape.pdf`.

The narrative: a process can look complete within a finite record while
belonging to broader dynamics that become important later.

Contents include local geometric bounds, a proof of the adaptive Gaussian
record bound, a stable coupled-oscillator construction, bounded active probing,
exact symbolic concealment, transfer of finite-horizon predictive descriptions,
and a separate conditional theorem about unbounded process scales.

- `finite_observation.tex`: complete manuscript and proofs.
- `finite_observation.pdf`: compiled note.
- `verify_and_plot.py`: independent numerical checks and figure generation.
- `verification_results.json`: generated numerical results.
- `finite_observation_figure.pdf` / `.png`: generated figure.

Build from this directory:

```powershell
python verify_and_plot.py
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=build finite_observation.tex
Copy-Item -LiteralPath build/finite_observation.pdf -Destination finite_observation.pdf
```

The build writes the PDF to `build/finite_observation.pdf`; the reviewed
publication copy is kept alongside the source. Python requires NumPy, SciPy,
and Matplotlib. The TeX source uses the same Latin Modern typography, margins,
and pale rounded callouts as the foundation paper.

The note makes no cosmological claim and does not establish that real physics
has an infinite hierarchy. Its probability-one statement explicitly assumes a
process-scale population law. The oscillator construction concerns one coupled
extension, not an infinite finite-energy system.
