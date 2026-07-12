"""One-time patch for the issue #128 snapshot identity fixture. Deleted before merge."""

from pathlib import Path

path = Path("tests/test_data_runtime_truth.py")
text = path.read_text(encoding="utf-8")
old = '''    # Quality report matching the 1-symbol universe used here.
    qr = {
        "ok": True,
        "latest_calendar_day": "2026-06-19",
        "warnings": [],
        "markets": {
            "us": {
                "instruments": 1,
                "stale_instruments": 0,
                "csv_missing": 0,
                "csv_parse_errors": 0,
                "csv_stale": 0,
            },
        },
    }
    acct = update_data.UpdateAccounting(configured={"us": ["AAPL"]})
    acct.add("attempted", "us", "AAPL")
    acct.add("updated", "us", "AAPL")
'''
new = '''    # Quality report matching the two-symbol provider fixture used here.
    qr = {
        "ok": True,
        "latest_calendar_day": "2026-06-19",
        "warnings": [],
        "markets": {
            "us": {
                "instruments": 2,
                "stale_instruments": 0,
                "csv_missing": 0,
                "csv_parse_errors": 0,
                "csv_stale": 0,
            },
        },
    }
    acct = update_data.UpdateAccounting(configured={"us": ["AAPL", "MSFT"]})
    for symbol in ("AAPL", "MSFT"):
        acct.add("attempted", "us", symbol)
        acct.add("updated", "us", symbol)
'''
if old not in text:
    if new in text:
        raise SystemExit(0)
    raise SystemExit("snapshot identity fixture anchor not found")
text = text.replace(old, new, 1)
text = text.replace(
    '            universe={"us": ["AAPL"]},\n',
    '            universe={"us": ["AAPL", "MSFT"]},\n',
    1,
)
path.write_text(text, encoding="utf-8")
