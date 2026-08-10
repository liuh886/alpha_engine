"""Rules-based allocation Research Loop runner.

The first supported mission is the frozen BYD v1.3 certification. The runner
binds an accepted formal Bundle v2 baseline, verifies that the maintained V1.2
runner reproduces the retained primary trace over the historical comparison
window, and evaluates the V1.3 delta on the same immutable BYD/515180 data and
execution engine.

No promotion is automatic. Historical selection evidence is explicitly marked
consumed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.byd_515180_allocation import metrics, prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
)
from src.research.byd_v1_3_candidate import (
    CANDIDATE_NAME as V13_MODEL_ID,
    V13_BEAR_DEFENSE_BYD,
    V13_CONVEX_POWER,
    V13_EXPANSION_PCT,
    V13_FULL_INCREMENT_MOMENTUM,
    V13_MIN_HOLD_DAYS,
    build_v13_signals,
    run_v13_candidate,
)
from src.research.formal_baseline import FormalBaseline, load_formal_baseline

RUNNER_ID = "rules_based_allocation_v1"
_EXECUTOR_ID = "byd_v1_3_min_hold_bear_defense_v1"


class EvidenceInvalid(ValueError):
    """Raised when a certification input cannot satisfy its frozen identity."""


def _load_spec(path: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).resolve()
    resolved.relative_to(PROJECT_ROOT.resolve())
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rules-based experiment spec must be a mapping")
    if raw.get("runner") != RUNNER_ID:
        raise ValueError(f"rules-based runner cannot execute {raw.get('runner')!r}")
    return resolved, raw


def _repo_file(raw: str) -> Path:
    path = (PROJECT_ROOT / raw).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_frozen_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    candidate = raw.get("challenger")
    if not isinstance(candidate, dict):
        raise ValueError("rules-based mission requires challenger mapping")
    if candidate.get("candidate_id") != V13_MODEL_ID:
        raise ValueError("BYD v1.3 candidate_id does not match frozen implementation")
    if candidate.get("executor") != _EXECUTOR_ID:
        raise ValueError("unsupported rules-based candidate executor")

    params = candidate.get("parameters")
    if not isinstance(params, dict):
        raise ValueError("BYD v1.3 challenger requires parameters mapping")
    expected = {
        "min_hold_risk_eligible_sessions": V13_MIN_HOLD_DAYS,
        "bear_defense_byd_weight": V13_BEAR_DEFENSE_BYD,
        "bear_defense_etf_weight": 1.0 - V13_BEAR_DEFENSE_BYD,
        "max_financed_increment": V13_EXPANSION_PCT,
        "convex_power": V13_CONVEX_POWER,
        "full_increment_momentum": V13_FULL_INCREMENT_MOMENTUM,
    }
    for key, value in expected.items():
        if params.get(key) != value:
            raise ValueError(
                f"frozen BYD v1.3 parameter drift for {key}: "
                f"{params.get(key)!r} != {value!r}"
            )
    return expected


def _load_formal_identity(raw: dict[str, Any]) -> FormalBaseline:
    baseline = raw.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("rules-based mission requires baseline mapping")
    return load_formal_baseline(
        str(baseline["model_version_id"]),
        expected_model_kind=str(baseline["model_kind"]),
        expected_model_family_id=str(baseline["model_family_id"]),
        expected_bundle_id=str(baseline["bundle_id"]),
        expected_manifest_sha256=str(baseline["manifest_sha256"]),
    )


def _verified_section(
    baseline: FormalBaseline,
    *,
    section_id: str,
    expected_sha256: str,
) -> tuple[Path, str]:
    manifest = json.loads(baseline.manifest_path.read_text(encoding="utf-8"))
    sections = manifest.get("sections")
    if not isinstance(sections, list):
        raise EvidenceInvalid("formal baseline manifest sections are invalid")
    matches = [
        row
        for row in sections
        if isinstance(row, dict) and row.get("section_id") == section_id
    ]
    if len(matches) != 1:
        raise EvidenceInvalid(f"formal baseline section {section_id!r} is not unique")
    section = matches[0]
    if section.get("availability_status") != "available":
        raise EvidenceInvalid(f"formal baseline section {section_id!r} is unavailable")
    declared_sha = str(section.get("sha256", ""))
    if declared_sha != expected_sha256:
        raise EvidenceInvalid(
            f"formal baseline {section_id} SHA does not match frozen mission"
        )
    path = (baseline.manifest_path.parent / str(section["path"])).resolve()
    path.relative_to(baseline.manifest_path.parent.resolve())
    if _sha256(path) != declared_sha:
        raise EvidenceInvalid(f"formal baseline {section_id} file hash drifted")
    return path, declared_sha


def _formal_primary_daily(performance_path: Path, *, cutoff: str) -> pd.DataFrame:
    payload = json.loads(performance_path.read_text(encoding="utf-8"))
    report = payload.get("report")
    if not isinstance(report, list) or not report:
        raise EvidenceInvalid("formal BYD performance report is missing")
    daily = pd.DataFrame(report)
    required = {
        "date",
        "period_return",
        "turnover",
        "transaction_cost",
        "financing_cost",
        "weight_BYD",
        "weight_515180",
        "weight_cash",
    }
    missing = sorted(required - set(daily.columns))
    if missing:
        raise EvidenceInvalid(f"formal BYD performance trace missing columns: {missing}")
    daily["date"] = pd.to_datetime(daily["date"], errors="raise").dt.normalize()
    daily = daily.set_index("date").sort_index()
    daily = daily.loc[: pd.Timestamp(cutoff)].copy()
    daily["net_return"] = pd.to_numeric(daily["period_return"], errors="raise")
    daily["turnover_units"] = pd.to_numeric(daily["turnover"], errors="raise")
    daily["cost"] = pd.to_numeric(daily["transaction_cost"], errors="raise")
    daily["financing_cost"] = pd.to_numeric(daily["financing_cost"], errors="raise")
    daily["position_byd_weight"] = pd.to_numeric(daily["weight_BYD"], errors="raise")
    daily["position_etf_weight"] = pd.to_numeric(
        daily["weight_515180"], errors="raise"
    )
    daily["position_cash_weight"] = pd.to_numeric(
        daily["weight_cash"], errors="raise"
    )
    daily["borrowed_weight"] = (-daily["position_cash_weight"]).clip(lower=0.0)
    return daily


def _extract_inputs(raw: dict[str, Any], root: Path) -> tuple[Path, Path, dict[str, str]]:
    data = raw.get("data")
    if not isinstance(data, dict):
        raise ValueError("rules-based mission requires data mapping")
    byd_archive = _repo_file(str(data["byd_snapshot_tar"]))
    etf_b64 = _repo_file(str(data["etf_artifact_b64"]))

    byd_sha = _sha256(byd_archive)
    if byd_sha != str(data["byd_snapshot_sha256"]):
        raise EvidenceInvalid("BYD snapshot SHA does not match frozen mission")

    decoded_etf = base64.b64decode(etf_b64.read_bytes())
    etf_sha = hashlib.sha256(decoded_etf).hexdigest()
    if etf_sha != str(data["etf_decoded_sha256"]):
        raise EvidenceInvalid("515180 artifact SHA does not match frozen mission")

    byd_dir = root / "byd"
    etf_dir = root / "etf"
    byd_dir.mkdir()
    etf_dir.mkdir()
    with tarfile.open(byd_archive, mode="r:xz") as archive:
        archive.extractall(byd_dir, filter="data")
    with zipfile.ZipFile(io.BytesIO(decoded_etf)) as archive:
        archive.extractall(etf_dir)
    return byd_dir, etf_dir, {
        "byd_snapshot_sha256": byd_sha,
        "etf_decoded_sha256": etf_sha,
    }


def _trace_reproduction(
    formal: pd.DataFrame,
    reproduced: pd.DataFrame,
) -> dict[str, Any]:
    reproduced = reproduced.loc[reproduced.index <= formal.index.max()].copy()
    index_equal = formal.index.equals(reproduced.index)
    columns = {
        "net_return": "net_return",
        "position_byd_weight": "position_byd_weight",
        "position_etf_weight": "position_etf_weight",
        "position_cash_weight": "position_cash_weight",
        "turnover_units": "turnover_units",
        "cost": "cost",
        "financing_cost": "financing_cost",
    }
    max_abs: dict[str, float | None] = {}
    exact = index_equal
    if index_equal:
        for formal_col, reproduced_col in columns.items():
            left = formal[formal_col].astype(float).to_numpy()
            right = reproduced[reproduced_col].astype(float).to_numpy()
            difference = np.abs(left - right)
            max_abs[formal_col] = (
                float(np.nanmax(difference)) if len(difference) else 0.0
            )
            exact = exact and bool(
                np.allclose(left, right, atol=1e-12, rtol=0.0, equal_nan=True)
            )
    else:
        for formal_col in columns:
            max_abs[formal_col] = None
    return {
        "exact": exact,
        "index_equal": index_equal,
        "formal_rows": int(len(formal)),
        "reproduced_rows": int(len(reproduced)),
        "max_absolute_difference": max_abs,
    }


def _window_metrics(
    daily: pd.DataFrame,
    *,
    start: str,
    end: str,
) -> dict[str, float]:
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise EvidenceInvalid(f"empty certification window: {start} to {end}")
    return metrics(block)


def _terminal_wealth(daily: pd.DataFrame, *, start: str, end: str) -> float:
    returns = daily.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"].dropna()
    if returns.empty:
        raise EvidenceInvalid(f"empty return window: {start} to {end}")
    return float((1.0 + returns).prod())


def _evaluate(
    raw: dict[str, Any],
    *,
    formal_primary: pd.DataFrame,
    v12_stress: pd.DataFrame,
    v13_primary: pd.DataFrame,
    v13_stress: pd.DataFrame,
    trace_reproduction: dict[str, Any],
) -> dict[str, Any]:
    windows = raw.get("windows")
    if not isinstance(windows, dict) or "full_overlap" not in windows:
        raise ValueError("rules-based mission requires windows including full_overlap")
    comparisons: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str], dict[str, float]] = {}

    for window, bounds in windows.items():
        if not isinstance(bounds, dict):
            raise ValueError(f"window {window} must be a mapping")
        start = str(bounds["start"])
        end = str(bounds["end"])
        for scenario, model, daily in (
            ("primary", V12_MODEL_ID, formal_primary),
            ("primary", V13_MODEL_ID, v13_primary),
            ("stress", V12_MODEL_ID, v12_stress),
            ("stress", V13_MODEL_ID, v13_stress),
        ):
            row = _window_metrics(daily, start=start, end=end)
            by_key[(scenario, model, window)] = row
            comparisons.append(
                {
                    "scenario": scenario,
                    "model": model,
                    "window": window,
                    **row,
                }
            )

    relative_by_period: dict[str, float] = {}
    for window, bounds in windows.items():
        if window == "full_overlap":
            continue
        start = str(bounds["start"])
        end = str(bounds["end"])
        base = _terminal_wealth(formal_primary, start=start, end=end)
        challenger = _terminal_wealth(v13_primary, start=start, end=end)
        relative_by_period[window] = challenger / base - 1.0

    positive = {key: max(value, 0.0) for key, value in relative_by_period.items()}
    positive_total = sum(positive.values())
    strongest_share = (
        max(positive.values()) / positive_total if positive_total > 0.0 else 1.0
    )

    base_full = by_key[("primary", V12_MODEL_ID, "full_overlap")]
    candidate_full = by_key[("primary", V13_MODEL_ID, "full_overlap")]
    base_stress = by_key[("stress", V12_MODEL_ID, "full_overlap")]
    candidate_stress = by_key[("stress", V13_MODEL_ID, "full_overlap")]

    evaluation = raw.get("evaluation")
    if not isinstance(evaluation, dict):
        raise ValueError("rules-based mission requires evaluation mapping")
    thresholds = evaluation.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("rules-based mission requires evaluation.thresholds")

    drawdown_improvement = (
        float(candidate_full["max_drawdown"]) - float(base_full["max_drawdown"])
    )
    cagr_improvement = float(candidate_full["cagr"]) - float(base_full["cagr"])
    risk_or_return = drawdown_improvement >= float(
        thresholds["min_drawdown_improvement"]
    ) or (
        cagr_improvement >= float(thresholds["min_cagr_improvement_for_return_path"])
        and float(candidate_full["max_drawdown"]) >= float(base_full["max_drawdown"])
    )

    val_relative = relative_by_period.get("fixed_validation", float("-inf"))
    recent_relative = relative_by_period.get(
        "retrospective_2025_plus", float("-inf")
    )
    gates = {
        "baseline_identity_and_trace": bool(trace_reproduction["exact"]),
        "full_calmar_margin": (
            float(candidate_full["calmar"]) - float(base_full["calmar"])
            >= float(thresholds["min_calmar_improvement"])
        ),
        "full_cagr_floor": (
            float(candidate_full["cagr"])
            >= float(base_full["cagr"]) - float(thresholds["max_cagr_shortfall"])
        ),
        "risk_or_return_improvement": risk_or_return,
        "stress_total_return_not_below_baseline": (
            float(candidate_stress["total_return"])
            >= float(base_stress["total_return"])
        ),
        "validation_and_recent_not_both_negative": (
            val_relative >= 0.0 or recent_relative >= 0.0
        ),
        "round_trips_cap": (
            float(candidate_full["round_trips_per_year"])
            <= float(thresholds["max_round_trips_per_year"])
        ),
        "positive_period_concentration": (
            strongest_share
            <= float(thresholds["max_positive_period_contribution_share"])
        ),
    }
    supported = all(gates.values())
    return {
        "decision": (
            "historically_supported_challenger" if supported else "not_supported"
        ),
        "historically_supported": supported,
        "gates": gates,
        "comparison": comparisons,
        "relative_terminal_wealth_by_period": relative_by_period,
        "largest_positive_period_share": strongest_share,
        "diagnostics": {
            "full_cagr_improvement": cagr_improvement,
            "full_drawdown_improvement": drawdown_improvement,
            "full_calmar_improvement": (
                float(candidate_full["calmar"]) - float(base_full["calmar"])
            ),
            "stress_full_total_return_improvement": (
                float(candidate_stress["total_return"])
                - float(base_stress["total_return"])
            ),
        },
    }


def _invalid_receipt(
    raw: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "experiment_id": str(raw["experiment_id"]),
        "runner": RUNNER_ID,
        "status": "completed",
        "decision": "invalid_evidence",
        "historically_supported": False,
        "promotion_authorized": False,
        "research_only": True,
        "trade_ready": False,
        "fresh_holdout": False,
        "historical_evidence_consumed": True,
        "invalid_evidence_reason": reason,
    }


def run_rules_based_allocation_experiment(
    spec_path: str | Path,
) -> dict[str, Any]:
    """Run one frozen rules-based allocation certification mission."""

    _, raw = _load_spec(spec_path)
    if raw.get("active") is not True:
        raise ValueError("rules-based certification spec must be active")
    if raw.get("research_only") is not True or raw.get("trade_ready") is not False:
        raise ValueError("rules-based certification must remain research-only")
    candidate_parameters = _validate_frozen_candidate(raw)

    try:
        baseline = _load_formal_identity(raw)
        baseline_cfg = raw["baseline"]
        performance_path, performance_sha = _verified_section(
            baseline,
            section_id="performance",
            expected_sha256=str(baseline_cfg["performance_sha256"]),
        )
        cutoff = str((raw.get("data") or {})["historical_cutoff"])
        formal_primary = _formal_primary_daily(performance_path, cutoff=cutoff)

        with tempfile.TemporaryDirectory(prefix="alpha-byd-v13-cert-") as temporary:
            temp_root = Path(temporary)
            byd_dir, etf_dir, data_identity = _extract_inputs(raw, temp_root)
            common, v12_signals, _ = prepare_common_dataset(byd_dir, etf_dir)

            canonical = load_canonical_snapshot(byd_dir)
            full_byd = build_research_dataset(canonical.adjusted, canonical.sessions)
            v13_signals = build_v13_signals(
                full_byd,
                target_index=common.index,
            )

            execution = raw.get("execution") or {}
            primary_cost = float(execution["primary_cost_bps"])
            stress_cost = float(execution["stress_cost_bps"])
            primary_financing = float(execution["primary_financing_rate"])
            stress_financing = float(execution["stress_financing_rate"])
            if primary_financing != PRIMARY_FINANCING_RATE:
                raise ValueError("primary financing rate drifted from maintained V1.2")
            if stress_financing != STRESS_FINANCING_RATE:
                raise ValueError("stress financing rate drifted from maintained V1.2")

            v12_primary, _ = run_v12_candidates(
                common,
                v12_signals,
                cost_bps=primary_cost,
                annual_financing_rate=primary_financing,
            )
            v12_stress, _ = run_v12_candidates(
                common,
                v12_signals,
                cost_bps=stress_cost,
                annual_financing_rate=stress_financing,
            )
            v13_primary, v13_diagnostics = run_v13_candidate(
                common,
                v13_signals,
                cost_bps=primary_cost,
                annual_financing_rate=primary_financing,
            )
            v13_stress, _ = run_v13_candidate(
                common,
                v13_signals,
                cost_bps=stress_cost,
                annual_financing_rate=stress_financing,
            )

            reproduced_primary = v12_primary[V12_MODEL_ID].daily.loc[
                : pd.Timestamp(cutoff)
            ]
            trace = _trace_reproduction(formal_primary, reproduced_primary)
            if not trace["exact"]:
                return _invalid_receipt(
                    raw,
                    reason="maintained V1.2 runner does not reproduce formal primary trace",
                )

            evaluation = _evaluate(
                raw,
                formal_primary=formal_primary,
                v12_stress=v12_stress[V12_MODEL_ID].daily.loc[
                    : pd.Timestamp(cutoff)
                ],
                v13_primary=v13_primary.daily.loc[: pd.Timestamp(cutoff)],
                v13_stress=v13_stress.daily.loc[: pd.Timestamp(cutoff)],
                trace_reproduction=trace,
            )

            receipt = {
                "schema_version": "1.0",
                "experiment_id": str(raw["experiment_id"]),
                "runner": RUNNER_ID,
                "status": "completed",
                **evaluation,
                "promotion_authorized": False,
                "research_only": True,
                "trade_ready": False,
                "fresh_holdout": False,
                "historical_evidence_consumed": True,
                "baseline": baseline.to_receipt(),
                "baseline_performance_sha256": performance_sha,
                "candidate": {
                    "candidate_id": V13_MODEL_ID,
                    "executor": _EXECUTOR_ID,
                    "parameters": candidate_parameters,
                },
                "data_identity": data_identity,
                "historical_cutoff": cutoff,
                "candidate_diagnostics": {
                    "bear_days": int(v13_signals["is_bear"].sum()),
                    "risk_on_days": int(v13_signals["base_risk_on"].sum()),
                    "financed_sessions_primary": int(
                        v13_primary.daily["borrowed_weight"].gt(0.0).sum()
                    ),
                    "mean_financed_increment": float(
                        v13_diagnostics["financed_increment"].mean()
                    ),
                },
                "baseline_trace_reproduction": trace,
                "governance": {
                    "post_selection_historical_search_consumed": True,
                    "automatic_promotion": False,
                    "prospective_confirmation_required": True,
                    "formal_baseline_source": "current_model_run_bundle_v2",
                    "v12_local_reimplementation_forbidden": True,
                },
            }
            return receipt
    except EvidenceInvalid as exc:
        return _invalid_receipt(raw, reason=str(exc))
    except (FileNotFoundError, ValueError) as exc:
        if "formal baseline" in str(exc) or "SHA" in str(exc):
            return _invalid_receipt(raw, reason=str(exc))
        raise
