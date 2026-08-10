"""Rules-based allocation Research Loop runner.

The first supported mission is the frozen BYD v1.3 certification. It binds the
current formal BYD v1.2 Bundle v2, verifies the maintained V1.2 runner against
that retained trace, then evaluates the frozen V1.3 delta on the same immutable
data and execution contract. Historical evidence is consumed; promotion is
never automatic.
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
    V13_BEAR_DEFENSE_ETF,
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
    """Raised when frozen evidence identity cannot be reproduced."""


def _load_spec(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    resolved.relative_to(PROJECT_ROOT.resolve())
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rules-based experiment spec must be a mapping")
    if raw.get("runner") != RUNNER_ID:
        raise ValueError(f"rules-based runner cannot execute {raw.get('runner')!r}")
    return raw


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


def _validate_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    challenger = raw.get("challenger")
    if not isinstance(challenger, dict):
        raise ValueError("rules-based mission requires challenger mapping")
    if challenger.get("candidate_id") != V13_MODEL_ID:
        raise ValueError("BYD v1.3 candidate_id does not match frozen implementation")
    if challenger.get("executor") != _EXECUTOR_ID:
        raise ValueError("unsupported rules-based candidate executor")
    params = challenger.get("parameters")
    if not isinstance(params, dict):
        raise ValueError("BYD v1.3 challenger requires parameters mapping")
    expected = {
        "min_hold_risk_eligible_sessions": V13_MIN_HOLD_DAYS,
        "bear_defense_byd_weight": V13_BEAR_DEFENSE_BYD,
        "bear_defense_etf_weight": V13_BEAR_DEFENSE_ETF,
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


def _load_formal(raw: dict[str, Any]) -> FormalBaseline:
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


def _formal_section(
    baseline: FormalBaseline,
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
    if len(matches) != 1 or matches[0].get("availability_status") != "available":
        raise EvidenceInvalid(f"formal baseline section {section_id!r} unavailable")
    section = matches[0]
    declared_sha = str(section.get("sha256", ""))
    if declared_sha != expected_sha256:
        raise EvidenceInvalid(f"formal baseline {section_id} SHA does not match mission")
    path = (baseline.manifest_path.parent / str(section["path"])).resolve()
    path.relative_to(baseline.manifest_path.parent.resolve())
    if _sha256(path) != declared_sha:
        raise EvidenceInvalid(f"formal baseline {section_id} file hash drifted")
    return path, declared_sha


def _formal_daily(path: Path, cutoff: str) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
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
    daily = daily.set_index("date").sort_index().loc[: pd.Timestamp(cutoff)].copy()
    daily["net_return"] = pd.to_numeric(daily["period_return"], errors="raise")
    daily["turnover_units"] = pd.to_numeric(daily["turnover"], errors="raise")
    daily["cost"] = pd.to_numeric(daily["transaction_cost"], errors="raise")
    daily["financing_cost"] = pd.to_numeric(daily["financing_cost"], errors="raise")
    daily["position_byd_weight"] = pd.to_numeric(daily["weight_BYD"], errors="raise")
    daily["position_etf_weight"] = pd.to_numeric(daily["weight_515180"], errors="raise")
    daily["position_cash_weight"] = pd.to_numeric(daily["weight_cash"], errors="raise")
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
    byd_dir, etf_dir = root / "byd", root / "etf"
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


def _trace_reproduction(formal: pd.DataFrame, reproduced: pd.DataFrame) -> dict[str, Any]:
    if reproduced.empty:
        raise EvidenceInvalid("maintained V1.2 reproduction is empty")
    end = min(formal.index.max(), reproduced.index.max())
    formal = formal.loc[:end]
    reproduced = reproduced.loc[:end]
    columns = (
        "net_return",
        "position_byd_weight",
        "position_etf_weight",
        "position_cash_weight",
        "turnover_units",
        "cost",
        "financing_cost",
    )
    index_equal = formal.index.equals(reproduced.index)
    exact = index_equal
    max_abs: dict[str, float | None] = {}
    if index_equal:
        for column in columns:
            left = formal[column].astype(float).to_numpy()
            right = reproduced[column].astype(float).to_numpy()
            difference = np.abs(left - right)
            max_abs[column] = float(np.nanmax(difference)) if len(difference) else 0.0
            exact = exact and bool(
                np.allclose(left, right, atol=1e-12, rtol=0.0, equal_nan=True)
            )
    else:
        max_abs = {column: None for column in columns}
    return {
        "exact": exact,
        "index_equal": index_equal,
        "formal_rows": int(len(formal)),
        "reproduced_rows": int(len(reproduced)),
        "comparison_end": end.strftime("%Y-%m-%d"),
        "max_absolute_difference": max_abs,
    }


def _window_metrics(daily: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise EvidenceInvalid(f"empty certification window: {start} to {end}")
    return metrics(block)


def _wealth(daily: pd.DataFrame, start: str, end: str) -> float:
    returns = daily.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"].dropna()
    if returns.empty:
        raise EvidenceInvalid(f"empty return window: {start} to {end}")
    return float((1.0 + returns).prod())


def _evaluate(
    raw: dict[str, Any],
    formal_primary: pd.DataFrame,
    v12_stress: pd.DataFrame,
    v13_primary: pd.DataFrame,
    v13_stress: pd.DataFrame,
    trace: dict[str, Any],
) -> dict[str, Any]:
    windows = raw.get("windows")
    if not isinstance(windows, dict) or "full_overlap" not in windows:
        raise ValueError("rules-based mission requires windows including full_overlap")
    comparisons: list[dict[str, Any]] = []
    keyed: dict[tuple[str, str, str], dict[str, float]] = {}
    for window, bounds in windows.items():
        if not isinstance(bounds, dict):
            raise ValueError(f"window {window} must be a mapping")
        start, end = str(bounds["start"]), str(bounds["end"])
        for scenario, model, daily in (
            ("primary", V12_MODEL_ID, formal_primary),
            ("primary", V13_MODEL_ID, v13_primary),
            ("stress", V12_MODEL_ID, v12_stress),
            ("stress", V13_MODEL_ID, v13_stress),
        ):
            row = _window_metrics(daily, start, end)
            keyed[(scenario, model, window)] = row
            comparisons.append(
                {"scenario": scenario, "model": model, "window": window, **row}
            )

    relative: dict[str, float] = {}
    for window, bounds in windows.items():
        if window == "full_overlap":
            continue
        start, end = str(bounds["start"]), str(bounds["end"])
        relative[window] = (
            _wealth(v13_primary, start, end) / _wealth(formal_primary, start, end) - 1.0
        )
    positives = [max(value, 0.0) for value in relative.values()]
    positive_total = sum(positives)
    strongest_share = max(positives) / positive_total if positive_total > 0.0 else 1.0

    primary_base = keyed[("primary", V12_MODEL_ID, "full_overlap")]
    primary_candidate = keyed[("primary", V13_MODEL_ID, "full_overlap")]
    stress_base = keyed[("stress", V12_MODEL_ID, "full_overlap")]
    stress_candidate = keyed[("stress", V13_MODEL_ID, "full_overlap")]
    validation_base = keyed[("primary", V12_MODEL_ID, "fixed_validation")]
    validation_candidate = keyed[("primary", V13_MODEL_ID, "fixed_validation")]
    recent_base = keyed[("primary", V12_MODEL_ID, "retrospective_2025_plus")]
    recent_candidate = keyed[("primary", V13_MODEL_ID, "retrospective_2025_plus")]

    evaluation = raw.get("evaluation")
    thresholds = evaluation.get("thresholds") if isinstance(evaluation, dict) else None
    if not isinstance(thresholds, dict):
        raise ValueError("rules-based mission requires evaluation.thresholds")

    primary_drawdown_gain = (
        float(primary_candidate["max_drawdown"])
        - float(primary_base["max_drawdown"])
    )
    stress_drawdown_gain = (
        float(stress_candidate["max_drawdown"])
        - float(stress_base["max_drawdown"])
    )
    gates = {
        "baseline_identity_and_trace": bool(trace["exact"]),
        "primary_full_cagr_floor": (
            float(primary_candidate["cagr"])
            >= float(primary_base["cagr"])
            - float(thresholds["max_primary_cagr_shortfall"])
        ),
        "primary_full_sharpe_not_below": (
            float(primary_candidate["sharpe"]) >= float(primary_base["sharpe"])
        ),
        "primary_full_calmar_not_below": (
            float(primary_candidate["calmar"]) >= float(primary_base["calmar"])
        ),
        "primary_full_drawdown_improvement": (
            primary_drawdown_gain
            >= float(thresholds["min_primary_drawdown_improvement"])
        ),
        "fixed_validation_cagr_not_below": (
            float(validation_candidate["cagr"]) >= float(validation_base["cagr"])
        ),
        "retrospective_2025_plus_cagr_not_below": (
            float(recent_candidate["cagr"]) >= float(recent_base["cagr"])
        ),
        "round_trips_cap": (
            float(primary_candidate["round_trips_per_year"])
            <= float(thresholds["max_round_trips_per_year"])
        ),
        "stress_full_cagr_floor": (
            float(stress_candidate["cagr"])
            >= float(stress_base["cagr"])
            - float(thresholds["max_stress_cagr_shortfall"])
        ),
        "stress_full_calmar_not_below": (
            float(stress_candidate["calmar"]) >= float(stress_base["calmar"])
        ),
        "stress_full_drawdown_improvement": (
            stress_drawdown_gain
            >= float(thresholds["min_stress_drawdown_improvement"])
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
        "relative_terminal_wealth_by_period": relative,
        "largest_positive_period_share": strongest_share,
        "diagnostics": {
            "primary_full_cagr_improvement": (
                float(primary_candidate["cagr"]) - float(primary_base["cagr"])
            ),
            "primary_full_sharpe_improvement": (
                float(primary_candidate["sharpe"]) - float(primary_base["sharpe"])
            ),
            "primary_full_calmar_improvement": (
                float(primary_candidate["calmar"]) - float(primary_base["calmar"])
            ),
            "primary_full_drawdown_improvement": primary_drawdown_gain,
            "fixed_validation_cagr_improvement": (
                float(validation_candidate["cagr"]) - float(validation_base["cagr"])
            ),
            "retrospective_2025_plus_cagr_improvement": (
                float(recent_candidate["cagr"]) - float(recent_base["cagr"])
            ),
            "stress_full_cagr_improvement": (
                float(stress_candidate["cagr"]) - float(stress_base["cagr"])
            ),
            "stress_full_calmar_improvement": (
                float(stress_candidate["calmar"]) - float(stress_base["calmar"])
            ),
            "stress_full_drawdown_improvement": stress_drawdown_gain,
        },
    }


def _invalid(raw: dict[str, Any], reason: str) -> dict[str, Any]:
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


def run_rules_based_allocation_experiment(spec_path: str | Path) -> dict[str, Any]:
    """Run one frozen rules-based allocation certification mission."""
    raw = _load_spec(spec_path)
    if raw.get("active") is not True:
        raise ValueError("rules-based certification spec must be active")
    if raw.get("research_only") is not True or raw.get("trade_ready") is not False:
        raise ValueError("rules-based certification must remain research-only")
    params = _validate_candidate(raw)
    try:
        baseline = _load_formal(raw)
        baseline_cfg = raw["baseline"]
        performance_path, performance_sha = _formal_section(
            baseline, "performance", str(baseline_cfg["performance_sha256"])
        )
        cutoff = str((raw.get("data") or {})["historical_cutoff"])
        formal_primary = _formal_daily(performance_path, cutoff)
        with tempfile.TemporaryDirectory(prefix="alpha-byd-v13-cert-") as temporary:
            byd_dir, etf_dir, data_identity = _extract_inputs(raw, Path(temporary))
            common, v12_signals, _ = prepare_common_dataset(byd_dir, etf_dir)
            canonical = load_canonical_snapshot(byd_dir)
            full_byd = build_research_dataset(canonical.adjusted, canonical.sessions)
            v13_signals = build_v13_signals(full_byd, target_index=common.index)
            execution = raw.get("execution") or {}
            primary_cost = float(execution["primary_cost_bps"])
            stress_cost = float(execution["stress_cost_bps"])
            primary_financing = float(execution["primary_financing_rate"])
            stress_financing = float(execution["stress_financing_rate"])
            if (
                primary_financing != PRIMARY_FINANCING_RATE
                or stress_financing != STRESS_FINANCING_RATE
            ):
                raise ValueError("financing rates drifted from maintained V1.2")

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
            v13_primary, diagnostics = run_v13_candidate(
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
            reproduced = v12_primary[V12_MODEL_ID].daily.loc[: pd.Timestamp(cutoff)]
            trace = _trace_reproduction(formal_primary, reproduced)
            if not trace["exact"]:
                return _invalid(
                    raw,
                    "maintained V1.2 runner does not reproduce formal primary trace",
                )
            end = pd.Timestamp(str(trace["comparison_end"]))
            evaluation = _evaluate(
                raw,
                formal_primary.loc[:end],
                v12_stress[V12_MODEL_ID].daily.loc[:end],
                v13_primary.daily.loc[:end],
                v13_stress.daily.loc[:end],
                trace,
            )
            return {
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
                    "parameters": params,
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
                        diagnostics["financed_increment"].mean()
                    ),
                },
                "baseline_trace_reproduction": trace,
                "governance": {
                    "post_selection_historical_search_consumed": True,
                    "automatic_promotion": False,
                    "prospective_confirmation_required": True,
                    "formal_baseline_source": "current_model_run_bundle_v2",
                    "v12_local_reimplementation_forbidden": True,
                    "promotion_authority": "explicit_user_direction_2026_08_10",
                },
            }
    except EvidenceInvalid as exc:
        return _invalid(raw, str(exc))
    except (FileNotFoundError, ValueError) as exc:
        if "formal baseline" in str(exc) or "SHA" in str(exc):
            return _invalid(raw, str(exc))
        raise
