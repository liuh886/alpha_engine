from __future__ import annotations

import math
import shutil
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import yaml

from scripts.run_cn130_ranking_batch import run as run_cn_ranking_batch
from src.artifacts.formal_refresh import load_object, sha256
from src.artifacts.qqq_v4_3_formal import (
    ASSETS,
    JOINT_STRATEGY,
    MODEL_ID as QQQ_MODEL_ID,
    build_formal_package as build_qqq_package,
)
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.data.etf_reference_bundle import build_etf_reference_bundle
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.replay_comparison import compare_package_sections, compare_row_lists
from src.research.rules_formal_replay_gate import (
    CN_MODEL_ID,
    CN_REPLAY_LEDGER_NAME,
    CN_WINDOW,
    RulesFormalReplayError,
    assert_exact_formal_prefix,
    verify_cn_current_allocation_replay,
)
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison

QQQ_REFERENCE_CONTRACT = Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml")
QQQ_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
QQQ_FORMAL_ROOT = Path("data/research/formal_backtests")
QQQ_FORMAL_CATALOG = QQQ_FORMAL_ROOT / "catalog.json"

# Historical economic rows are immutable accepted evidence. A current provider
# snapshot is authoritative for reproducing the strategy decision path and for
# economics of newly appended rows, but it must not rewrite the accepted past
# when the upstream provider restates historical adjusted prices by tiny amounts.
QQQ_DECISION_REPORT_FIELDS = (
    "date",
    "turnover",
    "transaction_cost",
    "position_state",
    "position_label",
    "decision_state",
    "decision_reason",
    "executed_reason",
    "trace_frequency",
    "panic_repair_active",
    "slow_bear_defense_active",
    *(f"weight_{asset}" for asset in ASSETS),
)
QQQ_POSITION_FIELDS = (
    "date",
    "instrument",
    "weight",
    "position_state",
    "position_label",
    "executed_reason",
    "panic_repair_active",
    "slow_bear_defense_active",
)
QQQ_TRADE_FIELDS = (
    "date",
    "instrument",
    "action",
    "previous_weight",
    "target_weight",
    "weight_delta",
    "transaction_cost",
    "reason",
    "position_state",
    "position_label",
    "vix_regime",
    "vxn_regime",
)
QQQ_APPENDED_ECONOMIC_FIELDS = (
    "date",
    "bench",
    "turnover",
    "period_return",
    "gross_return",
    "transaction_cost",
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _project_rows(
    rows: object,
    fields: Sequence[str],
    *,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise RulesFormalReplayError(f"QQQ {label} trace is missing")
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RulesFormalReplayError(f"QQQ {label}[{index}] is not a mapping")
        missing = [field for field in fields if field not in row]
        if missing:
            raise RulesFormalReplayError(
                f"QQQ {label}[{index}] missing authoritative fields: {missing}"
            )
        projected.append({field: row[field] for field in fields})
    return projected


def compare_qqq_authoritative_trace(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare current-source strategy identity, not frozen historical economics."""

    expected_projection = {
        "portfolio_contract": expected.get("portfolio_contract"),
        "report": _project_rows(
            expected.get("report"), QQQ_DECISION_REPORT_FIELDS, label="report"
        ),
        "positions": _project_rows(
            expected.get("positions"), QQQ_POSITION_FIELDS, label="positions"
        ),
        "trades": _project_rows(
            expected.get("trades"), QQQ_TRADE_FIELDS, label="trades"
        ),
    }
    observed_projection = {
        "portfolio_contract": observed.get("portfolio_contract"),
        "report": _project_rows(
            observed.get("report"), QQQ_DECISION_REPORT_FIELDS, label="report"
        ),
        "positions": _project_rows(
            observed.get("positions"), QQQ_POSITION_FIELDS, label="positions"
        ),
        "trades": _project_rows(
            observed.get("trades"), QQQ_TRADE_FIELDS, label="trades"
        ),
    }
    comparison = compare_package_sections(expected_projection, observed_projection)
    comparison["authority"] = {
        "historical_economic_authority": "accepted_formal_prefix",
        "current_source_authority": "decision_path_and_newly_appended_economics",
        "report_fields": list(QQQ_DECISION_REPORT_FIELDS),
        "position_fields": list(QQQ_POSITION_FIELDS),
        "trade_fields": list(QQQ_TRADE_FIELDS),
        "non_authoritative_current_observation_fields": [
            "report.account",
            "report.bench_qqq",
            "report.bench_tqqq",
            "report.bench",
            "report.period_return",
            "report.gross_return",
            "report.drawdown",
            "positions.price",
            "trades.vix_close",
            "trades.vxn_close",
        ],
        "source_identity_bound_separately": True,
    }
    return comparison


def _accepted_qqq_reference(root: Path) -> tuple[dict[str, Any], Path, str]:
    formal_root = (root / QQQ_FORMAL_ROOT).resolve()
    catalog_path = (root / QQQ_FORMAL_CATALOG).resolve()
    catalog = load_object(catalog_path)
    records = catalog.get("records")
    if not isinstance(records, list):
        raise RulesFormalReplayError("QQQ formal catalog records are missing")
    matches = [
        row
        for row in records
        if isinstance(row, Mapping) and row.get("model_id") == QQQ_MODEL_ID
    ]
    if len(matches) != 1:
        raise RulesFormalReplayError(
            f"expected one accepted QQQ formal catalog row, found {len(matches)}"
        )
    record = matches[0]
    if record.get("publication_status") != "accepted_formal_baseline":
        raise RulesFormalReplayError("QQQ formal catalog row is not accepted")
    package_path = (formal_root / str(record.get("path") or "")).resolve()
    package_path.relative_to(formal_root)
    if not package_path.is_file():
        raise RulesFormalReplayError("accepted QQQ formal package is missing")
    digest = sha256(package_path)
    if digest != str(record.get("sha256") or ""):
        raise RulesFormalReplayError("accepted QQQ formal catalog hash mismatch")
    package = load_object(package_path)
    if package.get("model_id") != QQQ_MODEL_ID:
        raise RulesFormalReplayError("accepted QQQ formal package identity mismatch")
    return package, package_path, digest


def _report_boundary(package: Mapping[str, Any]) -> str:
    report = package.get("report")
    if not isinstance(report, list) or not report:
        raise RulesFormalReplayError("QQQ formal report is empty")
    dates = [
        str(row["date"])
        for row in report
        if isinstance(row, Mapping) and row.get("date")
    ]
    if not dates:
        raise RulesFormalReplayError("QQQ formal report has no dated rows")
    return max(dates)


def _appended_economic_replay(
    accepted: Mapping[str, Any],
    candidate: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    boundary = _report_boundary(accepted)
    candidate_rows = [
        row
        for row in candidate.get("report", [])
        if isinstance(row, Mapping) and str(row.get("date") or "") > boundary
    ]
    if not candidate_rows:
        return {
            "exact": True,
            "status": "not_applicable_no_appended_rows",
            "boundary": boundary,
            "rows": 0,
        }
    observed_by_date = {
        str(row.get("date")): row
        for row in observed.get("report", [])
        if isinstance(row, Mapping) and row.get("date")
    }
    observed_rows: list[Mapping[str, Any]] = []
    for row in candidate_rows:
        date = str(row["date"])
        source = observed_by_date.get(date)
        if source is None:
            raise RulesFormalReplayError(
                f"QQQ appended economic source row is missing: {date}"
            )
        observed_rows.append(source)
    expected_projection = _project_rows(
        candidate_rows,
        QQQ_APPENDED_ECONOMIC_FIELDS,
        label="appended report",
    )
    observed_projection = _project_rows(
        observed_rows,
        QQQ_APPENDED_ECONOMIC_FIELDS,
        label="source appended report",
    )
    comparison = compare_row_lists(expected_projection, observed_projection)
    comparison["status"] = "exact_recomputed_appended_economics"
    comparison["boundary"] = boundary
    return comparison


def _verify_cumulative_continuity(
    accepted: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    boundary = _report_boundary(accepted)
    accepted_report = [
        row for row in accepted.get("report", []) if isinstance(row, Mapping)
    ]
    accepted_boundary = next(
        row for row in accepted_report if str(row.get("date")) == boundary
    )
    appended = sorted(
        [
            row
            for row in candidate.get("report", [])
            if isinstance(row, Mapping) and str(row.get("date") or "") > boundary
        ],
        key=lambda row: str(row["date"]),
    )
    if not appended:
        return {
            "exact": True,
            "status": "not_applicable_no_appended_rows",
            "boundary": boundary,
            "rows": 0,
        }

    account = float(accepted_boundary["account"])
    benchmark = float(accepted_boundary["bench_qqq"])
    peak = max(float(row["account"]) for row in accepted_report)
    for row in appended:
        date = str(row["date"])
        account *= 1.0 + float(row["period_return"])
        benchmark *= 1.0 + float(row["bench"])
        peak = max(peak, account)
        drawdown = account / peak - 1.0
        checks = {
            "account": (account, float(row["account"])),
            "bench_qqq": (benchmark, float(row["bench_qqq"])),
            "drawdown": (drawdown, float(row["drawdown"])),
        }
        for field, (expected_value, observed_value) in checks.items():
            if not math.isclose(
                expected_value,
                observed_value,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                return {
                    "exact": False,
                    "status": "cumulative_continuity_mismatch",
                    "boundary": boundary,
                    "date": date,
                    "field": field,
                    "expected": expected_value,
                    "observed": observed_value,
                }
    return {
        "exact": True,
        "status": "exact_frozen_prefix_continuation",
        "boundary": boundary,
        "rows": len(appended),
    }


def verify_qqq_authoritative_replay(
    repository_root: str | Path,
    *,
    package_path: str | Path,
    bundle_dir: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    package_file = Path(package_path).resolve()
    candidate = load_object(package_file)
    if candidate.get("model_id") != QQQ_MODEL_ID:
        raise RulesFormalReplayError("QQQ replay requires the accepted v4.3 model family")

    accepted, accepted_path, accepted_sha = _accepted_qqq_reference(root)
    frozen_prefix = assert_exact_formal_prefix(
        accepted,
        candidate,
        label="QQQ Rotation v4.3 frozen economic prefix",
    )

    cutoff = str(candidate.get("evidence_cutoff") or "")
    if not cutoff:
        raise RulesFormalReplayError("QQQ formal package has no evidence cutoff")

    contract_path = (root / QQQ_BRIDGE_CONTRACT).resolve()
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    bundle = Path(bundle_dir).resolve()
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"],
        start=str(contract["data"]["start_date"]),
        end=cutoff,
        bundle_dir=bundle,
    )
    if data_identity.get("professional_source_ready") is not True:
        raise RulesFormalReplayError(
            "QQQ exact replay requires a professional governed ETF bundle"
        )

    fear_greed = fetch_cnn_fear_greed(end_date=cutoff)
    _, results, diagnostics = run_v4_33_comparison(
        bars,
        contract,
        fear_greed,
        cash_symbol="SGOV",
    )
    observed = _json_safe(
        build_qqq_package(
            results[JOINT_STRATEGY],
            bars,
            generated_at=str(candidate.get("generated_at") or "credentialed-replay"),
            evidence_cutoff=cutoff,
            backtest_id=str(candidate.get("backtest_id") or f"{QQQ_MODEL_ID}-replay"),
            evidence={
                "replay_gate": "qqq_authoritative_replay_v2",
                "model_selection_reopened": False,
            },
            freshness={
                "status": "replay",
                "required_cutoff": cutoff,
                "model_selection_reopened": False,
                "research_only": True,
                "trade_ready": False,
            },
        )
    )

    decision_replay = compare_qqq_authoritative_trace(candidate, observed)
    if not decision_replay["exact"]:
        raise RulesFormalReplayError(
            "QQQ Rotation v4.3 decision replay mismatch: " + str(decision_replay)
        )
    appended_economics = _appended_economic_replay(accepted, candidate, observed)
    if not appended_economics["exact"]:
        raise RulesFormalReplayError(
            "QQQ Rotation v4.3 appended economic replay mismatch: "
            + str(appended_economics)
        )
    continuity = _verify_cumulative_continuity(accepted, candidate)
    if not continuity["exact"]:
        raise RulesFormalReplayError(
            "QQQ Rotation v4.3 cumulative continuation mismatch: " + str(continuity)
        )

    manifest = bundle / "bundle_manifest.json"
    reconciliation = bundle / "reconciliation.csv"
    coverage_path = bundle / "coverage.csv"
    for path in (manifest, reconciliation, coverage_path):
        if not path.is_file():
            raise RulesFormalReplayError(f"QQQ governed replay evidence missing: {path.name}")

    return {
        "schema_version": "2.0",
        "model_id": QQQ_MODEL_ID,
        "decision": "exact_replay",
        "trace_reproduction": {
            "exact": True,
            "frozen_economic_prefix": frozen_prefix,
            "current_source_decision_path": decision_replay,
            "appended_economics": appended_economics,
            "cumulative_continuity": continuity,
        },
        "frozen_economic_identity": {
            "mode": "accepted_formal_prefix_retained_exact",
            "accepted_package_path": str(accepted_path.relative_to(root)),
            "accepted_package_sha256": accepted_sha,
            "historical_economics_recomputed_from_current_provider": False,
        },
        "historical_challenger_policy": (
            "prospective_window_or_immutable_original_source_snapshot_required"
        ),
        "data_identity": data_identity,
        "coverage_rows": int(len(coverage)),
        "retrospective_diagnostics_present": bool(diagnostics),
        "source_evidence": {
            "bundle_manifest_sha256": sha256(manifest),
            "reconciliation_sha256": sha256(reconciliation),
            "coverage_sha256": sha256(coverage_path),
            "professional_source_ready": True,
        },
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }


def prepare_and_verify_active_rules_replay(
    repository_root: str | Path,
    *,
    formal_root: str | Path,
    cn_provider_dir: str | Path,
    qqq_bundle_dir: str | Path,
    cn_replay_output_dir: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    formal = Path(formal_root).resolve()
    qqq_bundle = Path(qqq_bundle_dir).resolve()
    cn_output = Path(cn_replay_output_dir).resolve()

    qqq_package = formal / f"{QQQ_MODEL_ID}.json"
    cn_package = formal / f"{CN_MODEL_ID}.json"
    if not qqq_package.is_file() or not cn_package.is_file():
        raise RulesFormalReplayError(
            "active formal QQQ/CN packages are required before replay planning"
        )

    qqq_cutoff = str(load_object(qqq_package).get("evidence_cutoff") or "")
    if not qqq_cutoff:
        raise RulesFormalReplayError("active QQQ package has no evidence cutoff")
    if qqq_bundle.exists():
        shutil.rmtree(qqq_bundle)
    qqq_manifest = build_etf_reference_bundle(
        contract_path=(root / QQQ_REFERENCE_CONTRACT).resolve(),
        output_root=qqq_bundle,
        end=qqq_cutoff,
    )
    if qqq_manifest.get("strategy_data_ready") is not True:
        raise RulesFormalReplayError("QQQ governed ETF replay bundle is not strategy-ready")
    if qqq_manifest.get("professional_source_ready") is not True:
        raise RulesFormalReplayError(
            "QQQ governed ETF replay bundle is not professionally reconciled"
        )
    qqq_replay = verify_qqq_authoritative_replay(
        root,
        package_path=qqq_package,
        bundle_dir=qqq_bundle,
    )

    if cn_output.exists():
        shutil.rmtree(cn_output)
    run_cn_ranking_batch(
        root,
        Path(cn_provider_dir).resolve(),
        cn_output,
        CN_WINDOW,
        "r0r1",
    )
    cn_ledger = cn_output / "score_ledgers" / CN_REPLAY_LEDGER_NAME
    if not cn_ledger.is_file():
        raise RulesFormalReplayError(f"CN replay ledger is missing: {cn_ledger}")
    cn_replay = verify_cn_current_allocation_replay(
        root,
        package_path=cn_package,
        provider_dir=cn_provider_dir,
        ledger_path=cn_ledger,
    )

    return {
        "schema_version": "active_rules_replay_v2",
        "decision": "exact_replay",
        "models": {
            QQQ_MODEL_ID: qqq_replay,
            CN_MODEL_ID: cn_replay,
        },
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
