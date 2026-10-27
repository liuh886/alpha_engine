"""Personal research-study workspace: one specification, one replayable receipt.

Uses the existing Walk-Forward engine and governed data slices. Local receipts
are research artifacts, never source-of-truth market data or trading signals.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any

from src.research.walkforward.contracts import WalkForwardConfig, WalkForwardFold
from src.research.walkforward.pipeline import DEFAULT_WALK_FORWARD_CONFIG


class ResearchStudyError(ValueError):
    """The requested research study cannot be executed or compared safely."""


def study_template() -> dict[str, Any]:
    """A runnable starting point, not a claim that arbitrary factors are supported."""
    return DEFAULT_WALK_FORWARD_CONFIG.to_dict()


def study_catalog(root: Path | None = None) -> dict[str, Any]:
    """Discover the runnable study and existing archived hypothesis evidence."""
    import yaml

    historical = []
    if root is not None:
        for path in sorted((root / "configs" / "research_experiments").glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise ResearchStudyError(f"cannot inspect research experiment {path}: {exc}") from exc
            if not isinstance(raw, dict) or not raw.get("experiment_id"):
                continue
            historical.append({
                "id": str(raw["experiment_id"]),
                "runner": str(raw.get("runner", "unknown")),
                "status": str(raw.get("status", "unknown")),
                "purpose": str(raw.get("purpose", "")).strip(),
                "spec_path": path.relative_to(root).as_posix(),
                "runnable_here": False,
            })
    return {
        "studies": [{
            "id": DEFAULT_WALK_FORWARD_CONFIG.study_id,
            "hypothesis": DEFAULT_WALK_FORWARD_CONFIG.hypothesis_name,
            "engine": "walkforward_volatility_reversal",
            "market": DEFAULT_WALK_FORWARD_CONFIG.market,
            "candidate_symbols": list(DEFAULT_WALK_FORWARD_CONFIG.symbols),
            "benchmark": DEFAULT_WALK_FORWARD_CONFIG.benchmark,
            "editable": ["hypothesis_name", "hypothesis_description", "symbols",
                         "benchmark", "folds", "param_grid", "cost_bps", "slippage_bps"],
            "limitation": "Only the existing volatility/reversal evaluator is implemented; "
                          "editing a study does not create a new factor or certify PIT.",
        }],
        "historical_experiments": historical,
        "research_only": True,
        "trade_ready": False,
    }


def _as_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchStudyError(f"cannot read study JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResearchStudyError("study JSON must be an object")
    return payload


def load_study_spec(path: Path) -> WalkForwardConfig:
    raw = _as_json(path)
    allowed = {f.name for f in fields(WalkForwardConfig)}
    if set(raw) != allowed:
        raise ResearchStudyError(f"study fields mismatch: missing={sorted(allowed - set(raw))}, "
                                 f"unknown={sorted(set(raw) - allowed)}")
    if raw["study_id"] != DEFAULT_WALK_FORWARD_CONFIG.study_id:
        raise ResearchStudyError("unsupported study evaluator; no other factor family is implemented")
    if raw["market"] != DEFAULT_WALK_FORWARD_CONFIG.market or raw["pool_id"] != DEFAULT_WALK_FORWARD_CONFIG.pool_id:
        raise ResearchStudyError("study cannot change the governed market or pool")
    if not isinstance(raw["symbols"], list) or not raw["symbols"] or len(raw["symbols"]) != len(set(raw["symbols"])):
        raise ResearchStudyError("symbols must be a non-empty unique list")
    if not isinstance(raw["folds"], list) or not raw["folds"]:
        raise ResearchStudyError("folds must be a non-empty list")
    if not isinstance(raw["param_grid"], dict):
        raise ResearchStudyError("param_grid must be an object")
    param_names = {"w_rev", "w_vol", "top_k"}
    if set(raw["param_grid"]) != param_names:
        raise ResearchStudyError("parameter grid must contain exactly w_rev, w_vol and top_k")
    if any(not isinstance(raw["param_grid"][name], list) or not raw["param_grid"][name] for name in param_names):
        raise ResearchStudyError("every parameter grid must be a non-empty list")
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0
           for values in raw["param_grid"].values() for v in values):
        raise ResearchStudyError("all grid values must be positive numbers")
    if any(not isinstance(raw[name], (int, float)) or isinstance(raw[name], bool) or raw[name] < 0
           for name in ("cost_bps", "slippage_bps")):
        raise ResearchStudyError("transaction costs must be non-negative numbers")
    fold_fields = {f.name for f in fields(WalkForwardFold)}
    folds = []
    for item in raw["folds"]:
        if not isinstance(item, dict) or set(item) != fold_fields:
            raise ResearchStudyError("fold must declare the exact WalkForwardFold fields")
        folds.append(WalkForwardFold(**item))
    fold_ids = [item.fold_id for item in folds]
    if len(set(fold_ids)) != len(fold_ids):
        raise ResearchStudyError("duplicate fold IDs")
    for prev, nxt in zip(folds, folds[1:]):
        if prev.test_end >= nxt.test_start:
            raise ResearchStudyError("test folds overlap or are not chronological")
    return WalkForwardConfig(
        study_id=raw["study_id"],
        hypothesis_name=raw["hypothesis_name"],
        hypothesis_description=raw["hypothesis_description"],
        market=raw["market"],
        pool_id=raw["pool_id"],
        symbols=tuple(raw["symbols"]),
        benchmark=raw["benchmark"],
        price_mode=raw["price_mode"],
        folds=tuple(folds),
        cost_bps=float(raw["cost_bps"]),
        slippage_bps=float(raw["slippage_bps"]),
        param_grid={k: tuple(v) for k, v in raw["param_grid"].items()},
    )


def _same_evidence(existing: bytes, proposed: dict[str, Any]) -> bool:
    """Repeat executions are idempotent when only their wall-clock time differs."""
    try:
        stored = json.loads(existing)
    except json.JSONDecodeError:
        return False
    if not isinstance(stored, dict):
        return False
    first, second = dict(stored), dict(proposed)
    first.pop("generated_at_utc", None)
    second.pop("generated_at_utc", None)
    return first == second


def save_receipt_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Atomically retain the first receipt; never replace different evidence."""
    content = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False,
                          allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not _same_evidence(path.read_bytes(), payload):
            raise ResearchStudyError(f"refusing to overwrite different retained evidence: {path}")
        return
    fd, temp_name = tempfile.mkstemp(prefix=".study-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_name, path)
        except FileExistsError:
            if not _same_evidence(path.read_bytes(), payload):
                raise ResearchStudyError(f"receipt already exists with different bytes: {path}")
    finally:
        Path(temp_name).unlink(missing_ok=True)


def initialize_study(path: Path) -> dict[str, Any]:
    """Create a user-editable study spec. Never overwrite an existing one."""
    if path.exists():
        raise ResearchStudyError(f"study specification already exists: {path}")
    save_receipt_exclusive(path, study_template())
    return {"status": "ready", "spec_path": str(path), "research_only": True,
            "trade_ready": False}


def run_study(spec: Path | None, root: Path, output: Path | None = None) -> dict[str, Any]:
    """Run the existing engine and retain both successful and blocked outcomes."""
    from src.research.walkforward.pipeline import run_walkforward_study

    cfg = load_study_spec(spec) if spec is not None else DEFAULT_WALK_FORWARD_CONFIG
    result = run_walkforward_study(cfg, root=root)
    payload = result.to_dict()
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise ResearchStudyError("non-research study receipt is not eligible for retention")
    digest = str(payload.get("study_hash", ""))
    if len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
        raise ResearchStudyError("study produced an invalid receipt hash")
    dest = output or root / "artifacts" / "research_studies" / cfg.study_id / f"{digest}.json"
    save_receipt_exclusive(dest, payload)
    return {
        "status": payload["status"],
        "study_id": cfg.study_id,
        "receipt_path": str(dest),
        "study_hash": digest,
        "oos_net_return": payload["overall_oos_net_return"] if payload["status"] == "ready" else None,
        "benchmark_return": payload["overall_benchmark_cumulative_return"] if payload["status"] == "ready" else None,
        "blocked_reasons": payload["blocked_reasons"],
        "pit_certified": False,
        "research_only": True,
        "trade_ready": False,
    }


def compare_studies(left: Path, right: Path) -> dict[str, Any]:
    """Compare observations only under exactly matching data and evaluation frames."""
    first, second = _as_json(left), _as_json(right)
    for receipt in (first, second):
        if (receipt.get("status") != "ready" or receipt.get("research_only") is not True
                or receipt.get("trade_ready") is not False):
            raise ResearchStudyError("both research receipts must be ready and research-only")
        if not isinstance(receipt.get("folds"), list) or not receipt["folds"]:
            raise ResearchStudyError("research receipt has no folds")
    a_cfg = first.get("experiment_receipt") or {}
    b_cfg = second.get("experiment_receipt") or {}
    comparable = ("study_id", "market", "pool_id", "symbols", "benchmark",
                  "price_mode", "folds")
    different = [name for name in comparable if a_cfg.get(name) != b_cfg.get(name)]
    if different:
        raise ResearchStudyError(f"non-comparable study definitions differ: {different}")
    for a, b in zip(first["folds"], second["folds"], strict=True):
        if any(a.get(key) != b.get(key) for key in ("fold_id", "train_data_hash", "test_data_hash")):
            raise ResearchStudyError("non-comparable source data, cutoffs or fold identities")
    if first.get("code_source_sha256") != second.get("code_source_sha256"):
        raise ResearchStudyError("different evaluator source; compare on an identical code revision")
    measures = ("overall_oos_net_return", "overall_benchmark_cumulative_return",
                "overall_oos_net_excess_return", "overall_oos_sharpe_ratio",
                "overall_oos_max_drawdown")
    try:
        deltas = {metric: round(float(second[metric]) - float(first[metric]), 6)
                  for metric in measures}
    except (KeyError, TypeError, ValueError) as exc:
        raise ResearchStudyError(f"missing or invalid study performance metric: {exc}") from exc
    return {
        "status": "comparable",
        "study_id": first.get("study_id"),
        "left_study_hash": first.get("study_hash"),
        "right_study_hash": second.get("study_hash"),
        "right_minus_left": deltas,
        "interpretation": "Descriptive deltas on matched research evidence; "
                          "not proof of alpha or prospective trade eligibility.",
        "pit_certified": False,
        "research_only": True,
        "trade_ready": False,
    }
