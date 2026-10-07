"""Offline starter exercise for "Inside My Trading Agent" (Appendix B).

Validates a few invented OHLC candles, rejects duplicates, orders them by
instant and prints a small report. Standard library only; no network access.

    python starter_report.py
"""
from datetime import datetime, timezone
from math import isfinite

SYNTHETIC_CANDLES = [
    # Deliberately out of order and with mixed offsets: the report must sort
    # by instant, not by string.
    {"instrument": "DEMO", "timestamp": "2030-01-08T16:00:00+00:00",
     "open": 102.0, "high": 105.0, "low": 101.0, "close": 104.0},
    {"instrument": "DEMO", "timestamp": "2030-01-07T11:00:00-05:00",
     "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
    {"instrument": "DEMO", "timestamp": "2030-01-09T16:00:00+00:00",
     "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0},
]

PRICE_FIELDS = ("open", "high", "low", "close")


def validate_candle(row):
    """Return the candle's timestamp as an aware datetime or raise ValueError."""
    try:
        stamp = datetime.fromisoformat(row["timestamp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Timestamp is missing or unreadable") from exc
    if stamp.utcoffset() is None:
        raise ValueError("Timestamp needs a timezone")
    try:
        values = [row[k] for k in PRICE_FIELDS]
    except KeyError as exc:
        raise ValueError(f"Missing price field: {exc.args[0]}") from exc
    if any(isinstance(v, bool) or
           not isinstance(v, (int, float)) or
           not isfinite(v) or v <= 0 for v in values):
        raise ValueError("Prices must be finite and positive")
    o, h, l, c = values
    if not (l <= min(o, c) <= max(o, c) <= h):
        raise ValueError("Inconsistent OHLC prices")
    return stamp


def build_report(rows):
    """Validate, de-duplicate and order candles; return a report dictionary."""
    valid, rejected, seen = [], [], {}
    for index, row in enumerate(rows):
        try:
            stamp = validate_candle(row)
        except ValueError as exc:
            rejected.append({"row": index, "reason": str(exc)})
            continue
        instant = stamp.astimezone(timezone.utc)
        if instant in seen:
            rejected.append({"row": index,
                             "reason": f"Duplicate instant (same as row {seen[instant]})"})
            continue
        seen[instant] = index
        valid.append((instant, row))

    valid.sort(key=lambda item: item[0])
    report = {"valid": len(valid), "rejected": rejected, "change_pct": None}
    if len(valid) >= 2:
        first, last = valid[0][1]["close"], valid[-1][1]["close"]
        report["first_utc"] = valid[0][0].isoformat()
        report["last_utc"] = valid[-1][0].isoformat()
        report["change_pct"] = round((last / first - 1) * 100, 2)
    return report


def main():
    report = build_report(SYNTHETIC_CANDLES)
    print("SYNTHETIC DATA - not market observations")
    print(f"Valid candles:    {report['valid']}")
    print(f"Rejected rows:    {len(report['rejected'])}")
    for item in report["rejected"]:
        print(f"  row {item['row']}: {item['reason']}")
    if report["change_pct"] is not None:
        print(f"First close (UTC): {report['first_utc']}")
        print(f"Last close (UTC):  {report['last_utc']}")
        print(f"Close-to-close:   {report['change_pct']:.2f}%")


if __name__ == "__main__":
    main()
