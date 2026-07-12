"""Run the one-time issue #128 migration with a fixture-safe boundary patch.

Deleted before merge.
"""

from __future__ import annotations

from pathlib import Path


migration_path = Path("scripts/apply_issue_128_migration.py")
migration = migration_path.read_text(encoding="utf-8")
call = "patch_test_fixture()\n"
if call not in migration:
    raise SystemExit("issue 128 migration call not found")

# Execute all production and CI migrations, but skip the fragile literal fixture patch.
exec(compile(migration.replace(call, "", 1), str(migration_path), "exec"), {"__name__": "__main__"})

fixture_path = Path("tests/test_data_runtime_truth.py")
text = fixture_path.read_text(encoding="utf-8")
start = text.index("def _provider(")
end = text.index("\n\ndef test_snapshot_index_round_trips_exact_verified_manifest", start)
replacement = '''def _provider(root: Path, value: bytes = b"provider") -> Path:
    provider = root / "provider"
    for symbol in ("AAPL", "MSFT", "SH600000"):
        (provider / "features" / symbol).mkdir(parents=True)
        (provider / "features" / symbol / "close.day.bin").write_bytes(value)
    (provider / "calendars").mkdir()
    (provider / "calendars" / "day.txt").write_text(
        "2026-06-19\\n", encoding="utf-8"
    )
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
fixture_path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
