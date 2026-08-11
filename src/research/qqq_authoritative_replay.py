from __future__ import annotations

import math
import shutil
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import pandas as pd
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
from src.research.formal_model_replay import _compare_package_sections
from src.research.rules_formal_replay_gate import (
    CN_MODEL_ID,
    CN_REPLAY_LEDGER_NAME,
    CN_WINDOW,
    RulesFormalReplayError,
    verify_cn_current_allocation_replay,
)
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison

QQQ_REFERENCE_CONTRACT = Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml")
QQQ_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)

# These are the fields that determine the accepted QQQ economic/decision path.
# `bench_tqqq` is a diagnostic comparison series, not the formal benchmark or a
# portfolio input. Position `price` is a displayed source observation; portfolio
# economics are carried by the retained return/account/cost trace below and the
# governed source identity is bound separately by manifest/reconciliation hashes.
QQQ_REPORT_FIELDS = (
    "date",
    "account",
    "bench_qqq",
    "bench",
    "turnover",
    "period_return",
    "gross_return",
    "transaction_cost",
    "position_state",
    "position_label",
    "decision_state",
    "decision_reason",
    "executed_reason",
    "drawdown",
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
    expected_projection = {
        "portfolio_contract": expected.get("portfolio_contract"),
        "report": _project_rows(expected.get("report"), QQQ_REPORT_FIELDS, label="report"),
        "positions": _project_rows(
            expected.get("positions"), QQQ_POSITION_FIELDS, label="positions"
        ),
        "trades": expected.get("trades"),
    }
    observed_projection = {
        "portfolio_contract": observed.get("portfolio_contract"),
        "report": _project_rows(observed.get("report"), QQQ_REPORT_FIELDS, label="report"),
        "positions": _project_rows(
            observed.get("positions"), QQQ_POSITION_FIELDS, label="positions"
        ),
        "trades": observed.get("trades"),
    }
    comparison = _compare_package_sections(expected_projection, observed_projection)
    comparison["authority"] = {
        "report_fields": list(QQQ_REPORT_FIELDS),
        "position_fields": list(QQQ_POSITION_FIELDS),
        "trade_fields": "all_retained_fields",
        "non_authoritative_observation_fields": ["report.bench_tqqq", "positions.price"],
        "source_identity_bound_separately": True,
    }
    return comparison


def verify_qqq_authoritative_replay(
    repository_root: str | Path,
    *,
    package_path: str | Path,
    bundle_dir: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    package_file = Path(package_path).resolve()
    expected = load_object(package_file)
    if expected.get("model_id") != QQQ_MODEL_ID:
        raise RulesFormalReplayError("QQQ replay requires the accepted v4.3 package")
    cutoff = str(expected.get("evidence_cutoff") or "")
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
            generated_at=str(expected.get("generated_at") or "credentialed-replay"),
            evidence_cutoff=cutoff,
            backtest_id=str(expected.get("backtest_id") or f"{QQQ_MODEL_ID}-replay"),
            evidence={
                "replay_gate": "qqq_authoritative_replay_v1",
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
    comparison = compare_qqq_authoritative_trace(expected, observed)
    if not comparison["exact"]:
        raise RulesFormalReplayError(
            "QQQ Rotation v4.3 authoritative replay mismatch: "
            + str(comparison)
        )

    manifest = bundle / "bundle_manifest.json"
    reconciliation = bundle / "reconciliation.csv"
    coverage_path = bundle / "coverage.csv"
    for path in (manifest, reconciliation, coverage_path):
        if not path.is_file():
            raise RulesFormalReplayError(f"QQQ governed replay evidence missing: {path.name}")

    return {
        "schema_version": "1.0",
        "model_id": QQQ_MODEL_ID,
        "decision": "exact_replay",
        "trace_reproduction": comparison,
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
        "schema_version": "active_rules_replay_v1",
        "decision": "exact_replay",
        "models": {
            QQQ_MODEL_ID: qqq_replay,
            CN_MODEL_ID: cn_replay,
        },
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
