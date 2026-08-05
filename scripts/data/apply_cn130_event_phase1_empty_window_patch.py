"""Apply the Phase 1 empty-window audit fix and regression test."""

from __future__ import annotations

import py_compile
from pathlib import Path

BUILDER = Path("scripts/data/build_cn130_pit_event_families.py")
TEST = Path("tests/test_cn130_pit_event_family_audit.py")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one replacement target, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    builder = BUILDER.read_text(encoding="utf-8")
    builder = replace_once(
        builder,
        '        matched = rebalance.loc[rebalance.get("matched_event_id", "") != ""].copy()\n',
        '        if "matched_event_id" not in rebalance.columns:\n'
        '            rebalance["matched_event_id"] = ""\n'
        '        matched = rebalance.loc[\n'
        '            rebalance["matched_event_id"].fillna("") != ""\n'
        '        ].copy()\n',
        label="empty rebalance fix",
    )
    BUILDER.write_text(builder, encoding="utf-8")
    py_compile.compile(str(BUILDER), doraise=True)

    test = TEST.read_text(encoding="utf-8")
    test = replace_once(
        test,
        "    CALIBRATION_HALF_YEARS,\n    build_r0_top3_rows,\n",
        "    CALIBRATION_HALF_YEARS,\n    audit_family,\n    build_r0_top3_rows,\n",
        label="audit_family test import",
    )
    regression = '''\n\ndef test_audit_family_handles_event_half_year_without_rebalance_rows() -> None:\n    events = pd.DataFrame(\n        [\n            {\n                "event_family": "earnings_forecast",\n                "event_id": "event-1",\n                "symbol": "000001",\n                "event_stage": "forecast_initial",\n                "announced_at": "2022-07-01T00:00:00+08:00",\n                "announced_date": "2022-07-01",\n                "half_year": "2022H2",\n                "revision_sequence": 0,\n                "first_eligible_session": "2022-07-04",\n                "availability_status": "usable",\n                "reconciliation_status": "reconciled",\n            }\n        ]\n    )\n    top3 = pd.DataFrame(\n        [\n            {\n                "window": "2023H1",\n                "date": "2023-01-03",\n                "instrument": "000001",\n                "sector": "Bank",\n                "sector_rank": 1.0,\n                "is_rebalance": True,\n            }\n        ]\n    )\n\n    rows = audit_family(\n        family="earnings_forecast",\n        events=events,\n        top3=top3,\n        sessions=["2022-07-01", "2022-07-04", "2023-01-03"],\n    )\n    result = {row["half_year"]: row for row in rows}\n\n    assert result["2022H2"]["fixed_top3_rows"] == 0\n    assert result["2022H2"]["fixed_recent_top3_coverage"] == 0.0\n'''
    if "test_audit_family_handles_event_half_year_without_rebalance_rows" in test:
        raise RuntimeError("regression test already exists")
    TEST.write_text(test + regression, encoding="utf-8")
    py_compile.compile(str(TEST), doraise=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
