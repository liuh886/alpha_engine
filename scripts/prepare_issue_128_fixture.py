"""Prepare the legacy snapshot test fixture for the one-time #128 migration."""

from pathlib import Path

path = Path("tests/test_data_runtime_truth.py")
text = path.read_text(encoding="utf-8")
start = text.index("def _provider(")
end = text.index("\n\ndef test_snapshot_index", start)
replacement = '''def _provider(root: Path, value: bytes = b"provider") -> Path:
    provider = root / "provider"
    for symbol in ("AAPL", "MSFT", "SH600000"):
        (provider / "features" / symbol).mkdir(parents=True)
        (provider / "features" / symbol / "close.day.bin").write_bytes(value)
    (provider / "calendars").mkdir()
    (provider / "calendars" / "day.txt").write_text("2026-06-19\\n", encoding="utf-8")
    (provider / "instruments").mkdir()
    (provider / "instruments" / "us.txt").write_text(
        "AAPL\\t2026-06-19\\t2026-06-19\\n"
        "MSFT\\t2026-06-19\\t2026-06-19\\n",
        encoding="utf-8",
    )
    (provider / "instruments" / "cn.txt").write_text(
        "SH600000\\t2026-06-19\\t2026-06-19\\n",
        encoding="utf-8",
    )
    return provider
'''
path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
