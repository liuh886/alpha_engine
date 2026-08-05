"""Apply the Phase 1 empty-window fix and freeze the first live source cache."""

from __future__ import annotations

import py_compile
from pathlib import Path

BRANCH_WORKFLOW = Path(".github/workflows/cn130-pit-event-families-phase1.yml")
BUILDER = Path("scripts/data/build_cn130_pit_event_families.py")
TEST = Path("tests/test_cn130_pit_event_family_audit.py")
SELF = Path(__file__)
PATCH_WORKFLOW = Path(".github/workflows/cn130-pit-event-families-phase1-patch.yml")


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

    workflow = BRANCH_WORKFLOW.read_text(encoding="utf-8")
    workflow = replace_once(
        workflow,
        "  CALIBRATION_LEDGER_ARTIFACT_ID: '8927662386'\n",
        "  CALIBRATION_LEDGER_ARTIFACT_ID: '8927662386'\n"
        "  SOURCE_CACHE_ARTIFACT_ID: '8933376684'\n"
        "  SOURCE_CACHE_ARTIFACT_SHA256: '53b1b1c1bf4c0fcead2e6e60283400879c7332968ddf8c08d91c00a91bd4560a'\n",
        label="source cache env",
    )
    workflow = replace_once(
        workflow,
        "      - name: Build source cache and execute twice\n",
        "      - name: Download frozen source cache\n"
        "        run: |\n"
        "          mkdir -p .research/source-cache-artifact .research/source-cache\n"
        "          gh api \"/repos/${GITHUB_REPOSITORY}/actions/artifacts/${SOURCE_CACHE_ARTIFACT_ID}/zip\" > .research/source-cache.zip\n"
        "          test \"$(sha256sum .research/source-cache.zip | awk '{print $1}')\" = \"${SOURCE_CACHE_ARTIFACT_SHA256}\"\n"
        "          unzip -q .research/source-cache.zip -d .research/source-cache-artifact\n"
        "          cp -R .research/source-cache-artifact/source-cache/. .research/source-cache/\n"
        "          test \"$(find .research/source-cache -type f -name '*.json' | wc -l | tr -d ' ')\" = \"294\"\n"
        "      - name: Execute frozen source cache twice\n",
        label="frozen source cache step",
    )
    workflow = replace_once(
        workflow,
        "            --execution-at \"$EXECUTION_AT\" \\\n            --refresh-source-cache\n",
        "            --execution-at \"$EXECUTION_AT\"\n",
        label="remove live refresh",
    )
    BRANCH_WORKFLOW.write_text(workflow, encoding="utf-8")

    SELF.unlink()
    PATCH_WORKFLOW.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
