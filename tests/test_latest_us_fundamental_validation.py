from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.research.latest_us_fundamental_validation as live


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_snapshot(monkeypatch, tmp_path: Path) -> Path:
    prices = tmp_path / "snapshot" / "2026-07-31" / "prices.csv"
    prices.parent.mkdir(parents=True)
    prices.write_text("date,symbol,open,close\n2026-07-31,QQQ,100,101\n", encoding="utf-8")

    def fake_snapshot(**kwargs):
        assert kwargs["start_date"] == "2020-01-01"
        return {
            "resolved_as_of_date": "2026-07-31",
            "prices_csv": str(prices),
            "trade_ready": False,
        }

    monkeypatch.setattr(live, "build_us_pool_price_snapshot", fake_snapshot)
    return prices


def test_live_wrapper_binds_source_and_validation(monkeypatch, tmp_path: Path) -> None:
    prices = _patch_snapshot(monkeypatch, tmp_path)

    def fake_sec(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "fundamentals.csv").write_text(
            "symbol,fiscal_period_end,filed_date,revenue,gross_profit,currency,form_type,accession_id\n",
            encoding="utf-8",
        )
        _write_json(output / "evidence_manifest.json", {"identity": "sec"})
        return {
            "decision": "sec_companyfacts_source_ready",
            "candidate_count": 23,
            "factor_ready_count": 23,
            "trade_ready": False,
        }

    def fake_validation(**kwargs):
        assert Path(kwargs["prices_csv"]) == prices
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        _write_json(
            output / "decision.json",
            {"decision": "simple_fundamental_factor_not_supported"},
        )
        _write_json(output / "evidence_manifest.json", {"identity": "validation"})
        return {
            "decision": "simple_fundamental_factor_not_supported",
            "trade_ready": False,
        }

    monkeypatch.setattr(live, "build_sec_companyfacts_fundamentals", fake_sec)
    monkeypatch.setattr(live, "run_minimal_fundamental_validation", fake_validation)

    result = live.run_latest_us_fundamental_validation(
        output_root=tmp_path / "live",
        snapshot_root=tmp_path / "snapshot",
        registry_db=tmp_path / "registry.db",
    )

    assert result["outputs"]["validation_decision"] == "simple_fundamental_factor_not_supported"
    assert result["source_grade"] == "current_sec_companyfacts_reconstruction_with_filed_dates"
    assert result["trade_ready"] is False
    assert len(result["run_identity_sha256"]) == 64
    manifest = tmp_path / "live" / "2026-07-31" / "latest_run_manifest.json"
    assert manifest.is_file()


def test_incomplete_sec_coverage_fails_closed(monkeypatch, tmp_path: Path) -> None:
    _patch_snapshot(monkeypatch, tmp_path)

    def fake_sec(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        return {
            "decision": "sec_companyfacts_source_ready_with_partial_coverage",
            "candidate_count": 23,
            "factor_ready_count": 22,
            "trade_ready": False,
        }

    monkeypatch.setattr(live, "build_sec_companyfacts_fundamentals", fake_sec)

    with pytest.raises(ValueError, match="do not cover every frozen candidate"):
        live.run_latest_us_fundamental_validation(
            output_root=tmp_path / "live",
            snapshot_root=tmp_path / "snapshot",
            registry_db=tmp_path / "registry.db",
        )

    blocked = tmp_path / "live" / "2026-07-31" / "blocked.json"
    payload = json.loads(blocked.read_text(encoding="utf-8"))
    assert payload["decision"] == "live_fundamental_validation_blocked"
    assert payload["factor_ready_count"] == 22
    assert payload["trade_ready"] is False
