"""Publish CN x1.1 formal v1 and Model Run Bundle v2 artifacts."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes, validate_catalog
from src.artifacts.model_run_exporter import (
    RunExportPlan,
    SectionPlan,
    catalog_record,
    export_model_run,
)
from src.research.cn_x1_1_formal_evidence import FormalEvidence, clean


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(clean(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(canonical_json_bytes(clean(value)))


def _metric(
    metric_id: str,
    value: float,
    unit: str,
    direction: str,
    sample_count: int,
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "value": value,
        "unit": unit,
        "direction": direction,
        "estimator": "retained_formal_cn_x1_1",
        "annualization": (
            "non_overlapping_10_session_252_day"
            if metric_id
            in {
                "annualized_return",
                "annualized_volatility",
                "sharpe_ratio",
                "information_ratio",
            }
            else None
        ),
        "sample_count": sample_count,
        "scope": "accepted_formal_full_frozen_interval",
        "availability_status": "available",
        "unavailable_reason": None,
    }


def _summary_metrics(evidence: FormalEvidence) -> list[dict[str, Any]]:
    raw = evidence.package["metrics"]
    count = len(evidence.periods)
    aliases = (
        ("total_return", "Total Return", "ratio", "higher_is_better"),
        ("annualized_return", "Annualized Return", "ratio", "higher_is_better"),
        ("benchmark_return", "Benchmark Return", "ratio", "descriptive"),
        (
            "excess_return",
            "Compounded Relative Excess Return",
            "ratio",
            "higher_is_better",
        ),
        (
            "annualized_volatility",
            "Annualized Volatility",
            "ratio",
            "lower_is_better",
        ),
        ("sharpe_ratio", "Sharpe Ratio", "decimal", "higher_is_better"),
        (
            "information_ratio",
            "Information Ratio",
            "decimal",
            "higher_is_better",
        ),
        ("max_drawdown", "Max Drawdown", "ratio", "higher_is_better"),
        ("turnover", "Turnover", "ratio", "lower_is_better"),
        (
            "transaction_cost",
            "Transaction Cost",
            "ratio",
            "lower_is_better",
        ),
    )
    rows = [
        _metric(metric_id, float(raw[label]), unit, direction, count)
        for metric_id, label, unit, direction in aliases
    ]
    for metric_id in ("ic", "rank_ic", "icir"):
        rows.append(
            {
                "metric_id": metric_id,
                "value": None,
                "unit": "decimal",
                "direction": "higher_is_better",
                "estimator": None,
                "annualization": None,
                "sample_count": None,
                "scope": "accepted_formal_full_frozen_interval",
                "availability_status": "not_retained",
                "unavailable_reason": (
                    "The promoted portfolio conversion does not recompute "
                    "cross-sectional prediction metrics."
                ),
            }
        )
    return rows


def _v2_plan(evidence: FormalEvidence, source_dir: Path) -> RunExportPlan:
    package = evidence.package
    metrics = _summary_metrics(evidence)
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": "cn_ranker",
        "model_version_id": "cn_x1_1",
        "run_id": "cn_x1_1_through_2026_08_03",
        "display_name": "CN x1.1",
        "market": "cn",
        "benchmark": "000300",
        "metrics": metrics,
        "evidence_completeness": package["evidence_completeness"],
        "source_package_sha256": hashlib.sha256(
            canonical_json_bytes(package)
        ).hexdigest(),
        "research_only": True,
        "trade_ready": False,
    }
    performance = {
        "schema_version": "2.0.0",
        "report": package["report"],
        "date_range": package["date_range"],
        "benchmark": "000300",
        "trace_frequency": package["trace_frequency"],
        "segment_contract": {
            "historical": "2022H2-2025H2",
            "reporting_only": ["2026H1", "2026H2_PARTIAL"],
            "evaluation_resets_at_reporting_boundary": True,
        },
        "research_only": True,
        "trade_ready": False,
    }
    risk = {
        "schema_version": "2.0.0",
        "metrics": [
            row
            for row in metrics
            if row["metric_id"]
            in {
                "annualized_volatility",
                "max_drawdown",
                "turnover",
                "transaction_cost",
            }
        ],
        "state_summary": package["state_summary"],
        "research_only": True,
        "trade_ready": False,
    }
    robustness = {
        "schema_version": "2.0.0",
        "window_summary": package["window_summary"],
        "candidate_decision": package["evidence"]["candidate_decision"],
        "research_only": True,
        "trade_ready": False,
    }
    portfolio = {
        "schema_version": "2.0.0",
        "portfolio_contract": package["portfolio_contract"],
        "positions": package["positions"],
        "research_only": True,
        "trade_ready": False,
    }
    trades = {
        "schema_version": "2.0.0",
        "derivation": "consecutive_exact_target_weights_with_cash_aware_turnover",
        "rows": package["trades"],
        "research_only": True,
        "trade_ready": False,
    }
    attribution = {
        "schema_version": "2.0.0",
        "rows": package["attribution"],
        "semantics": "position_net_contribution_and_deterministic_aggregates",
        "research_only": True,
        "trade_ready": False,
    }
    diagnostics = {
        "schema_version": "2.0.0",
        "interpretation_notes": package["interpretation_notes"],
        "evidence_completeness": package["evidence_completeness"],
        "research_only": True,
        "trade_ready": False,
    }
    lineage = {
        "schema_version": "2.0.0",
        "adapter": "cn_x1_1_formal_promotion_v1",
        "source_artifact": package["evidence"],
        "source_candidate_decision_sha256": _sha(source_dir / "decision.json"),
        "source_rebalance_sha256": _sha(source_dir / "rebalance_periods.csv"),
        "source_holdings_sha256": _sha(source_dir / "holdings.csv"),
        "historical_evidence_recomputed": False,
        "model_selection_reopened": False,
        "parent_model_version_id": "cn_x1_0",
        "supersedes_model_version_id": "cn_x1_0",
        "research_only": True,
        "trade_ready": False,
    }
    sections = tuple(
        SectionPlan(
            name,
            "available",
            name
            in {
                "summary",
                "performance",
                "robustness",
                "portfolio",
                "lineage",
            },
            payload,
        )
        for name, payload in (
            ("summary", summary),
            ("performance", performance),
            ("risk", risk),
            ("robustness", robustness),
            ("portfolio", portfolio),
            ("trades", trades),
            ("attribution", attribution),
            ("diagnostics", diagnostics),
            ("lineage", lineage),
        )
    ) + (
        SectionPlan(
            "decision",
            "not_retained",
            False,
            reason=(
                "The formal promotion decision remains a companion receipt "
                "bound to the source artifact."
            ),
        ),
    )
    return RunExportPlan(
        model_family_id="cn_ranker",
        model_version_id="cn_x1_1",
        run_id="cn_x1_1_through_2026_08_03",
        model_kind="cross_sectional_ranker",
        publication_channel="formal",
        publication_status="accepted_formal_baseline",
        generated_at="2026-08-05T17:20:00Z",
        evidence_cutoff="2026-08-03",
        comparability_key={
            "market": "cn",
            "universe_id": "cn_selected_equities_v3",
            "benchmark_id": "000300",
            "start": "2022-07-01",
            "end": "2026-08-03",
            "trace_frequency": "non_overlapping_10_session",
            "horizon": "10_sessions",
            "rebalance_contract_id": "rebalance_10_sessions",
            "cost_contract_id": "cost_20_bps",
        },
        sections=sections,
        research_only=True,
        trade_ready=False,
    )


def _write_ledgers(output_root: Path, evidence: FormalEvidence) -> None:
    target = output_root / "data/research/formal_backtests/cn_x1_1_ledgers"
    target.mkdir(parents=True, exist_ok=True)
    periods = evidence.periods.copy()
    periods["datetime"] = periods["datetime"].dt.strftime("%Y-%m-%d")
    holdings = evidence.holdings.copy()
    holdings["datetime"] = holdings["datetime"].dt.strftime("%Y-%m-%d")
    periods.to_csv(
        target / "rebalance_periods.csv",
        index=False,
        float_format="%.10g",
        lineterminator="\n",
    )
    holdings.to_csv(
        target / "holdings.csv",
        index=False,
        float_format="%.10g",
        lineterminator="\n",
    )
    evidence.trades.to_csv(
        target / "trades.csv",
        index=False,
        float_format="%.10g",
        lineterminator="\n",
    )
    pd.DataFrame(evidence.attribution).to_csv(
        target / "attribution.csv",
        index=False,
        float_format="%.10g",
        lineterminator="\n",
    )


def _v1_catalog(
    repository_root: Path,
    output_root: Path,
    package_path: Path,
) -> None:
    catalog = json.loads(
        (repository_root / "data/research/formal_backtests/catalog.json").read_text(
            encoding="utf-8"
        )
    )
    records = [
        row
        for row in catalog["records"]
        if row["model_id"] not in {"cn_x1_0", "cn_x1_1"}
    ]
    records.append(
        {
            "display_name": "CN x1.1",
            "display_order": 3,
            "model_id": "cn_x1_1",
            "path": "cn_x1_1.json",
            "publication_status": "accepted_formal_baseline",
            "sha256": _sha(package_path),
        }
    )
    catalog["published_at"] = "2026-08-05T17:20:00Z"
    catalog["records"] = sorted(records, key=lambda row: row["display_order"])
    _write_json(output_root / "data/research/formal_backtests/catalog.json", catalog)


def _v2_catalog(
    repository_root: Path,
    output_root: Path,
    manifest_path: Path,
) -> None:
    existing = json.loads(
        (repository_root / "data/research/formal_model_runs/catalog.json").read_text(
            encoding="utf-8"
        )
    )
    records = [
        row for row in existing["records"] if row["model_family_id"] != "cn_ranker"
    ]
    records.append(
        catalog_record(
            manifest_path,
            catalog_path=output_root / "data/research/formal_model_runs/catalog.json",
        )
    )
    catalog = {
        "schema_version": "2.0.0",
        "channel": "formal",
        "generated_at": "2026-08-05T17:20:00Z",
        "research_only": True,
        "trade_ready": False,
        "records": sorted(
            records,
            key=lambda row: (
                row["model_family_id"],
                row["model_version_id"],
                row["run_id"],
            ),
        ),
    }
    validate_catalog(catalog)
    _write_json(output_root / "data/research/formal_model_runs/catalog.json", catalog)


def _write_model_config(output_root: Path, evidence: FormalEvidence) -> None:
    metrics = evidence.package["metrics"]
    provider = evidence.source_objects["manifest.json"]["provider_identity_sha256"]
    value = {
        "schema_version": "1.1",
        "model_id": "cn_x1_1",
        "display_name": "CN x1.1",
        "release_date": "2026-08-06",
        "status": "accepted_formal_baseline",
        "research_only": True,
        "trade_ready": False,
        "market": "cn",
        "benchmark": "000300",
        "objective": (
            "Govern CN130 with a PIT regime gate over the frozen CN x1.0 R0 score."
        ),
        "lineage": {
            "parent": "cn_x1_0",
            "source_candidate_pr": 576,
            "promotion_issue": 577,
            "supersedes_named_model": "cn_x1_0",
        },
        "universe": {
            "universe_id": "cn_selected_equities_v3",
            "source": "configs/research_universes/cn_selected_equities_v3.yaml",
            "declared_candidate_count": 130,
            "membership_mode": "static_curated",
            "survivorship_bias": True,
        },
        "provider_binding": {
            "canonical_provider_artifact_id": 8850463785,
            "canonical_provider_identity_sha256": provider,
            "cutoff": "2026-08-03",
        },
        "score_source": {
            "model_id": "cn_x1_0",
            "ranking_id": "r0_cn_x1_0_raw_return_rank",
            "feature_family": "current_cn_ohlcv",
        },
        "portfolio": evidence.package["portfolio_contract"],
        "formal_backtest": {
            "start": "2022-07-01",
            "end": "2026-08-03",
            "package": "data/research/formal_backtests/cn_x1_1.json",
            "run_bundle": (
                "data/research/formal_model_runs/cn_ranker/cn_x1_1/"
                "cn_x1_1_through_2026_08_03/manifest.json"
            ),
            "rebalance_periods": 102,
            "position_rows": 252,
            "evidence_status": "complete",
            "total_return": metrics["Total Return"],
            "benchmark_return": metrics["Benchmark Return"],
            "compounded_relative_excess_return": metrics[
                "Compounded Relative Excess Return"
            ],
            "max_drawdown": metrics["Max Drawdown"],
            "historical_2022H2_2025H2_relative_excess": 0.5493370449,
            "reporting_2026_relative_excess": 0.0277002864,
        },
        "evidence_identity": {
            "workflow_run_id": 31022910416,
            "artifact_id": 8937409026,
            "artifact_digest": (
                "sha256:e540e400dbefd5178122444e709182323f1b363a3c41496fd8212e5095ee5a4b"
            ),
        },
        "known_limitations": [
            "Static curated CN130 membership carries survivorship bias.",
            "The authorized frozen score-ledger interval begins on 2022-07-01.",
            "2026 windows are reporting-only.",
            "The formal research baseline does not authorize automated trading.",
        ],
    }
    path = output_root / "configs/models/cn_x1_1.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_release(output_root: Path) -> None:
    value = {
        "schema_version": "1.0.0",
        "model_id": "cn_x1_1",
        "package_path": "data/research/formal_backtests/cn_x1_1.json",
        "evidence_cutoff": "2026-08-03",
        "research_only": True,
        "trade_ready": False,
        "source": {
            "kind": "github_actions_artifact",
            "repository": "liuh886/alpha_engine",
            "workflow_run_id": 31022910416,
            "workflow_head_sha": "20bb4f52d16e11fe594480226d0a02989cf9b00b",
            "artifact_id": 8937409026,
            "artifact_name": "cn-x1-1-fallback-aware-certified-31022910416",
            "artifact_digest": (
                "sha256:e540e400dbefd5178122444e709182323f1b363a3c41496fd8212e5095ee5a4b"
            ),
            "expires_at": "2026-09-04T15:59:13Z",
        },
        "durability": {
            "status": "durable_repository_evidence",
            "on_expiry": "use_hash_bound_formal_package_and_ledgers",
            "approved_durable_locations": [
                "data/research/formal_backtests/cn_x1_1.json",
                "data/research/formal_backtests/cn_x1_1_ledgers/rebalance_periods.csv",
                "data/research/formal_backtests/cn_x1_1_ledgers/holdings.csv",
                "data/research/formal_backtests/cn_x1_1_ledgers/trades.csv",
                "data/research/formal_backtests/cn_x1_1_ledgers/attribution.csv",
            ],
            "non_regenerable_after_expiry": False,
        },
    }
    _write_json(
        output_root / "data/research/formal_promotions/releases/cn_x1_1.json",
        value,
        pretty=True,
    )


def _write_notebook(output_root: Path) -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# CN x1.1 complete formal backtest\n",
                    "Regime-Gated Sector Breadth through 2026-08-03.\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from pathlib import Path\n",
                    "import json, pandas as pd\n",
                    "ROOT = Path('../..').resolve()\n",
                    "package = json.loads((ROOT / 'data/research/formal_backtests/cn_x1_1.json').read_text())\n",
                    "periods = pd.read_csv(ROOT / 'data/research/formal_backtests/cn_x1_1_ledgers/rebalance_periods.csv')\n",
                    "holdings = pd.read_csv(ROOT / 'data/research/formal_backtests/cn_x1_1_ledgers/holdings.csv', dtype={'instrument': str})\n",
                    "trades = pd.read_csv(ROOT / 'data/research/formal_backtests/cn_x1_1_ledgers/trades.csv', dtype={'instrument': str})\n",
                    "package['metrics'], periods.shape, holdings.shape, trades.shape\n",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    _write_json(
        output_root / "notebooks/models/cn_x1_1_complete_backtest.ipynb",
        notebook,
        pretty=True,
    )


def publish_formal_evidence(
    evidence: FormalEvidence,
    *,
    source_dir: Path,
    repository_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    _write_ledgers(output_root, evidence)
    package_path = output_root / "data/research/formal_backtests/cn_x1_1.json"
    _write_json(package_path, evidence.package)
    _v1_catalog(repository_root, output_root, package_path)
    manifest_path = export_model_run(
        _v2_plan(evidence, source_dir),
        output_root=output_root / "data/research/formal_model_runs",
    )
    _v2_catalog(repository_root, output_root, manifest_path)
    _write_model_config(output_root, evidence)
    _write_release(output_root)
    _write_notebook(output_root)
    files = [path for path in sorted(output_root.rglob("*")) if path.is_file()]
    return {
        "schema_version": "1.0.0",
        "status": "cn_x1_1_formal_promotion_materialized",
        "model_id": "cn_x1_1",
        "date_range": evidence.package["date_range"],
        "metrics": evidence.package["metrics"],
        "row_counts": evidence.package["evidence"]["row_counts"],
        "bundle_id": json.loads(manifest_path.read_text(encoding="utf-8"))[
            "bundle_id"
        ],
        "manifest_sha256": _sha(manifest_path),
        "generated_files": [
            {
                "path": path.relative_to(output_root).as_posix(),
                "sha256": _sha(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        ],
        "research_only": True,
        "trade_ready": False,
    }
