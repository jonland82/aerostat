# Global State-Series Experiment

This experiment retrieves a bounded sequence of historical global OpenSky state-vector snapshots. It is separate from the dashboard runtime and does not change the dashboard's latest-snapshot storage model.

The default run requests 60 snapshots at one-minute intervals covering the immediately preceding hour. A global `/states/all` request costs four state credits, so the default run spends 240 credits. The script checks and updates the dashboard's shared conservative quota ledger at `data/quota.json`.

## Run

From the repository root:

```powershell
python -m pip install -r experiments/global-state-series/requirements.txt
python experiments/global-state-series/pull.py
```

OpenSky only exposes state vectors from the previous hour through REST. Run the command while connected to the internet; it fetches the oldest timestamp first so the history window does not expire during the pull.

To make a smaller bounded pull:

```powershell
python experiments/global-state-series/pull.py --samples 10 --interval 60
```

## Outputs

Generated files are local and ignored by Git under `data/`:

- `raw/states-<timestamp>.json.gz`: exact OpenSky responses for reproducibility.
- `global_states.parquet`: all state vectors with requested and returned snapshot timestamps.
- `top_500_states.parquet`: the 500 ICAO24 identifiers appearing in the most snapshots.
- `manifest.json`: time range, row counts, aircraft coverage, credit usage, and filenames.

Times are Unix UTC seconds. Altitudes are meters, velocity is meters per second, vertical rate is meters per second, and coordinates are WGS-84 decimal degrees. State vectors reflect OpenSky receiver coverage and are observations rather than a complete registry of aircraft operating worldwide.

See the official [OpenSky REST API documentation](https://openskynetwork.github.io/opensky-api/rest.html) for field definitions, history limits, and current credit rules.

## Current Local Dataset

The pull completed on 2026-06-20 and covers 02:11:45Z through 03:10:45Z:

- 60 raw snapshots at one-minute intervals.
- 414,269 total state-vector rows.
- 12,524 distinct ICAO24 identifiers.
- 2,204 aircraft present in all 60 snapshots.
- 30,000 rows in `top_500_states.parquet`; every selected aircraft has all 60 observations.
- 240 OpenSky state credits spent; OpenSky reported 3,744 remaining after the pull.

The generated dataset remains local under this experiment's ignored `data/` directory. `manifest.json` is the machine-readable record for the run.

## Visualizations

The experiment includes three static browser visualizations:

| Page | Purpose |
|---|---|
| [Three-flight globe](visualizations/three-flight-globe/) | Animates three complete representative tracks |
| [Altitude histogram](visualizations/altitude-histogram/) | Animates the global altitude distribution across all 60 snapshots |
| [Geodesic deviation](visualizations/geodesic-deviation/) | Compares complete tracks with their endpoint great-circle arcs |

Each page uses a compact generated JavaScript dataset and does not load the
ignored Parquet file in the browser. Serve the repository root with
`python -m http.server 8080`; opening the HTML files directly with a
`file://` URL is not the supported workflow.

The globe and altitude pages use local assets. The mathematical section on the
geodesic-deviation page loads MathJax 3 from jsDelivr, so its typeset equations
require an internet connection.

## Three-Flight Globe

`visualizations/three-flight-globe/index.html` animates three complete captured segments across an interactive globe: AAL784 over the North Atlantic, DAL158 over the North Pacific, and ARG1815 over South America. The visualization embeds only those 180 observations in `flight-data.js`; it does not read the ignored Parquet files at runtime.

Serve the repository root and open the visualization:

```powershell
python -m http.server 8080
```

Then visit <http://127.0.0.1:8080/experiments/global-state-series/visualizations/three-flight-globe/>. Rebuild the embedded observations after replacing the source dataset with:

```powershell
python experiments/global-state-series/visualizations/three-flight-globe/build_data.py
```

## Altitude Histogram

`visualizations/altitude-histogram/index.html` animates the global distribution
of reported barometric altitudes across all 60 snapshots. It uses fixed
1,000-foot bins from -1,000 through 60,000 feet so changes in the distribution
are comparable from minute to minute. Aircraft without a reported altitude are
displayed as a separate count and excluded from the bars.

Serve the repository root as above, then visit
<http://127.0.0.1:8080/experiments/global-state-series/visualizations/altitude-histogram/>.
Rebuild the embedded histogram frames after replacing the source dataset with:

```powershell
python experiments/global-state-series/visualizations/altitude-histogram/build_data.py
```

## Geodesic Path Deviation

`visualizations/geodesic-deviation/index.html` compares each complete observed
track with the minor great-circle arc joining its first and last positions. The
interactive histogram shows RMS and maximum spherical deviation, excess path
length, and path efficiency. The quality-filtered cohort requires a position in
all 60 snapshots, at least 25 km of endpoint displacement, and no implausible
one-minute jump over 30 km.

The complete-position cohort contains 2,183 aircraft. The displacement filter
removes 95 and the jump filter removes 308, leaving 1,780 aircraft in the
displayed distributions. For RMS geodesic deviation, the current cohort has:

- 16.7 km median.
- 22.7 km mean.
- 50.0 km 90th percentile.
- 102.3 km 99th percentile.

Median excess path length is 9.7 km and median path efficiency is 98.7%.

Serve the repository root as above, then visit
<http://127.0.0.1:8080/experiments/global-state-series/visualizations/geodesic-deviation/>.
Rebuild its embedded metrics after replacing the source dataset with:

```powershell
python experiments/global-state-series/visualizations/geodesic-deviation/build_data.py
```

### Mathematical Model

For observed spherical path \(x_i(t)\), let \(g_i\) be the minor great-circle
arc between its endpoints. The pointwise cross-track displacement is

\[
\eta_i(t)=d_{S_R^2}\left(x_i(t),g_i([0,1])\right),
\]

and the displayed RMS statistic is

\[
D_i=\left[\frac{1}{60}\sum_{j=1}^{60}\eta_i(t_j)^2\right]^{1/2}.
\]

The simplest empirical hypothesis is
\(\log D_i\sim\mathcal N(\mu,\sigma^2)\). The page also presents the
geometry-driven random-scale bridge model

\[
\eta_i(t)=A_iZ_i(t),\qquad D_i=A_iQ_i,
\]

where \(Z_i\) is an endpoint-pinned bridge, \(A_i\) is a positive route-scale
variable, and \(Q_i\) is the bridge's RMS shape functional. A Brownian-bridge
baseline makes \(Q_i^2\) a weighted chi-square variable. With lognormal
\(A_i\), the resulting population law is

\[
f_D(d)=\int_0^\infty f_A\left(\frac{d}{q}\right)f_Q(q)\frac{dq}{q}.
\]

A single lognormal is the concentrated-shape approximation to this model.
Flight-phase and route-class heterogeneity may instead produce a mixture of
such laws.

### Academic Note

The self-contained three-page note
[When Does a Random-Scale Flight Path Look Lognormal?](notes/random-scale-bridge/random-scale-bridge.pdf)
develops the scale-shape model into a lognormal-smoothing theorem, exact
cumulant identities, a Brownian-bridge threshold, and an empirical diagnostic
for the near-geodesic boundary population. Its LaTeX source and reproducible
figure builder are in `notes/random-scale-bridge/`.

Rebuild the vector figure and PDF from that directory with:

```powershell
python build_figure.py
latexmk -pdf -interaction=nonstopmode -halt-on-error random-scale-bridge.tex
```

### Energy and Fuel Counterfactual

The geodesic page also converts the cohort's 45,451 km of aggregate excess
ground track into an adjustable energy, jet-fuel, and spot-value estimate. For
representative aircraft mass \(M\), lift-to-drag ratio \(L/\mathcal D\), and
overall fuel-to-propulsive efficiency \(\eta\),

\[
\Delta E_{\mathrm{mech}}
\approx \frac{Mg}{L/\mathcal D}\Delta s_\Sigma,
\qquad
\Delta m_f=\frac{\Delta E_{\mathrm{mech}}}{\eta H_f}.
\]

Using \(M=70\) metric tons, \(L/\mathcal D=17\), \(\eta=0.35\), jet-kerosene
net calorific value \(H_f=44.1\) MJ/kg, density 0.800 kg/L, and the EIA Gulf
Coast spot price of $3.185/gallon for the week ending 2026-06-12 gives:

- 1.84 TJ of extra mechanical work.
- 118.9 metric tons, or about 39,300 gallons, of jet fuel.
- About $125,000 at spot value.

A broad 40-100 metric ton sensitivity envelope gives roughly $56,000-$236,000.
This is a counterfactual order-of-magnitude calculation, not an estimate of
avoidable operational loss. It ignores winds, vertical flight, aircraft type,
payload, airspace constraints, weather, and necessary routing, and it covers
only the 1,780-aircraft quality cohort.
