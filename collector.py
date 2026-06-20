from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import boto3


TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"
SNAPSHOT_KEY = "data/latest.json"
CREDIT_COST = 4
DAILY_BUDGET = 3_000


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def stack_outputs(cloudformation: Any, stack_name: str) -> dict[str, str]:
    stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}


def get_token(credentials: dict[str, str]) -> str:
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
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)["access_token"]


def fetch_states(credentials: dict[str, str]) -> tuple[dict[str, Any], str | None]:
    request = urllib.request.Request(
        STATES_URL,
        headers={
            "Authorization": f"Bearer {get_token(credentials)}",
            "Accept": "application/json",
            "User-Agent": "Aerostat-Local-Collector/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response), response.headers.get("X-Rate-Limit-Remaining")


class Collector:
    def __init__(self, profile: str, region: str, stack_name: str):
        session = boto3.Session(profile_name=profile, region_name=region)
        self.s3 = session.client("s3")
        self.sqs = session.client("sqs")
        self.dynamodb = session.client("dynamodb")
        self.secrets = session.client("secretsmanager")
        outputs = stack_outputs(session.client("cloudformation"), stack_name)
        self.bucket = outputs["DataBucketName"]
        self.table = outputs["StateTableName"]
        self.queue_url = outputs["RefreshQueueUrl"]
        self.secret_arn = outputs["OpenSkySecretArn"]
        self.credentials: dict[str, str] | None = None

    def secret(self) -> dict[str, str]:
        if self.credentials is None:
            value = self.secrets.get_secret_value(SecretId=self.secret_arn)["SecretString"]
            self.credentials = json.loads(value)
        return self.credentials

    def quota_spent(self) -> int:
        result = self.dynamodb.get_item(
            TableName=self.table,
            Key={"id": {"S": f"quota#{utc_day()}"}},
            ConsistentRead=True,
        )
        try:
            return int(result["Item"]["spent"]["N"])
        except (KeyError, TypeError, ValueError):
            return 0

    def release(self, success: bool) -> None:
        values = {":zero": {"N": "0"}}
        expression = "SET lockUntil = :zero"
        if success:
            values[":now"] = {"N": str(int(time.time()))}
            expression += ", lastRefreshEpoch = :now"
        self.dynamodb.update_item(
            TableName=self.table,
            Key={"id": {"S": "refresh-control"}},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )

    def record_credit(self, fetched_at: str, remaining: str | None) -> None:
        values = {":cost": {"N": str(CREDIT_COST)}, ":updated": {"S": fetched_at}}
        expression = "SET updatedAt = :updated ADD spent :cost"
        if remaining is not None:
            try:
                values[":remaining"] = {"N": str(int(remaining))}
                expression = "SET updatedAt = :updated, openskyRemaining = :remaining ADD spent :cost"
            except ValueError:
                pass
        self.dynamodb.update_item(
            TableName=self.table,
            Key={"id": {"S": f"quota#{utc_day()}"}},
            UpdateExpression=expression,
            ExpressionAttributeValues=values,
        )

    def process(self, message: dict[str, Any]) -> None:
        try:
            if self.quota_spent() + CREDIT_COST > DAILY_BUDGET:
                raise RuntimeError("The conservative daily OpenSky credit budget is exhausted.")
            payload, remaining = fetch_states(self.secret())
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
                "requestCost": CREDIT_COST,
                "aircraft": aircraft,
            }
            self.record_credit(fetched_at, remaining)
            raw = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode()
            self.s3.put_object(
                Bucket=self.bucket,
                Key=SNAPSHOT_KEY,
                Body=gzip.compress(raw, compresslevel=6),
                ContentType="application/json",
                ContentEncoding="gzip",
                CacheControl="no-cache, no-store, must-revalidate",
                ServerSideEncryption="AES256",
                Metadata={"fetchedat": fetched_at, "aircraftcount": str(len(aircraft))},
            )
            self.release(success=True)
            print(f"Published {len(aircraft):,} aircraft at {fetched_at}", flush=True)
        except Exception as error:
            self.release(success=False)
            print(f"Refresh failed: {type(error).__name__}: {error}", flush=True)
        finally:
            self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=message["ReceiptHandle"])

    def run(self, watch: bool) -> None:
        print("Collector ready; OpenSky is called only after an owner refresh request.", flush=True)
        while True:
            result = self.sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=120,
            )
            messages = result.get("Messages") or []
            if messages:
                self.process(messages[0])
                if not watch:
                    return
            elif not watch:
                print("No refresh request is queued.", flush=True)
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="Consume explicitly requested OpenSky refresh jobs.")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--stack-name", default="opensky-dashboard")
    parser.add_argument("--watch", action="store_true", help="Wait continuously for manual refresh jobs.")
    args = parser.parse_args()
    Collector(args.profile, args.region, args.stack_name).run(watch=args.watch)


if __name__ == "__main__":
    main()
