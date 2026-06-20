import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class CreditCostTests(unittest.TestCase):
    def test_global_costs_four_credits(self):
        self.assertEqual(app.credit_cost(None), 4)

    def test_bounding_box_cost_tiers(self):
        self.assertEqual(app.credit_cost({"lamin": 0, "lamax": 5, "lomin": 0, "lomax": 5}), 1)
        self.assertEqual(app.credit_cost({"lamin": 0, "lamax": 10, "lomin": 0, "lomax": 10}), 2)
        self.assertEqual(app.credit_cost({"lamin": 0, "lamax": 20, "lomin": 0, "lomax": 20}), 3)
        self.assertEqual(app.credit_cost({"lamin": -90, "lamax": 90, "lomin": -180, "lomax": 180}), 4)


class StateNormalizationTests(unittest.TestCase):
    def test_normalizes_state_vector(self):
        row = ["abc123", " TEST1 ", "United States", 1, 2, -73.5, 40.7, 1000, False, 200, 90, 3, None, 1100, "1200", False, 0, 3]
        result = app.normalize_state(row)
        self.assertEqual(result["callsign"], "TEST1")
        self.assertEqual(result["longitude"], -73.5)
        self.assertEqual(result["category"], 3)

    def test_drops_aircraft_without_position(self):
        self.assertIsNone(app.normalize_state(["abc123", None, "US", 1, 2, None, 40.7]))


class QuotaLedgerTests(unittest.TestCase):
    def test_persists_credit_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quota.json"
            ledger = app.QuotaLedger(path)
            ledger.record(4, "3996")
            restored = app.QuotaLedger(path).snapshot()
            self.assertEqual(restored["spent"], 4)
            self.assertEqual(restored["openskyRemaining"], 3996)

    def test_refuses_spend_over_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = app.QuotaLedger(Path(directory) / "quota.json")
            ledger.state["spent"] = app.LOCAL_DAILY_BUDGET
            with self.assertRaises(app.ApiError):
                ledger.require(1)


if __name__ == "__main__":
    unittest.main()
