"""Exact incumbent replay for the CN_27 V1.3 formal baseline.

The replay reruns the frozen k2 recipe over the lineage-pinned frozen source
bars and requires the rebuilt row-level evidence to match the published
Bundle v2 sections byte-for-byte. Any input drift fails closed: missing or
modified frozen inputs report ``data_blocked`` so the refresh workflow keeps
waiting for governed data instead of inventing evidence.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.artifacts.formal_bundle_reader import FormalBundleReadError, load_formal_run
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes

REPLAY_ID = "cn_27_v1_3_formal_replay_v1"
MODEL_ID = "cn_27_v1_3"
MODEL_CONTRACT = Path("configs/models/cn_27_v1_3.yaml")
DISCOVERY_CONTRACT = Path(
    "configs/research_experiments/cn_27_v1_3_projected_concentration_discovery_v1.yaml"
)
# Same numeric bar the formal publication itself enforces when it compares a
# fresh reconstruction against sealed summaries: cross-process float noise
# (last-ulp BLAS reduction order) must never fail a replay whose decision
# path is identical.
FLOAT_TOLERANCE = 1e-10


def _values_close(fresh: object, current: object) -> bool:
    if isinstance(fresh, bool) or isinstance(current, bool):
        return fresh is current or fresh == current
    if isinstance(fresh, (int, float)) and isinstance(current, (int, float)):
        return abs(float(fresh) - float(current)) <= FLOAT_TOLERANCE
    if isinstance(fresh, Mapping) and isinstance(current, Mapping):
        return set(fresh) == set(current) and all(
            _values_close(fresh[key], current[key]) for key in fresh
        )
    if isinstance(fresh, list) and isinstance(current, list):
        return len(fresh) == len(current) and all(
            _values_close(a, b) for a, b in zip(fresh, current)
        )
    return fresh == current


def rows_close_enough(fresh: object, current: object) -> bool:
    """Tolerance-bound row equality for replay and refresh prefix gates."""
    return _values_close(fresh, current)


def _receipt(
    *,
    baseline: str | None,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "replay_id": REPLAY_ID,
        "model_id": MODEL_ID,
        "baseline": baseline,
        "decision": decision,
        "reason": reason,
        "research_only": True,
        "trade_ready": False,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_model_contract(root: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load((root / MODEL_CONTRACT).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"model contract must be an object: {MODEL_CONTRACT}")
    return payload


def replay_cn_27_v1_3(*, root: str | Path) -> dict[str, Any]:
    """Recompute the published CN_27 V1.3 evidence and compare it exactly."""

    from scripts.cn27_v1_3_formal_common import (
        RECIPE_ID,
        build_attribution_payload,
        build_backtest_rows,
        load_k2_context,
    )

    normalized_root = Path(root).resolve()
    try:
        accepted = load_formal_run(normalized_root, MODEL_ID)
        baseline = accepted.identity
        cutoff = accepted.evidence_cutoff
        lineage = accepted.section("lineage")
    except Exception as exc:
        return _receipt(baseline=None, decision="invalid_evidence", reason=str(exc))
    source_evidence = lineage.get("source_evidence")
    if not isinstance(source_evidence, Mapping):
        return _receipt(
            baseline=baseline,
            decision="invalid_evidence",
            reason="formal lineage source_evidence is missing",
        )

    try:
        prices_path = normalized_root / str(source_evidence["source_prices"])
        expected_prices_sha = str(source_evidence["source_prices_sha256"])
        pool_rel = str(source_evidence["pool"])
        pool_path = normalized_root / pool_rel
        expected_pool_sha = str(source_evidence["pool_sha256"])
    except KeyError as exc:
        return _receipt(
            baseline=baseline,
            decision="invalid_evidence",
            reason=f"formal lineage source binding is missing: {exc}",
        )
    if not prices_path.is_file() or _sha256_file(prices_path) != expected_prices_sha:
        return _receipt(
            baseline=baseline,
            decision="data_blocked",
            reason="frozen CN_27 source prices are missing or revised",
        )
    if not pool_path.is_file() or _sha256_file(pool_path) != expected_pool_sha:
        return _receipt(
            baseline=baseline,
            decision="data_blocked",
            reason="frozen CN_27 pool file is missing or revised",
        )

    try:
        model_contract = _load_model_contract(normalized_root)
        portfolio = model_contract.get("portfolio")
        if not isinstance(portfolio, Mapping):
            raise ValueError("model contract portfolio block is missing")
        context = load_k2_context(normalized_root / DISCOVERY_CONTRACT)
        recipe = context.recipe
        if recipe.get("id") != RECIPE_ID:
            raise ValueError("frozen k2 recipe identity drifted")
        for field in (
            "maximum_single_equity_sleeve_share",
            "maximum_sector_equity_sleeve_share",
            "minimum_effective_names",
        ):
            if float(recipe.get(field, 0.0)) != float(portfolio.get(field, -1.0)):
                raise ValueError(f"frozen recipe param drifted: {field}")
        if str(portfolio.get("weighting")) != "shrinkage_minimum_variance_projected":
            raise ValueError("frozen weighting identity drifted")
    except Exception as exc:
        return _receipt(
            baseline=baseline, decision="invalid_evidence", reason=str(exc)
        )

    try:
        report, positions, trades = build_backtest_rows(
            context.bars, context.contract, context.result
        )
        attribution_payload = build_attribution_payload(context.attribution)
        state = accepted.refresh_state()
    except Exception as exc:
        return _receipt(
            baseline=baseline, decision="invalid_evidence", reason=str(exc)
        )
    for name, fresh in (
        ("report", report),
        ("positions", positions),
        ("trades", trades),
        ("attribution", attribution_payload),
    ):
        current = state.get(name)
        if not isinstance(current, list) or not rows_close_enough(fresh, current):
            return _receipt(
                baseline=baseline,
                decision="invalid_evidence",
                reason=f"recomputed CN_27 {name} differs from the published bundle",
            )
    if context.bars["date"].max().date().isoformat() != cutoff:
        return _receipt(
            baseline=baseline,
            decision="invalid_evidence",
            reason="recomputed bars do not end at the published evidence cutoff",
        )
    return _receipt(baseline=baseline, decision="exact_replay", reason="ok")
