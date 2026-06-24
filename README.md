# Aerostat OpenSky Globe

A lightweight, manually refreshed aircraft globe backed by the OpenSky Network API.

## Public Links

- Project overview for GitHub Pages: <https://jonland82.github.io/aerostat/>
- Live CloudFront dashboard: <https://d2188f8gar9chl.cloudfront.net/>
- Live CloudFront experiment viewer: <https://d2188f8gar9chl.cloudfront.net/experiments/index.html>

The public dashboard can display the deployed snapshot. Manual refresh remains owner-gated by the private refresh key and local collector described in [AWS_SETUP.md](AWS_SETUP.md).

## What This Project Is About

Aerostat is a small OpenSky-based airspace project with two connected layers:

- A live aircraft globe that can be deployed behind CloudFront and refreshed manually without browser polling.
- A captured one-hour global state-series experiment that turns OpenSky state vectors into static visualizations and a short mathematical note about flight-path geometry.

The dashboard is intentionally credit-safe and operationally conservative. Opening
the site does not call OpenSky. The analytical side is separate: it uses bounded
historical pulls to ask geometric questions about how aircraft tracks deviate
from the direct spherical route between their observed endpoints.

## Website and Experiments

The GitHub Pages overview is the public project landing page. The CloudFront
site is the operational dashboard and experiment viewer:

- [Live aircraft dashboard](https://d2188f8gar9chl.cloudfront.net/)
- [Tabbed experiment viewer](https://d2188f8gar9chl.cloudfront.net/experiments/index.html)
- [Random-scale bridge note](experiments/global-state-series/notes/random-scale-bridge/random-scale-bridge.pdf)
- [Global state-series experiment README](experiments/global-state-series/README.md)

The experiment viewer includes three browser artifacts:

- Representative flight traversals on an animated globe.
- An animated altitude histogram across 60 one-minute snapshots.
- A path-deviation page comparing complete tracks with endpoint great-circle arcs.

## Current Dataset

The current local experiment pull covers 2026-06-20 02:11:45Z through
03:10:45Z:

- 60 one-minute global snapshots.
- 414,269 OpenSky state-vector rows.
- 12,524 distinct ICAO24 identifiers.
- 2,204 aircraft present in all 60 snapshots.
- 1,780 quality-filtered tracks after requiring complete positions, at least
  25 km of endpoint displacement, and no implausible one-minute jump above
  30 km.

Generated raw responses and Parquet files remain local and gitignored. The
tracked visualizations use compact JavaScript datasets rebuilt from that local
experiment output.

## Path-Geometry Question

The basic question is not whether aircraft follow great circles. They usually
do not. The endpoint great-circle is used as a simple reference curve: given the
first and last observed positions of an aircraft, how far does the recorded
track move sideways from that direct spherical arc?

For each aircraft, the primary statistic is RMS geodesic deviation. In the
current quality-filtered cohort:

- Median RMS deviation is 16.7 km.
- Mean RMS deviation is 22.7 km.
- The 90th percentile is 50.0 km.
- The 99th percentile is 102.3 km.
- Median excess path length is 9.7 km.
- Median path efficiency is 98.7%.

The histogram has a broad center that looks plausibly lognormal, but the lower
tail is too sharp for a single smooth population: 53 tracks have RMS deviation
at or below 0.1 km.

## Basic Mathematical Formalism

Let \(x_i(t)\) be aircraft \(i\)'s observed position on the spherical Earth,
normalized to \(0 \le t \le 1\). Let \(g_i\) be the minor great-circle arc
joining its first and last observed positions. The pointwise cross-track
displacement is

\[
\eta_i(t)=d_{S_R^2}\left(x_i(t),g_i([0,1])\right),
\]

and the sampled RMS deviation is

\[
D_i=\left[\frac{1}{60}\sum_{j=1}^{60}\eta_i(t_j)^2\right]^{1/2}.
\]

The random-scale bridge model factors each deviation into scale and shape:

\[
\eta_i(t)=A_iZ_i(t), \qquad D_i=A_iQ_i.
\]

Here \(A_i\) is a positive route-scale variable, \(Z_i(t)\) is an
endpoint-pinned standardized bridge, and \(Q_i\) is the bridge's RMS shape
functional. If variation in \(A_i\) dominates variation in \(Q_i\), then
\(\log D_i=\log A_i+\log Q_i\) is driven toward a Gaussian-looking law. This
explains why the center can look lognormal.

The same calculation also makes the empirical failure meaningful. Under a
single independent lognormal-scale Brownian-bridge population, matching the
observed log-variance predicts almost no skewness or excess kurtosis. The
observed positive-deviation cohort instead has log-skewness near -2.40 and
log-excess-kurtosis near 8.11, concentrated in the near-geodesic boundary
tracks. That points to a mixture model rather than one universal product law.

## Main Results in Plain Language

- Route-scale variation can make path-deviation histograms look lognormal even
  when the underlying route shapes are not exactly lognormal.
- The Brownian-bridge baseline gives a concrete smoothing threshold: once
  route-scale spread is moderately larger than bridge-shape spread, residual
  skewness and kurtosis should be small.
- The observed cohort violates the single-population prediction because of a
  distinct near-geodesic lower-tail group.
- A sequential diagnostic asks how long one must watch before assigning one
  aircraft to that boundary population. In the current hour, the small-residual
  signal crosses high posterior confidence after about 41 elapsed minutes.
- The geodesic page also includes a fuel/energy counterfactual for aggregate
  excess ground track. This is an order-of-magnitude comparison to endpoint
  geodesics, not a claim that the excess is avoidable operational waste.

## Local Setup

Requirements: Python 3.10 or newer and OpenSky OAuth2 client credentials.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item credentials.example.json credentials.json
```

Edit the ignored `credentials.json` with the client ID and client secret from your OpenSky account. Never commit this file or paste its values into source code. Then start the local server:

```powershell
python app.py
```

Open <http://127.0.0.1:8000> for the live all-flights globe. The globe library and Earth texture are vendored under `static/vendor`, so the dashboard interface has no runtime CDN dependency.

The captured analytical results are a separate tabbed application at
<http://127.0.0.1:8000/experiments/index.html>. It combines the representative flight
traversals, altitude distribution, and path-deviation analysis while keeping
their generated source assets under `experiments/`.

No frontend build is required. The local web server itself uses only the Python standard library; `boto3` is needed by the AWS collector and Lambda tests.

## AWS

The production architecture and complete deploy, credential rotation, shutdown, restart, troubleshooting, and destruction procedures are documented in [AWS_SETUP.md](AWS_SETUP.md).

Because OpenSky currently times out AWS Lambda connections, the deploy script also starts a lightweight local SQS collector. It contacts OpenSky only after the authenticated owner presses Refresh on the deployed site.

```powershell
.\scripts\deploy.ps1
```

## Credit Safety

**The dashboard does not automatically fetch aircraft.** Starting the server and opening the page use zero OpenSky state credits. A global state request is made only when a user clicks **Refresh aircraft**.

Current safeguards:

- No polling loop, scheduled task, Server-Sent Events, or WebSocket refresh exists.
- A global manual refresh is accounted as four state credits.
- Manual refreshes have a 15-second server-side cooldown.
- A persisted local guard stops at 3,000 state credits per UTC day, below the standard authenticated allowance of 4,000.
- The server records `X-Rate-Limit-Remaining` when OpenSky returns it.
- All browser tabs share the server's one cached snapshot.
- `credentials.json` and the quota ledger under `data/` are gitignored.

The repository includes only `credentials.example.json`, which contains placeholders. AWS CLI credentials must stay in your external AWS profile under `%USERPROFILE%\.aws`; see [AWS_SETUP.md](AWS_SETUP.md) for deployment and secret-rotation procedures.

OpenSky credits are maintained in independent state, track, and flight buckets. The `/states/all` endpoint currently costs 1-4 state credits depending on bounding-box area; a global request costs four. Confirm current policy in the [official API documentation](https://openskynetwork.github.io/opensky-api/rest.html).

### Before Adding Automatic Refresh

Do not simply add `setInterval()` to `static/app.js`. Automatic refresh should be a backend-controlled feature with:

1. One shared poller regardless of browser count.
2. Polling only while at least one client is active.
3. Viewport bounding boxes and their actual credit cost.
4. A daily reserve and adaptive slowing based on `X-Rate-Limit-Remaining`.
5. Backoff using `X-Rate-Limit-Retry-After-Seconds` after HTTP 429.
6. A global cadence no faster than roughly two minutes for a standard account.

The guard comment above `MIN_REFRESH_SECONDS` in `app.py` and the comment at the end of `static/app.js` deliberately mark the two places where accidental polling is most likely to be introduced.

## API

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/api/status` | Local cache and quota status; never calls OpenSky |
| `GET` | `/api/aircraft` | Returns the cached snapshot; never calls OpenSky |
| `POST` | `/api/aircraft/refresh` | Performs one global OpenSky states request |
| `GET` | `/healthz` | Local health check |

## Analytics Direction

The dashboard cache is intentionally ephemeral. Historical collection and the
first analytical visualizations live under `experiments/`, separate from the
browser-to-server dashboard contract. Later layers can add sampled tracks in
SQLite, aggregate Parquet partitions, DuckDB queries, spherical density
estimation, flow-field geometry, anomaly detection, and graph analysis.

## Experiments

Historical and analytical work lives outside the dashboard under
`experiments/`. The [global state-series experiment](experiments/global-state-series/README.md)
contains a captured hour of one-minute OpenSky snapshots and produces raw
compressed responses plus full and top-500 Parquet datasets. Its browser
visualizations are combined at `/experiments/index.html` and include:

- Three representative flight traversals on an animated globe.
- The evolving global distribution of reported barometric altitude.
- Distributions of spherical path deviation from endpoint geodesics, with an
  accompanying random-scale bridge, lognormal-mixture formalism, and sequential
  boundary-population diagnostic.

Generated experiment data remains local and ignored by Git. The compact
JavaScript data files used by the visualizations are generated artifacts that
can be rebuilt from the local Parquet dataset.
