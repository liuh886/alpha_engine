"""Production-contract tests for BYD signal evidence binding."""

from __future__ import annotations

from copy import deepcopy

from src.research.byd_signal_evidence import (
    bind_final_signal_identity,
    close_evidence_is_current,
)


def _sources(*, open_eligible: bool) -> tuple[dict, dict, dict]:
    shadow = {
        "signal_date": "2026-08-07",
        "prospective_eligible": True,
        "open_research_eligible": open_eligible,
        "data_version": "shadow-v1",
    }
    paired = {
        "signal_date": "2026-08-07",
        "data_version": "paired-v1",
        "common_open_eligible": open_eligible,
        "prospective_eligible": open_eligible,
        "byd": {"prospective_eligible": True},
        "etf": {"independent_raw_confirmed": True},
    }
    expansion = {
        "signal_date": "2026-08-07",
        "data_version": "expansion-v1",
        "common_open_eligible": open_eligible,
        "prospective_eligible": open_eligible,
        "factors": {
            "market_state": "bear",
            "vol_state": "high",
            "mom_20": 0.01,
            "mom_60": -0.08,
            "drawdown_252": -0.20,
        },
    }
    return shadow, paired, expansion


def _alert() -> dict:
    return {
        "fingerprint": "decision-identity",
        "markdown": "<!-- signal-fingerprint:decision-identity -->\n",
        "data_provenance": {
            "shadow_manifest_sha256": "a" * 64,
            "paired_manifest_sha256": "b" * 64,
            "expansion_manifest_sha256": "c" * 64,
            "source_workflow": "byd-daily-signal-alert",
        },
        "factor_evidence": {
            "catalog_implementation_hash": "d" * 64,
            "source_sha256": "e" * 64,
        },
    }


def test_quarantined_same_session_open_does_not_make_close_data_stale() -> None:
    shadow, paired, expansion = _sources(open_eligible=False)
    assert close_evidence_is_current(shadow, paired, expansion) is True


def test_close_freshness_fails_when_independent_etf_evidence_is_missing() -> None:
    shadow, paired, expansion = _sources(open_eligible=True)
    paired["etf"]["independent_raw_confirmed"] = False
    assert close_evidence_is_current(shadow, paired, expansion) is False


def test_final_fingerprint_binds_factor_and_source_identity() -> None:
    first = bind_final_signal_identity(deepcopy(_alert()))
    changed = _alert()
    changed["factor_evidence"]["catalog_implementation_hash"] = "f" * 64
    second = bind_final_signal_identity(changed)

    assert first["decision_fingerprint"] == second["decision_fingerprint"]
    assert first["fingerprint"] != second["fingerprint"]
    assert f"signal-fingerprint:{first['fingerprint']}" in first["markdown"]
    assert "signal-fingerprint:decision-identity" not in first["markdown"]
