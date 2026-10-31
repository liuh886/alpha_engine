"""Synthetic RDI Phase 2: point-in-time, coverage, purge, ETF admission tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import csv
import io

import pytest

from src.research.ashare_rdi.contracts import RiskEvent
from src.research.ashare_rdi.briefing import BASELINE, PRICE, READINESS, SECTORS, SOURCES, CONTRACT, SOURCE_MANIFEST, PROTOCOL, build_research_briefing
from src.research.ashare_rdi.coverage import FamilyCoverage, audit_coverage, coverage_cells_ready
from src.research.ashare_rdi.outcomes import PriceBar
from src.research.ashare_rdi.phase2 import build_pit_panel, evaluate_blocked_oos, read_price_csv
from src.research.ashare_rdi.phase2_audit import source_readiness
from src.research.ashare_rdi.price_baseline import descriptive_drawdown_comparison
from src.research.ashare_rdi.price_renewal import audit_price_renewal
from src.research.ashare_rdi.price_reconstruction import repair_prices, replay_source, recompute, repo_file
from src.research.ashare_rdi.sector_etfs import SectorETFCandidate, audit_sector_etf


def _renewal_inputs(*, missing=False, conflict=False, wrong_identity=False, future=False):
    days = ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"]
    old_days = days[:3] if not missing else [days[0], days[2]]
    legacy = ("date,open,high,low,close\n" + "".join(
        f"{day},100,101,99,100\n" for day in old_days)).encode()
    security = {"market": "cn", "instrument_id": "cn:000300", "symbol": "000300",
                "provider_symbol": "000300", "roles": ["benchmark"], "start": days[0],
                "cutoff": days[-1], "source_csv_sha256": "a" * 64,
                "provider_manifest_sha256": "b" * 64, "research_only": True,
                "trade_ready": False, "bars": [dict(time=d, open=100, high=101, low=99, close=100) for d in days]}
    if conflict:
        security["bars"][1]["close"] = 100.5
    if wrong_identity:
        security["symbol"] = "515180"
    raw = json.dumps(security).encode()
    catalog = {"market": "cn", "cutoff": days[-1], "provider_manifest_sha256": "b" * 64,
               "research_only": True, "trade_ready": False,
               "symbols": [{"instrument_id": "cn:000300", "path": "symbols/000300.json",
                            "sha256": hashlib.sha256(raw).hexdigest(), "start": days[0], "cutoff": days[-1]}]}
    return legacy, json.dumps(catalog).encode(), raw, date(2021, 1, 6 if future else 7)


def test_renewal_clean_overlap_is_not_provider_or_pit_admission():
    old, catalog, security, cutoff = _renewal_inputs()
    result = audit_price_renewal(old, catalog, security, completed_cutoff=cutoff)
    assert result["blockers"] == ["original_provider_bytes_and_index_price_basis_not_certified"]
    assert result["overlap_rows"] == 3 and result["append_candidate_rows"] == 1
    assert not result["price_splice_written"] and not result["baseline_recomputed"]
    assert not result["event_history_ready"] and not result["predictive_skill_established"]


@pytest.mark.parametrize("condition,blocker", [
    ("missing", "retained_history_calendar_conflict"),
    ("conflict", "overlapping_ohlc_conflict"),
])
def test_renewal_preserves_calendar_and_overlap_failures(condition, blocker):
    old, catalog, security, cutoff = _renewal_inputs(**{condition: True})
    result = audit_price_renewal(old, catalog, security, completed_cutoff=cutoff)
    assert blocker in result["blockers"]
    assert result["status"] == "blocked_price_renewal"
    if condition == "missing":
        assert result["retained_history"]["missing_sessions"] == ["2021-01-05"]
    else:
        assert result["overlap_conflicts"][0]["session"] == "2021-01-05"


@pytest.mark.parametrize("condition,message", [
    ("wrong_identity", "identity/hash mismatch"), ("future", "completed-session cutoff"),
])
def test_renewal_rejects_wrong_instrument_and_future_prices(condition, message):
    old, catalog, security, cutoff = _renewal_inputs(**{condition: True})
    with pytest.raises(ValueError, match=message):
        audit_price_renewal(old, catalog, security, completed_cutoff=cutoff)


def test_renewal_rejects_unbound_candidate_bytes():
    old, catalog, security, cutoff = _renewal_inputs()
    with pytest.raises(ValueError, match="identity/hash mismatch"):
        audit_price_renewal(old, catalog, security + b" ", completed_cutoff=cutoff)


def _repair_fixture():
    old = b"date,open,high,low,close\n2021-01-04,100.000,101,98.000,100.00\n2021-01-06,100,101,98,99\n"
    source = b"date,open,high,low,close\n2021-01-04,100,101,98,100\n2021-01-05,100,101,98,100\n2021-01-06,100,101,98,100\n2021-01-07,100,101,98,100\n"
    contract = {"start": "2021-01-04", "cutoff": "2021-01-07", "retained_cutoff": "2021-01-06",
                "legacy_sha256": hashlib.sha256(old).hexdigest(), "expected_retained_rows": 2,
                "expected_output_rows": 4, "expected_append_rows": 1,
                "ohlc_audit_resolution_index_points": 0.01,
                "output_fields": ["date", "open", "high", "low", "close"],
                "insert_sessions": ["2021-01-05"],
                "replacements": [{"date": "2021-01-06", "field": "close", "old": "99", "new": "100"}]}
    return old, source, contract


def test_versioned_repair_preserves_untouched_strings_and_declares_every_change():
    old, source, contract = _repair_fixture()
    result, receipt = repair_prices(old, source, contract)
    rows = list(csv.DictReader(io.StringIO(result.decode())))
    assert rows[0]["open"] == "100.000" and rows[0]["close"] == "100.00"
    assert rows[2]["close"] == "100" and len(rows) == 4
    assert receipt["insert_sessions"] == ["2021-01-05"] and receipt["append_rows"] == 1


@pytest.mark.parametrize("mutation", ["replacement", "insert", "legacy", "extra_repair", "tolerance"])
def test_versioned_repair_rejects_undeclared_or_unnecessary_changes(mutation):
    old, source, contract = _repair_fixture()
    if mutation == "replacement":
        contract["replacements"][0]["new"] = "100.5"
    elif mutation == "insert":
        contract["insert_sessions"] = []
    elif mutation == "legacy":
        old += b" "
    elif mutation == "extra_repair":
        contract["replacements"].append({"date": "2021-01-04", "field": "open", "old": "100.000", "new": "100"})
    else:
        contract["ohlc_audit_resolution_index_points"] = 2
    with pytest.raises(ValueError):
        repair_prices(old, source, contract)


def test_reconstruction_paths_cannot_escape_repository(tmp_path):
    with pytest.raises(ValueError):
        repo_file(tmp_path, "../external/source.gz")


def test_source_replay_rejects_archive_tampering(tmp_path):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "data/research/ashare_rdi/price_sources/sina_2026-10-31/manifest.json").read_bytes())
    manifest["archive_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="archive digest"):
        replay_source(root, manifest)


def test_real_reconstruction_is_offline_preserves_legacy_and_bounds_labels(monkeypatch):
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("offline reconstruction attempted a network call")

    monkeypatch.setattr(requests, "get", forbidden)
    root = Path(__file__).resolve().parents[1]
    contract = root / "configs/research_experiments/ashare_rdi_csi300_price_repair_2026-10-31.json"
    frozen = contract.read_bytes()
    prices, receipt = recompute(root, contract, completed_cutoff=date(2026, 10, 30))
    assert receipt["repairs"]["output_rows"] == 5238
    assert receipt["repairs"]["append_rows"] == 85
    assert receipt["repairs"]["insert_sessions"] == ["2026-06-23"]
    assert len(receipt["repairs"]["replacement_fields"]) == 2
    assert not receipt["legacy_source_overwritten"] and not receipt["event_study_ready"]
    assert hashlib.sha256(prices).hexdigest() == receipt["output_sha256"]
    assert contract.read_bytes() == frozen
    original = subprocess.check_output(["git", "cat-file", "blob", receipt["legacy_git_blob_sha1"]], cwd=root)
    output = {r["date"]: r for r in csv.DictReader(io.StringIO(prices.decode()))}
    exceptions = {("2026-06-22", "high"), ("2026-06-22", "close")}
    for row in csv.DictReader(io.StringIO(original.decode())):
        if row["date"] >= "2005-04-08":
            for field in ("open", "high", "low", "close"):
                if (row["date"], field) not in exceptions:
                    assert output[row["date"]][field] == row[field]
    for row in receipt["retrospective_stress_case"]["results"]:
        assert row["label_end_end"] == "2026-10-30"
        assert row["insufficient_future_bars"]["count"] == row["horizon_sessions"]
        assert row["eligible_observation_end"] < "2026-10-30"


def test_windowed_baseline_keeps_prior_warmup_and_never_shortens_tail():
    bars = _bars(100)
    result = descriptive_drawdown_comparison(bars, observation_start=bars[90].session, horizons=(7,))
    row = result["results"][0]
    assert row["drawdown_at_least_threshold"]["observations"] + row["other"]["observations"] == 3
    assert row["eligible_observation_start"] == bars[90].session.isoformat()
    assert row["label_end_end"] == bars[-1].session.isoformat()
    assert row["insufficient_future_bars"]["count"] == 7


def _cov(day: date, family: str = "holding_change", archived: bool = True) -> FamilyCoverage:
    return FamilyCoverage(day, family, "verified", "fixture://cninfo", "a" * 64, archived)


def _bars(n: int = 240) -> list[PriceBar]:
    d = date(2020, 1, 2)
    return [PriceBar(d + timedelta(days=i), 90 + i % 14, 88 + i % 14, 91 + i % 14) for i in range(n)]


def _event(available: datetime, direction: str = "risk") -> RiskEvent:
    return RiskEvent(
        event_id=f"event-{direction}-{available.day}", story_id="story-1",
        family="holding_change", direction=direction, scope="market", sector_id=None,
        stage="announced", announced_at=available - timedelta(hours=1),
        available_at=available, active_from=date(2020, 3, 1),
        active_until=date(2020, 8, 1), source_id="fixture://cninfo",
        source_hash="a" * 64,
    )


def test_missing_history_never_means_zero_events() -> None:
    a, b = date(2020, 1, 1), date(2020, 1, 2)
    report = audit_coverage([_cov(a)], [a, b], ["holding_change"])
    assert report["status"] == "blocked_incomplete_event_history"
    assert report["missing_cells"] == 1
    assert not coverage_cells_ready({(a, "holding_change"): _cov(a)}, b, ["holding_change"])


def test_unverified_coverage_is_not_eligible() -> None:
    d = date(2020, 1, 2)
    assert audit_coverage([_cov(d, archived=False)], [d], ["holding_change"])["usable_cells"] == 0
    with pytest.raises(ValueError, match="SHA-256"):
        FamilyCoverage(d, "holding_change", "verified", "source", "", True)


def test_pit_panel_filters_future_revisions() -> None:
    bars = _bars()
    coverage = [_cov(p.session) for p in bars]
    first = _event(datetime(2020, 2, 1, tzinfo=timezone.utc))
    later = _event(datetime(2020, 7, 1, tzinfo=timezone.utc), direction="clearing")
    panel, gate = build_pit_panel(
        bars, [first, later], coverage, required_families=["holding_change"],
        horizon=7, validated_sessions=[p.session for p in bars],
    )
    assert gate["history"]["status"] == "ready"
    march = next(r for r in panel if r["session"] == "2020-03-10")
    july = next(r for r in panel if r["session"] == "2020-07-10")
    assert march["risk_density"] == 1.0 and march["clearing_density"] == 0.0
    assert july["risk_density"] == 0.0 and july["clearing_density"] == 1.0


def test_missing_family_blocks_every_research_row() -> None:
    bars = _bars()
    panel, gate = build_pit_panel(
        bars, [], [_cov(p.session) for p in bars],
        required_families=["holding_change", "ipo_refinancing"],
        horizon=14, validated_sessions=[p.session for p in bars],
    )
    assert panel == []
    assert gate["history"]["status"] == "blocked_incomplete_event_history"


def test_provider_calendar_boundary_is_enforced() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="exactly match"):
        build_pit_panel(bars, [], [_cov(p.session) for p in bars],
                        required_families=["holding_change"], horizon=7,
                        validated_sessions=[p.session for p in bars[:-1]])


def test_unobserved_label_tail_is_excluded() -> None:
    bars = _bars(80)
    panel, _ = build_pit_panel(
        bars, [], [_cov(p.session) for p in bars], required_families=["holding_change"],
        horizon=14, validated_sessions=[p.session for p in bars],
    )
    assert len(panel) == 6
    assert panel[-1]["session"] == bars[65].session.isoformat()


def test_oos_purge_removes_overlap_at_actual_label_end() -> None:
    d = date(2018, 1, 1)
    panel = [{
        "session": (d + timedelta(days=i)).isoformat(),
        "end_session": (d + timedelta(days=i + 28)).isoformat(),
        "horizon_sessions": 28,
        "down": int(i % 5 in (0, 1)),
        "risk_density": float((i // 13) % 4),
        "clearing_density": float((i // 19) % 2),
        "bear_drawdown_60": float((i % 17) - 17) / 100,
    } for i in range(330)]
    outcome = evaluate_blocked_oos(panel, horizon=28)
    assert outcome["status"] == "diagnostic_only"
    assert outcome["train_last_label_end"] < outcome["test_first_session"]
    assert outcome["incremental_event_model"]["features"] == [
        "bear_drawdown_60", "risk_density", "clearing_density"
    ]


def test_empty_sample_does_not_report_forecast_skill() -> None:
    assert evaluate_blocked_oos([], horizon=7)["status"] == "insufficient_samples"


def test_pre_inception_ohlcv_excluded_and_rdi_blocked(tmp_path) -> None:
    path = tmp_path / "csi.csv"
    path.write_text(
        "date,open,low,close\n2002-01-04,10,9,10\n"
        "2005-04-08,11,10,11\n2005-04-11,12,11,12\n",
        encoding="utf-8",
    )
    assert [p.session.isoformat() for p in read_price_csv(path)] == ["2005-04-08", "2005-04-11"]
    receipt = source_readiness(path)
    assert receipt["status"] == "blocked_event_pit_coverage"
    assert receipt["last_observed_session"] == "2005-04-11"
    assert receipt["predictive_claim"] is False


def test_sector_etf_eligibility_needs_more_than_ticker_and_inception() -> None:
    etf = SectorETFCandidate(
        "512480.SH", "semiconductors", date(2019, 5, 8), date(2019, 6, 12),
        "https://www.sse.com.cn",
    )
    prices = [
        PriceBar(date(2019, 6, 13) + timedelta(days=i), 2, 1.9, 2.1)
        for i in range(10)
    ]
    report = audit_sector_etf(etf, prices, required_last_session=date(2019, 8, 1))
    assert report["status"] == "blocked"
    assert "liquidity_not_verified" in report["blockers"]
    assert "insufficient_verified_history" in report["blockers"]


def test_severe_outcomes_are_separately_defined_from_down_direction() -> None:
    bars = _bars()
    panel, _ = build_pit_panel(
        bars, [], [_cov(p.session) for p in bars], required_families=["holding_change"],
        horizon=7, validated_sessions=[p.session for p in bars],
    )
    assert panel
    assert all(row["severe_loss_5pct"] in (0, 1) for row in panel)
    assert all(row["path_loss_5pct"] in (0, 1) for row in panel)
    with pytest.raises(ValueError, match="target"):
        evaluate_blocked_oos(panel, horizon=7, target="invalid")


def test_price_only_baseline_is_descriptive_not_rdi() -> None:
    bars = _bars(100)
    result = descriptive_drawdown_comparison(bars, horizons=(7,))
    assert result["event_rdi_evaluated"] is False
    assert result["predictive_skill_established"] is False
    assert result["results"][0]["horizon_sessions"] == 7
    assert (
        result["results"][0]["other"]["observations"]
        + result["results"][0]["drawdown_at_least_threshold"]["observations"]
        == 34
    )


@pytest.fixture
def briefing_repo(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    for name in (READINESS, BASELINE, SOURCES, SECTORS, CONTRACT, SOURCE_MANIFEST, PRICE, PROTOCOL):
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, dest)
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "--quiet", "--no-gpg-sign", "-m", "fixture"], cwd=tmp_path, check=True)
    return tmp_path


def test_product_briefing_is_dated_and_never_promotes(briefing_repo: Path) -> None:
    result = build_research_briefing(briefing_repo)
    assert result["status"] == "not_validated"
    assert result["reviewed_price_cutoff"] == "2026-10-30"
    assert result["reviewed_price_rows"] == 5238
    assert [r["horizon_sessions"] for r in result["historical_comparison"]] == [7, 14, 28]
    assert all(not r["historical_pit_verified"] for r in result["event_families"])
    assert all(not r["admitted"] for r in result["sector_candidates"])
    assert result["trade_ready"] is False
    assert len(result["repository_commit"]) == 40
    assert all(len(row["sha256"]) == 64 for row in result["evidence"])


def test_sparse_checkout_uses_source_tree_without_copying_prices(briefing_repo: Path) -> None:
    (briefing_repo / PRICE).unlink()
    result = build_research_briefing(briefing_repo)
    assert result["status"] == "not_validated"
    assert not (briefing_repo / PRICE).exists()


@pytest.mark.parametrize("name", [CONTRACT, SOURCE_MANIFEST, PROTOCOL])
def test_rebound_source_chain_changes_withhold_comparison(briefing_repo: Path, name: str):
    path = briefing_repo / name
    path.write_bytes(path.read_bytes() + b"\n")
    result = build_research_briefing(briefing_repo)
    assert result["status"] == "evidence_mismatch" and result["historical_comparison"] == []


def test_product_read_does_not_import_price_decoder_or_evaluator(briefing_repo: Path):
    import sys

    command = ("import sys; from pathlib import Path; "
               "from src.research.ashare_rdi.briefing import build_research_briefing; "
               f"build_research_briefing(Path({str(briefing_repo)!r})); "
               "assert 'akshare' not in sys.modules; assert 'sklearn' not in sys.modules; "
               "assert 'src.research.ashare_rdi.price_reconstruction' not in sys.modules")
    subprocess.run([sys.executable, "-c", command], check=True)


def test_original_preflight_remains_replayable_after_product_rebinding():
    import sys

    raw = subprocess.check_output([
        sys.executable, "-m", "src.research.ashare_rdi.phase2_audit",
        "--price-renewal-audit", "--as-of", "2026-10-30",
    ])
    report = json.loads(raw)
    assert report["source_git_blob_sha1"] == "4f6f2dec557b8a55af748f73c49465d5d4686beb"
    assert report["status"] == "blocked_price_renewal"
    assert report["retained_history"]["missing_sessions"] == ["2026-06-23"]


def test_source_change_suppresses_all_descriptive_statistics(briefing_repo: Path) -> None:
    with (briefing_repo / PRICE).open("ab") as handle:
        handle.write(b"2020-01-03,11,10,11\n")
    result = build_research_briefing(briefing_repo)
    assert result["status"] == "evidence_mismatch"
    assert result["historical_comparison"] == []


@pytest.mark.parametrize("change", [
    {"last_price_session": "2026-10-23"},
    {"predictive_skill_established": True},
    {"drawdown_threshold": -0.2},
    {"results": []},
])
def test_incompatible_archived_claims_are_hidden(briefing_repo: Path, change: dict) -> None:
    path = briefing_repo / BASELINE
    report = json.loads(path.read_text())
    report.update(change)
    path.write_text(json.dumps(report), encoding="utf-8")
    result = build_research_briefing(briefing_repo)
    assert result["status"] == "evidence_mismatch"
    assert result["historical_comparison"] == []


def test_missing_artifact_is_not_a_successful_empty_briefing(briefing_repo: Path) -> None:
    (briefing_repo / SOURCES).unlink()
    with pytest.raises(FileNotFoundError):
        build_research_briefing(briefing_repo)


def test_corrupt_research_boundary_is_rejected(briefing_repo: Path) -> None:
    path = briefing_repo / READINESS
    report = json.loads(path.read_text())
    report["trade_ready"] = True
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="boundary"):
        build_research_briefing(briefing_repo)
