from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.promote_cn_x1_1_formal import build_package as build_cn_frozen_package
from scripts.run_cn_x1_1_sector_breadth import load_ledgers
from src.artifacts.formal_refresh import load_object, sha256
from src.artifacts.qqq_v4_3_formal import (
    JOINT_STRATEGY,
    MODEL_ID as QQQ_MODEL_ID,
    build_formal_package as build_qqq_package,
)
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    run_regime_portfolio,
)
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.formal_model_replay import _compare_package_sections, _compare_row_lists
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison

CN_MODEL_ID = "cn_x1_1"
CN_FROZEN_EVIDENCE = Path("data/research/cn_x1_1_regime_gated_candidate_v1")
CN_WINDOW = "2026H2_PARTIAL"
QQQ_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)


class RulesFormalReplayError(ValueError):
    """Raised when an accepted rules-based economic path cannot be reproduced."""


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


def _raise_mismatch(label: str, comparison: Mapping[str, Any]) -> None:
    raise RulesFormalReplayError(
        f"{label} exact replay mismatch: "
        + json.dumps(comparison, ensure_ascii=False, sort_keys=True, default=str)
    )


def _prefix_package(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    prefix: dict[str, Any] = {
        "portfolio_contract": observed.get("portfolio_contract"),
    }
    for section in ("report", "positions", "trades"):
        expected_rows = expected.get(section)
        observed_rows = observed.get(section)
        if not isinstance(expected_rows, list) or not isinstance(observed_rows, list):
            prefix[section] = observed_rows
            continue
        prefix[section] = observed_rows[: len(expected_rows)]
    return prefix


def assert_exact_formal_prefix(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    comparison = _compare_package_sections(expected, _prefix_package(expected, observed))
    if not comparison["exact"]:
        _raise_mismatch(label, comparison)
    return comparison


def verify_cn_frozen_prefix(
    repository_root: str | Path,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    if package.get("model_id") != CN_MODEL_ID:
        raise RulesFormalReplayError("CN replay requires the accepted cn_x1_1 package")
    evidence_root = (root / CN_FROZEN_EVIDENCE).resolve()
    frozen = build_cn_frozen_package(
        evidence_root,
        generated_at=str(package.get("generated_at") or "frozen-replay"),
    )
    comparison = assert_exact_formal_prefix(
        frozen,
        package,
        label="CN x1.1 frozen incumbent prefix",
    )
    report = frozen.get("report")
    if not isinstance(report, list) or not report:
        raise RulesFormalReplayError("CN frozen formal report is empty")
    boundary = max(str(row["date"]) for row in report if isinstance(row, Mapping))
    return {
        "decision": "exact_replay",
        "boundary": boundary,
        "evidence_root": str(CN_FROZEN_EVIDENCE),
        "evidence_manifest_sha256": sha256(evidence_root / "evidence_manifest.json"),
        "trace_reproduction": comparison,
    }


def _weights_before(package: Mapping[str, Any], boundary: str) -> dict[str, float]:
    positions = package.get("positions")
    if not isinstance(positions, list):
        raise RulesFormalReplayError("CN formal positions are missing")
    eligible = [
        row
        for row in positions
        if isinstance(row, Mapping)
        and row.get("date")
        and str(row["date"]) < boundary
    ]
    if not eligible:
        return {}
    latest = max(str(row["date"]) for row in eligible)
    weights = {
        str(row["instrument"]): float(row["weight"])
        for row in eligible
        if str(row["date"]) == latest
    }
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise RulesFormalReplayError(
            f"CN formal pre-window weights do not sum to one on {latest}"
        )
    return weights


def _cn_report_rows(periods: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in periods.sort_values("datetime").to_dict("records"):
        risk_on = bool(row["risk_on"])
        rows.append(
            {
                "date": pd.Timestamp(row["datetime"]).date().isoformat(),
                "period_return": float(row["net_return"]),
                "gross_return": float(row["gross_return"]),
                "benchmark_return": float(row["benchmark_return"]),
                "relative_log_return": float(row["relative_log_return"]),
                "turnover": float(row["turnover"]),
                "transaction_cost": float(row["cost"]),
                "risk_on": risk_on,
                "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                "votes": int(row["votes"]),
                "long_trend": bool(row["long_trend"]),
                "medium_momentum": bool(row["medium_momentum"]),
                "cross_sectional_breadth": bool(row["cross_sectional_breadth"]),
                "breadth_value": float(row["breadth_value"]),
                "benchmark_hit": bool(row["benchmark_hit"]),
            }
        )
    return rows


def _cn_position_rows(
    periods: pd.DataFrame,
    holdings: pd.DataFrame,
) -> list[dict[str, Any]]:
    risk_by_date = {
        pd.Timestamp(row["datetime"]).date().isoformat(): bool(row["risk_on"])
        for row in periods.to_dict("records")
    }
    rows: list[dict[str, Any]] = []
    for row in holdings.to_dict("records"):
        date = pd.Timestamp(row["datetime"]).date().isoformat()
        score = row.get("score")
        rows.append(
            {
                "date": date,
                "instrument": str(row["instrument"]),
                "name": str(row["entity"]),
                "sector": str(row["sector"]),
                "weight": float(row["weight"]),
                "score": None if pd.isna(score) else float(score),
                "raw_return": float(row["raw_return"]),
                "benchmark_return": float(row["benchmark_return"]),
                "net_contribution": float(row["net_contribution"]),
                "precision_hit": bool(row["precision_hit"]),
                "risk_state": (
                    "risk_on" if risk_by_date[date] else "risk_off_csi300_fallback"
                ),
            }
        )
    return sorted(rows, key=lambda row: (row["date"], row["instrument"]))


def _project_fields(
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    return [{field: row.get(field) for field in fields} for row in rows]


def verify_cn_current_allocation_replay(
    repository_root: str | Path,
    *,
    package_path: str | Path,
    provider_dir: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    package_file = Path(package_path).resolve()
    package = load_object(package_file)
    frozen = verify_cn_frozen_prefix(root, package)

    spec = RegimeGateSpec()
    universe = yaml.safe_load(
        (root / "configs/research_universes/cn_selected_equities_v3.yaml").read_text(
            encoding="utf-8"
        )
    )
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise RulesFormalReplayError("CN130 universe identity is not exact")

    ledger_file = Path(ledger_path).resolve()
    ledger, _ = load_ledgers([ledger_file.parent], (CN_WINDOW,))
    panel = load_provider_panel(
        Path(provider_dir).resolve(),
        [*symbols, spec.benchmark],
        fields=("close",),
    )
    close = panel.fields["close"]
    state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=spec.benchmark,
        long_ma_sessions=spec.long_ma_sessions,
        momentum_sessions=spec.momentum_sessions,
        breadth_ma_sessions=spec.breadth_ma_sessions,
        breadth_threshold=spec.breadth_threshold,
    )
    benchmark_returns = forward_returns(
        close[[spec.benchmark]],
        horizon=spec.horizon_sessions,
        delay=spec.execution_delay_sessions,
    )[spec.benchmark]
    _, periods, holdings, _ = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=(CN_WINDOW,),
        variant=spec.variant(),
        rule="two_of_three",
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        initial_weights=_weights_before(package, "2026-07-01"),
    )

    computed_report = _cn_report_rows(periods)
    computed_dates = {row["date"] for row in computed_report}
    accepted_report = [
        row
        for row in package.get("report", [])
        if isinstance(row, Mapping)
        and str(row.get("date") or "") in computed_dates
    ]
    report_fields = (
        "date",
        "period_return",
        "gross_return",
        "benchmark_return",
        "relative_log_return",
        "turnover",
        "transaction_cost",
        "risk_on",
        "risk_state",
        "votes",
        "long_trend",
        "medium_momentum",
        "cross_sectional_breadth",
        "breadth_value",
        "benchmark_hit",
    )
    report_expected = _project_fields(accepted_report, report_fields)
    report_observed = _project_fields(
        [row for row in computed_report if row["date"] in {x["date"] for x in report_expected}],
        report_fields,
    )
    report_comparison = _compare_row_lists(report_expected, report_observed)
    if not report_comparison["exact"]:
        _raise_mismatch("CN x1.1 current allocation report", report_comparison)

    computed_positions = _cn_position_rows(periods, holdings)
    accepted_dates = {row["date"] for row in report_expected}
    accepted_positions = sorted(
        [
            row
            for row in package.get("positions", [])
            if isinstance(row, Mapping) and str(row.get("date") or "") in accepted_dates
        ],
        key=lambda row: (str(row.get("date")), str(row.get("instrument"))),
    )
    position_fields = (
        "date",
        "instrument",
        "name",
        "sector",
        "weight",
        "score",
        "raw_return",
        "benchmark_return",
        "net_contribution",
        "precision_hit",
        "risk_state",
    )
    position_expected = _project_fields(accepted_positions, position_fields)
    position_observed = _project_fields(
        [row for row in computed_positions if row["date"] in accepted_dates],
        position_fields,
    )
    position_comparison = _compare_row_lists(position_expected, position_observed)
    if not position_comparison["exact"]:
        _raise_mismatch("CN x1.1 current allocation positions", position_comparison)

    if not report_expected:
        raise RulesFormalReplayError(
            "CN current governed ledger has no overlap with accepted settled formal trace"
        )

    return {
        "schema_version": "1.0",
        "model_id": CN_MODEL_ID,
        "decision": "exact_replay",
        "frozen_prefix": frozen,
        "current_allocation": {
            "accepted_overlap_periods": len(report_expected),
            "report": report_comparison,
            "positions": position_comparison,
            "ledger_sha256": sha256(ledger_file),
            "provider_calendar_start": pd.Timestamp(close.index.min()).date().isoformat(),
            "provider_calendar_end": pd.Timestamp(close.index.max()).date().isoformat(),
            "continuation_state_source": "accepted_formal_positions_before_2026_07_01",
        },
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }


def verify_qqq_professional_replay(
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
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"],
        start=str(contract["data"]["start_date"]),
        end=cutoff,
        bundle_dir=Path(bundle_dir).resolve(),
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
                "replay_gate": "rules_formal_replay_gate_v1",
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
    comparison = _compare_package_sections(expected, observed)
    if not comparison["exact"]:
        _raise_mismatch("QQQ Rotation v4.3 professional replay", comparison)
    return {
        "schema_version": "1.0",
        "model_id": QQQ_MODEL_ID,
        "decision": "exact_replay",
        "trace_reproduction": comparison,
        "data_identity": data_identity,
        "coverage_rows": int(len(coverage)),
        "retrospective_diagnostics_present": bool(diagnostics),
        "bundle_manifest_sha256": sha256(Path(bundle_dir).resolve() / "bundle_manifest.json"),
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
