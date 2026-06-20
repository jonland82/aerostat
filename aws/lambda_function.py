from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError


TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"
SNAPSHOT_KEY = "data/latest.json"
STATE_CREDIT_COST = 4

DATA_BUCKET = os.environ["DATA_BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]
SECRET_ARN = os.environ["SECRET_ARN"]
REFRESH_QUEUE_URL = os.environ["REFRESH_QUEUE_URL"]
ADMIN_KEY_HASH = os.environ["ADMIN_KEY_HASH"]
ORIGIN_VERIFY = os.environ["ORIGIN_VERIFY"]
DAILY_BUDGET = int(os.environ.get("DAILY_BUDGET", "3000"))
MIN_REFRESH_SECONDS = int(os.environ.get("MIN_REFRESH_SECONDS", "15"))

s3 = boto3.client("s3")
dynamodb = boto3.client("dynamodb")
secrets = boto3.client("secretsmanager")
sqs = boto3.client("sqs")

_secret: dict[str, str] | None = None
_token: str | None = None
_token_expires_at = 0.0


class DashboardError(Exception):
    def __init__(self, status: int, message: str, code: str = "REQUEST_FAILED"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(payload, separators=(",", ":")),
    }


def headers(event: dict[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}


def require_cloudfront(event: dict[str, Any]) -> None:
    supplied = headers(event).get("x-origin-verify", "")
    if not hmac.compare_digest(supplied, ORIGIN_VERIFY):
        raise DashboardError(403, "Requests must use the dashboard CloudFront URL.", "ORIGIN_REQUIRED")


def require_admin(event: dict[str, Any]) -> None:
    supplied = headers(event).get("x-refresh-key", "")
    digest = hashlib.sha256(supplied.encode()).hexdigest()
    if not supplied or not hmac.compare_digest(digest, ADMIN_KEY_HASH):
        raise DashboardError(401, "The dashboard owner refresh key is invalid.", "ADMIN_KEY_REQUIRED")


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def number(item: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(item[key]["N"])
    except (KeyError, TypeError, ValueError):
        return default


def quota_item() -> dict[str, Any]:
    result = dynamodb.get_item(
        TableName=TABLE_NAME,
        Key={"id": {"S": f"quota#{utc_day()}"}},
        ConsistentRead=True,
    )
    return result.get("Item") or {}


def status_payload() -> dict[str, Any]:
    item = quota_item()
    control = dynamodb.get_item(
        TableName=TABLE_NAME,
        Key={"id": {"S": "refresh-control"}},
        ConsistentRead=True,
    ).get("Item") or {}
    spent = number(item, "spent")
    opensky_remaining = number(item, "openskyRemaining", -1)
    try:
        head = s3.head_object(Bucket=DATA_BUCKET, Key=SNAPSHOT_KEY)
        metadata = head.get("Metadata") or {}
        has_snapshot = True
        last_refresh = metadata.get("fetchedat")
        aircraft_count = int(metadata.get("aircraftcount", "0"))
        version = str(int(head["LastModified"].timestamp()))
        snapshot_url = f"/data/latest.json?v={version}"
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        has_snapshot = False
        last_refresh = None
        aircraft_count = 0
        snapshot_url = None
    return {
        "manualOnly": True,
        "autoRefresh": False,
        "requiresRefreshKey": True,
        "minimumRefreshSeconds": MIN_REFRESH_SECONDS,
        "hasSnapshot": has_snapshot,
        "snapshotUrl": snapshot_url,
        "lastRefresh": last_refresh,
        "aircraftCount": aircraft_count,
        "refreshPending": number(control, "lockUntil") > int(time.time()),
        "quota": {
            "day": utc_day(),
            "spent": spent,
            "budget": DAILY_BUDGET,
            "available": max(0, DAILY_BUDGET - spent),
            "openskyRemaining": None if opensky_remaining < 0 else opensky_remaining,
        },
    }


def acquire_refresh_lock() -> int:
    now = int(time.time())
    try:
        dynamodb.update_item(
            TableName=TABLE_NAME,
            Key={"id": {"S": "refresh-control"}},
            UpdateExpression="SET lockUntil = :lock",
            ConditionExpression=(
                "(attribute_not_exists(lockUntil) OR lockUntil < :now) AND "
                "(attribute_not_exists(lastRefreshEpoch) OR lastRefreshEpoch <= :cooldown)"
            ),
            ExpressionAttributeValues={
                ":lock": {"N": str(now + 300)},
                ":now": {"N": str(now)},
                ":cooldown": {"N": str(now - MIN_REFRESH_SECONDS)},
            },
        )
    except dynamodb.exceptions.ConditionalCheckFailedException as error:
        raise DashboardError(
            429,
            "A refresh is already running or the manual cooldown is active.",
            "REFRESH_COOLDOWN",
        ) from error
    spent = number(quota_item(), "spent")
    if spent + STATE_CREDIT_COST > DAILY_BUDGET:
        release_refresh_lock(success=False)
        raise DashboardError(429, "The conservative daily state-credit budget is exhausted.", "BUDGET_EXHAUSTED")
    return now


def queue_refresh(event: dict[str, Any]) -> dict[str, Any]:
    requested_at = acquire_refresh_lock()
    try:
        request_id = event.get("requestContext", {}).get("requestId") or str(requested_at)
        sqs.send_message(
            QueueUrl=REFRESH_QUEUE_URL,
            MessageBody=json.dumps({"requestedAt": requested_at, "requestId": request_id}),
            MessageGroupId="opensky-refresh",
            MessageDeduplicationId=request_id,
        )
        return {"queued": True, "status": status_payload()}
    except Exception:
        release_refresh_lock(success=False)
        raise


def release_refresh_lock(success: bool, now: int | None = None) -> None:
    values = {":zero": {"N": "0"}}
    expression = "SET lockUntil = :zero"
    if success:
        values[":now"] = {"N": str(now or int(time.time()))}
        expression += ", lastRefreshEpoch = :now"
    dynamodb.update_item(
        TableName=TABLE_NAME,
        Key={"id": {"S": "refresh-control"}},
        UpdateExpression=expression,
        ExpressionAttributeValues=values,
    )


def get_secret() -> dict[str, str]:
    global _secret
    if _secret is None:
        payload = secrets.get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        _secret = json.loads(payload)
    return _secret


def get_token(force: bool = False) -> str:
    global _token, _token_expires_at
    if not force and _token and _token_expires_at > time.time() + 30:
        return _token
    credentials = get_secret()
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": credentials["clientId"],
            "client_secret": credentials["clientSecret"],
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as token_response:
            payload = json.load(token_response)
    except urllib.error.HTTPError as error:
        print(f"OpenSky authentication HTTP error: {error.code}")
        raise DashboardError(502, "OpenSky authentication failed.", "OPENSKY_AUTH_FAILED") from error
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"OpenSky authentication network error: {type(error).__name__}: {error}")
        raise DashboardError(502, "Could not reach OpenSky authentication.", "OPENSKY_UNREACHABLE") from error
    _token = payload["access_token"]
    _token_expires_at = time.time() + int(payload.get("expires_in", 1800))
    return _token


def fetch_states(retry_auth: bool = True) -> tuple[dict[str, Any], str | None]:
    request = urllib.request.Request(
        STATES_URL,
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Accept": "application/json",
            "User-Agent": "Aerostat-OpenSky-Dashboard/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as states_response:
            return json.load(states_response), states_response.headers.get("X-Rate-Limit-Remaining")
    except urllib.error.HTTPError as error:
        if error.code == 401 and retry_auth:
            get_token(force=True)
            return fetch_states(retry_auth=False)
        if error.code == 429:
            raise DashboardError(429, "OpenSky's state-credit limit is currently exhausted.", "OPENSKY_LIMIT") from error
        raise DashboardError(502, f"OpenSky returned HTTP {error.code}.", "OPENSKY_FAILED") from error
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"OpenSky states network error: {type(error).__name__}: {error}")
        raise DashboardError(502, "Could not reach the OpenSky states API.", "OPENSKY_UNREACHABLE") from error


def normalize_state(row: list[Any]) -> dict[str, Any] | None:
    def item(index: int) -> Any:
        return row[index] if index < len(row) else None

    if item(5) is None or item(6) is None:
        return None
    return {
        "icao24": item(0),
        "callsign": (item(1) or "").strip() or None,
        "country": item(2),
        "timePosition": item(3),
        "lastContact": item(4),
        "longitude": item(5),
        "latitude": item(6),
        "baroAltitude": item(7),
        "onGround": bool(item(8)),
        "velocity": item(9),
        "trueTrack": item(10),
        "verticalRate": item(11),
        "geoAltitude": item(13),
        "squawk": item(14),
        "positionSource": item(16),
        "category": item(17),
    }


def refresh() -> dict[str, Any]:
    lock_time = acquire_refresh_lock()
    try:
        payload, remaining_header = fetch_states()
        aircraft = []
        for row in payload.get("states") or []:
            normalized = normalize_state(row)
            if normalized:
                aircraft.append(normalized)
        fetched_at = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "sourceTime": payload.get("time"),
            "fetchedAt": fetched_at,
            "count": len(aircraft),
            "requestCost": STATE_CREDIT_COST,
            "aircraft": aircraft,
        }
        raw = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode()
        s3.put_object(
            Bucket=DATA_BUCKET,
            Key=SNAPSHOT_KEY,
            Body=gzip.compress(raw, compresslevel=6),
            ContentType="application/json",
            ContentEncoding="gzip",
            CacheControl="no-cache, no-store, must-revalidate",
            ServerSideEncryption="AES256",
            Metadata={"fetchedAt": fetched_at, "aircraftCount": str(len(aircraft))},
        )
        values = {":cost": {"N": str(STATE_CREDIT_COST)}, ":updated": {"S": fetched_at}}
        update = "SET updatedAt = :updated ADD spent :cost"
        if remaining_header is not None:
            try:
                values[":remaining"] = {"N": str(int(remaining_header))}
                update = "SET updatedAt = :updated, openskyRemaining = :remaining ADD spent :cost"
            except ValueError:
                pass
        dynamodb.update_item(
            TableName=TABLE_NAME,
            Key={"id": {"S": f"quota#{utc_day()}"}},
            UpdateExpression=update,
            ExpressionAttributeValues=values,
        )
        release_refresh_lock(success=True, now=lock_time)
        current_status = status_payload()
        return {"snapshotUrl": current_status["snapshotUrl"], "status": current_status}
    except Exception:
        release_refresh_lock(success=False)
        raise


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    try:
        require_cloudfront(event)
        route = event.get("routeKey") or f"{event.get('requestContext', {}).get('http', {}).get('method', '')} {event.get('rawPath', '')}"
        if route == "GET /api/status":
            return response(200, status_payload())
        if route == "POST /api/aircraft/refresh":
            require_admin(event)
            return response(202, queue_refresh(event))
        return response(404, {"error": "Not found.", "code": "NOT_FOUND"})
    except DashboardError as error:
        return response(error.status, {"error": error.message, "code": error.code})
    except Exception as error:
        print(f"Unhandled dashboard error: {type(error).__name__}: {error}")
        return response(500, {"error": "The dashboard backend failed.", "code": "INTERNAL_ERROR"})
