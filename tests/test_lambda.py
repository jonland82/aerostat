import gzip
import hashlib
import importlib.util
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError


os.environ.update(
    {
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "DATA_BUCKET": "test-data",
        "TABLE_NAME": "test-state",
        "SECRET_ARN": "test-secret",
        "REFRESH_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123/test.fifo",
        "ADMIN_KEY_HASH": hashlib.sha256(b"owner-key").hexdigest(),
        "ORIGIN_VERIFY": "origin-key",
    }
)

MODULE_PATH = Path(__file__).parents[1] / "aws" / "lambda_function.py"
SPEC = importlib.util.spec_from_file_location("dashboard_lambda", MODULE_PATH)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class FakeDynamoDb:
    def __init__(self):
        self.updates = []

    def get_item(self, **kwargs):
        return {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}


class FakeS3:
    def __init__(self):
        self.object = None

    def head_object(self, **kwargs):
        if self.object is None:
            raise ClientError({"Error": {"Code": "404", "Message": "Not found"}}, "HeadObject")
        return {
            "Metadata": self.object["Metadata"],
            "LastModified": datetime.now(timezone.utc),
        }

    def put_object(self, **kwargs):
        self.object = kwargs
        return {}


class HandlerTests(unittest.TestCase):
    def test_rejects_direct_api_gateway_request(self):
        result = dashboard.lambda_handler({"routeKey": "GET /api/status", "headers": {}}, None)
        self.assertEqual(result["statusCode"], 403)

    def test_owner_key_is_required_for_refresh(self):
        result = dashboard.lambda_handler(
            {
                "routeKey": "POST /api/aircraft/refresh",
                "headers": {"x-origin-verify": "origin-key"},
            },
            None,
        )
        self.assertEqual(result["statusCode"], 401)

    def test_status_does_not_call_opensky(self):
        fake_s3 = FakeS3()
        with patch.object(dashboard, "s3", fake_s3), patch.object(dashboard, "dynamodb", FakeDynamoDb()):
            result = dashboard.lambda_handler(
                {"routeKey": "GET /api/status", "headers": {"X-Origin-Verify": "origin-key"}},
                None,
            )
        body = json.loads(result["body"])
        self.assertEqual(result["statusCode"], 200)
        self.assertFalse(body["hasSnapshot"])
        self.assertTrue(body["requiresRefreshKey"])


class RefreshTests(unittest.TestCase):
    def test_refresh_writes_compressed_snapshot(self):
        fake_s3 = FakeS3()
        fake_dynamo = FakeDynamoDb()
        states = {
            "time": 123,
            "states": [
                ["abc123", " TEST1 ", "United States", 1, 2, -73.5, 40.7, 1000, False, 200, 90, 3]
            ],
        }
        with (
            patch.object(dashboard, "s3", fake_s3),
            patch.object(dashboard, "dynamodb", fake_dynamo),
            patch.object(dashboard, "acquire_refresh_lock", return_value=100),
            patch.object(dashboard, "release_refresh_lock"),
            patch.object(dashboard, "fetch_states", return_value=(states, "3996")),
        ):
            result = dashboard.refresh()
        snapshot = json.loads(gzip.decompress(fake_s3.object["Body"]))
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["aircraft"][0]["callsign"], "TEST1")
        self.assertEqual(fake_s3.object["ContentEncoding"], "gzip")
        self.assertTrue(result["snapshotUrl"].startswith("/data/latest.json?v="))

    def test_drops_state_without_position(self):
        self.assertIsNone(dashboard.normalize_state(["abc123", None, "US", 1, 2, None, 40.7]))


if __name__ == "__main__":
    unittest.main()
