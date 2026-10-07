"""Tests for the offline starter exercise.

    python -m unittest -v test_starter_report.py
"""
import unittest

from starter_report import SYNTHETIC_CANDLES, build_report, validate_candle


def candle(**overrides):
    row = {"instrument": "DEMO", "timestamp": "2030-01-07T16:00:00+00:00",
           "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0}
    row.update(overrides)
    return row


class ValidateCandleTests(unittest.TestCase):
    def test_valid_record_passes(self):
        self.assertEqual(validate_candle(candle()).year, 2030)

    def test_high_below_close_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            validate_candle(candle(high=102.0))

    def test_missing_timezone_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            validate_candle(candle(timestamp="2030-01-07T16:00:00"))

    def test_missing_timestamp_is_rejected(self):
        row = candle()
        del row["timestamp"]
        with self.assertRaisesRegex(ValueError, "Timestamp"):
            validate_candle(row)

    def test_non_finite_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_candle(candle(close=float("nan")))

    def test_boolean_is_not_a_price(self):
        # bool is a subclass of int in Python; True would otherwise pass as 1.
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_candle(candle(low=True))


class BuildReportTests(unittest.TestCase):
    def test_bundled_example(self):
        report = build_report(SYNTHETIC_CANDLES)
        self.assertEqual(report["valid"], 3)
        self.assertEqual(report["rejected"], [])
        self.assertEqual(report["change_pct"], 4.90)

    def test_reversed_input_gives_same_result(self):
        self.assertEqual(build_report(list(reversed(SYNTHETIC_CANDLES))),
                         build_report(SYNTHETIC_CANDLES))

    def test_same_instant_with_different_offsets_is_duplicate(self):
        rows = [candle(timestamp="2030-01-07T16:00:00+00:00"),
                candle(timestamp="2030-01-07T11:00:00-05:00")]
        report = build_report(rows)
        self.assertEqual(report["valid"], 1)
        self.assertIn("Duplicate", report["rejected"][0]["reason"])

    def test_invalid_rows_are_reported_not_dropped_silently(self):
        report = build_report([candle(), candle(high=1.0,
                               timestamp="2030-01-08T16:00:00+00:00")])
        self.assertEqual(report["valid"], 1)
        self.assertEqual(report["rejected"][0]["row"], 1)
        self.assertIsNone(report["change_pct"])


if __name__ == "__main__":
    unittest.main()
