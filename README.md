# Aerostat OpenSky Globe

A lightweight, manually refreshed aircraft globe backed by the OpenSky Network API.

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

Open <http://127.0.0.1:8000>. The globe library and Earth texture are vendored under `static/vendor`, so the interface has no runtime CDN dependency.

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

## Next Layers

The current cache is intentionally ephemeral. A later analytics layer can add sampled tracks in SQLite, aggregate Parquet partitions, DuckDB queries, spherical density estimation, trajectory filters, flow-field geometry, anomaly detection, and graph analysis without changing the browser-to-server contract.
