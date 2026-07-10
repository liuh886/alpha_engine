"""Tests for the read-only decision-pack compatibility CLI."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_model_decision_pack import render_decision_pack


def test_cli_renderer_never_recomputes_promotion(tmp_path: Path) -> None:
    promotion_path = tmp_path / "promotion_decision.json"
    promotion_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "subject_id": "fixture-run",
                "status": "research_candidate",
                "trade_ready": False,
                "candidate": {"candidate": "lgbm:fixture", "mean_icir": 0.1},
                "failed_gates": ["mean_icir"],
                "missing_evidence": [],
                "evidence_refs": [],
                "contract_sha256": "a" * 64,
                "thresholds": {"min_mean_icir": 0.3},
                "rationale": "fixture remains research-only",
            }
        ),
        encoding="utf-8",
    )

    result = render_decision_pack(promotion_path, tmp_path / "rendered")
    pack = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")

    assert result["decision_source"] == "promotion_decision"
    assert result["may_recompute_decision"] is False
    assert pack["source"] == "promotion_decision"
    assert pack["decision"]["status"] == "research_candidate"
    assert pack["decision"]["trade_ready"] is False
    assert pack["promotion_decision"]["rationale"] == (
        "fixture remains research-only"
    )
    assert "Decision status: **research_candidate**" in markdown
