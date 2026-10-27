"""Personal research-study workspace: one specification, one replayable receipt.

Unified study workspace supporting diverse quantitative investment hypotheses:
1. Walk-Forward Volatility Reversal (us_tech_vol_reversal_v1)
2. Cross-Sectional XGBoost Ranker (cross_sectional_xgb_v1)
3. Multi-Factor Rank IC & Monotonicity Exploration (factor_exploration_v1)
4. A-Share RDI Macro Risk Event Forward Outcomes (ashare_rdi_v1)

Uses existing governed data slices and execution modules. Local receipts
are research artifacts, never source-of-truth market data or trading signals.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from src.research.walkforward.contracts import WalkForwardConfig, WalkForwardFold
from src.research.walkforward.pipeline import DEFAULT_WALK_FORWARD_CONFIG


class ResearchStudyError(ValueError):
    """The requested research study cannot be executed or compared safely."""


# ---------------------------------------------------------------------------
# Study Specifications & Configurations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossSectionalXGBConfig:
    """Configuration for cross-sectional XGBoost ranking study."""

    study_id: str
    hypothesis_name: str
    hypothesis_description: str
    market: str
    pool_id: str
    symbols: tuple[str, ...]
    benchmark: str
    price_mode: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    as_of_cutoff: str
    top_k: int
    cost_bps: float
    slippage_bps: float
    xgb_params: dict[str, Any]
    features: tuple[str, ...] = ("return_5d", "return_20d", "volatility_20d", "volume_ratio_20d")

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "hypothesis_name": self.hypothesis_name,
            "hypothesis_description": self.hypothesis_description,
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": list(self.symbols),
            "benchmark": self.benchmark,
            "price_mode": self.price_mode,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "as_of_cutoff": self.as_of_cutoff,
            "top_k": self.top_k,
            "cost_bps": self.cost_bps,
            "slippage_bps": self.slippage_bps,
            "xgb_params": dict(self.xgb_params),
            "features": list(self.features),
        }


@dataclass(frozen=True)
class FactorExplorationConfig:
    """Configuration for multi-factor Rank IC exploration study."""

    study_id: str
    hypothesis_name: str
    hypothesis_description: str
    market: str
    pool_id: str
    symbols: tuple[str, ...]
    benchmark: str
    price_mode: str
    start_date: str
    end_date: str
    as_of_cutoff: str
    factors: tuple[str, ...] = ("momentum_20", "volatility_20", "volume_ratio_20")
    forward_horizon: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "hypothesis_name": self.hypothesis_name,
            "hypothesis_description": self.hypothesis_description,
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": list(self.symbols),
            "benchmark": self.benchmark,
            "price_mode": self.price_mode,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "as_of_cutoff": self.as_of_cutoff,
            "factors": list(self.factors),
            "forward_horizon": self.forward_horizon,
        }


@dataclass(frozen=True)
class AShareRDIConfig:
    """Configuration for A-share RDI risk event horizon study."""

    study_id: str
    hypothesis_name: str
    hypothesis_description: str
    market: str
    pool_id: str
    symbols: tuple[str, ...]
    benchmark: str
    price_mode: str
    start_date: str
    end_date: str
    as_of_cutoff: str
    horizons: tuple[int, ...]
    event: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "hypothesis_name": self.hypothesis_name,
            "hypothesis_description": self.hypothesis_description,
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": list(self.symbols),
            "benchmark": self.benchmark,
            "price_mode": self.price_mode,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "as_of_cutoff": self.as_of_cutoff,
            "horizons": list(self.horizons),
            "event": self.event,
        }


DEFAULT_XGB_CONFIG = CrossSectionalXGBConfig(
    study_id="cross_sectional_xgb_v1",
    hypothesis_name="US Tech Multi-factor Non-linear Cross-Sectional XGBoost Ranking",
    hypothesis_description="XGBoost rank:ndcg tree model ranking cross-section of US tech leaders using return, volatility, and volume features, evaluated out-of-sample against QQQ.",
    market="us",
    pool_id="us_selected_equities_v2",
    symbols=("AAPL", "MSFT", "GOOGL", "NVDA", "AMZN", "META", "AVGO", "TSLA"),
    benchmark="QQQ",
    price_mode="anchored_adjusted",
    train_start="2024-01-02",
    train_end="2024-12-31",
    test_start="2025-01-02",
    test_end="2025-06-30",
    as_of_cutoff="2025-06-30",
    top_k=3,
    cost_bps=3.0,
    slippage_bps=5.0,
    xgb_params={
        "n_gain_bins": 5,
        "num_boost_round": 20,
        "max_depth": 3,
        "learning_rate": 0.05,
        "seed": 42,
    },
    features=("return_5d", "return_20d", "volatility_20d", "volume_ratio_20d"),
)

DEFAULT_FACTOR_EXPLORATION_CONFIG = FactorExplorationConfig(
    study_id="factor_exploration_v1",
    hypothesis_name="CN Selected Equities Multi-Factor Rank IC and Cross-Sectional Monotonicity",
    hypothesis_description="Evaluates cross-sectional factor rankings, Spearman Rank IC, and IC-IR across CN candidate equities on governed data slices.",
    market="cn",
    pool_id="cn_selected_equities_v3",
    symbols=("000001", "000338", "600519", "688008"),
    benchmark="000300",
    price_mode="anchored_adjusted",
    start_date="2024-01-01",
    end_date="2026-09-04",
    as_of_cutoff="2026-09-04",
    factors=("momentum_20", "volatility_20", "volume_ratio_20"),
    forward_horizon=5,
)

DEFAULT_ASHARE_RDI_CONFIG = AShareRDIConfig(
    study_id="ashare_rdi_v1",
    hypothesis_name="A-Share RDI Macro Risk Event Forward Realized Horizon Response",
    hypothesis_description="Realized forward 7/14/28-session outcome analysis for CSI 300 following documented PIT macro/policy events (#1272).",
    market="cn",
    pool_id="cn_selected_equities_v3",
    symbols=("000300",),
    benchmark="000300",
    price_mode="anchored_adjusted",
    start_date="2024-01-01",
    end_date="2026-09-04",
    as_of_cutoff="2026-09-04",
    horizons=(7, 14, 28),
    event={
        "event_id": "macro-risk-policy-20240510",
        "story_id": "story-macro-pboc-2024",
        "family": "policy_easing",
        "direction": "policy",
        "scope": "market",
        "sector_id": None,
        "stage": "announced",
        "announced_at": "2024-05-09T18:00:00Z",
        "available_at": "2024-05-09T20:00:00Z",
        "active_from": "2024-05-10",
        "active_until": "2024-06-20",
        "source_id": "gov://pbc.gov.cn/notice/2024-0509",
        "source_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
    },
)

SUPPORTED_STUDY_TEMPLATES: dict[str, Any] = {
    DEFAULT_WALK_FORWARD_CONFIG.study_id: DEFAULT_WALK_FORWARD_CONFIG,
    DEFAULT_XGB_CONFIG.study_id: DEFAULT_XGB_CONFIG,
    DEFAULT_FACTOR_EXPLORATION_CONFIG.study_id: DEFAULT_FACTOR_EXPLORATION_CONFIG,
    DEFAULT_ASHARE_RDI_CONFIG.study_id: DEFAULT_ASHARE_RDI_CONFIG,
}


def study_template(template: str = "us_tech_vol_reversal_v1") -> dict[str, Any]:
    """Return a runnable starting point for the given study template ID."""
    if template not in SUPPORTED_STUDY_TEMPLATES:
        raise ResearchStudyError(
            f"unknown study template: '{template}'. Supported: {sorted(SUPPORTED_STUDY_TEMPLATES.keys())}"
        )
    return SUPPORTED_STUDY_TEMPLATES[template].to_dict()


def study_catalog(root: Path | None = None) -> dict[str, Any]:
    """Discover the runnable studies and existing archived hypothesis evidence."""
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
        "studies": [
            {
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
            },
            {
                "id": DEFAULT_XGB_CONFIG.study_id,
                "hypothesis": DEFAULT_XGB_CONFIG.hypothesis_name,
                "engine": "cross_sectional_xgb",
                "market": DEFAULT_XGB_CONFIG.market,
                "candidate_symbols": list(DEFAULT_XGB_CONFIG.symbols),
                "benchmark": DEFAULT_XGB_CONFIG.benchmark,
                "editable": ["hypothesis_name", "hypothesis_description", "symbols",
                             "benchmark", "train_start", "train_end", "test_start", "test_end",
                             "top_k", "cost_bps", "slippage_bps", "xgb_params", "features"],
                "limitation": "Evaluates multi-factor non-linear ranking using native XGBoost rank:ndcg "
                              "on governed data slices. Does not certify PIT or trade execution.",
            },
            {
                "id": DEFAULT_FACTOR_EXPLORATION_CONFIG.study_id,
                "hypothesis": DEFAULT_FACTOR_EXPLORATION_CONFIG.hypothesis_name,
                "engine": "factor_exploration",
                "market": DEFAULT_FACTOR_EXPLORATION_CONFIG.market,
                "candidate_symbols": list(DEFAULT_FACTOR_EXPLORATION_CONFIG.symbols),
                "benchmark": DEFAULT_FACTOR_EXPLORATION_CONFIG.benchmark,
                "editable": ["hypothesis_name", "hypothesis_description", "symbols",
                             "benchmark", "start_date", "end_date", "as_of_cutoff", "factors", "forward_horizon"],
                "limitation": "Explores factor Rank IC and cross-sectional dispersion on governed data slices; "
                              "does not promote factors to production or certify PIT.",
            },
            {
                "id": DEFAULT_ASHARE_RDI_CONFIG.study_id,
                "hypothesis": DEFAULT_ASHARE_RDI_CONFIG.hypothesis_name,
                "engine": "ashare_rdi",
                "market": DEFAULT_ASHARE_RDI_CONFIG.market,
                "candidate_symbols": list(DEFAULT_ASHARE_RDI_CONFIG.symbols),
                "benchmark": DEFAULT_ASHARE_RDI_CONFIG.benchmark,
                "editable": ["hypothesis_name", "hypothesis_description", "symbols",
                             "start_date", "end_date", "as_of_cutoff", "horizons", "event"],
                "limitation": "Descriptive forward outcome measurement only; strictly forbidden from "
                              "being promoted to a live trading signal or certifying full multi-vintage PIT.",
            },
        ],
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


def load_study_spec(path: Path) -> WalkForwardConfig | CrossSectionalXGBConfig | FactorExplorationConfig | AShareRDIConfig:
    """Validate and deserialize an editable research study specification."""
    raw = _as_json(path)
    study_id = raw.get("study_id")

    if study_id == DEFAULT_WALK_FORWARD_CONFIG.study_id:
        allowed = {f.name for f in fields(WalkForwardConfig)}
        if set(raw) != allowed:
            raise ResearchStudyError(f"study fields mismatch: missing={sorted(allowed - set(raw))}, "
                                     f"unknown={sorted(set(raw) - allowed)}")
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

    elif study_id == DEFAULT_XGB_CONFIG.study_id:
        allowed = {f.name for f in fields(CrossSectionalXGBConfig)}
        if set(raw) != allowed:
            raise ResearchStudyError(f"study fields mismatch: missing={sorted(allowed - set(raw))}, "
                                     f"unknown={sorted(set(raw) - allowed)}")
        if raw["market"] != "us" or raw["pool_id"] != "us_selected_equities_v2":
            raise ResearchStudyError("study cannot change the governed market or pool")
        if not isinstance(raw["symbols"], list) or not raw["symbols"] or len(raw["symbols"]) != len(set(raw["symbols"])):
            raise ResearchStudyError("symbols must be a non-empty unique list")
        if raw["train_start"] >= raw["train_end"]:
            raise ResearchStudyError("train_start must precede train_end")
        if raw["train_end"] >= raw["test_start"]:
            raise ResearchStudyError("train_end must precede test_start")
        if raw["test_start"] > raw["test_end"] or raw["test_end"] > raw["as_of_cutoff"]:
            raise ResearchStudyError("test window must be within as_of_cutoff")
        if not isinstance(raw.get("xgb_params"), dict) or not raw["xgb_params"]:
            raise ResearchStudyError("xgb_params must be a non-empty dictionary")
        if not isinstance(raw.get("features"), list) or not raw["features"]:
            raise ResearchStudyError("features must be a non-empty list")
        if int(raw["top_k"]) <= 0 or int(raw["top_k"]) > len(raw["symbols"]):
            raise ResearchStudyError("top_k must be positive and <= len(symbols)")
        return CrossSectionalXGBConfig(
            study_id=raw["study_id"],
            hypothesis_name=raw["hypothesis_name"],
            hypothesis_description=raw["hypothesis_description"],
            market=raw["market"],
            pool_id=raw["pool_id"],
            symbols=tuple(raw["symbols"]),
            benchmark=raw["benchmark"],
            price_mode=raw["price_mode"],
            train_start=raw["train_start"],
            train_end=raw["train_end"],
            test_start=raw["test_start"],
            test_end=raw["test_end"],
            as_of_cutoff=raw["as_of_cutoff"],
            top_k=int(raw["top_k"]),
            cost_bps=float(raw["cost_bps"]),
            slippage_bps=float(raw["slippage_bps"]),
            xgb_params=dict(raw["xgb_params"]),
            features=tuple(raw["features"]),
        )

    elif study_id == DEFAULT_FACTOR_EXPLORATION_CONFIG.study_id:
        allowed = {f.name for f in fields(FactorExplorationConfig)}
        if set(raw) != allowed:
            raise ResearchStudyError(f"study fields mismatch: missing={sorted(allowed - set(raw))}, "
                                     f"unknown={sorted(set(raw) - allowed)}")
        if raw["market"] != "cn" or raw["pool_id"] != "cn_selected_equities_v3":
            raise ResearchStudyError("study cannot change the governed market or pool")
        if not isinstance(raw["symbols"], list) or not raw["symbols"] or len(raw["symbols"]) != len(set(raw["symbols"])):
            raise ResearchStudyError("symbols must be a non-empty unique list")
        if raw["start_date"] >= raw["end_date"] or raw["end_date"] > raw["as_of_cutoff"]:
            raise ResearchStudyError("date range must be chronological and <= as_of_cutoff")
        if not isinstance(raw.get("factors"), list) or not raw["factors"]:
            raise ResearchStudyError("factors must be a non-empty list")
        return FactorExplorationConfig(
            study_id=raw["study_id"],
            hypothesis_name=raw["hypothesis_name"],
            hypothesis_description=raw["hypothesis_description"],
            market=raw["market"],
            pool_id=raw["pool_id"],
            symbols=tuple(raw["symbols"]),
            benchmark=raw["benchmark"],
            price_mode=raw["price_mode"],
            start_date=raw["start_date"],
            end_date=raw["end_date"],
            as_of_cutoff=raw["as_of_cutoff"],
            factors=tuple(raw["factors"]),
            forward_horizon=int(raw.get("forward_horizon", 5)),
        )

    elif study_id == DEFAULT_ASHARE_RDI_CONFIG.study_id:
        allowed = {f.name for f in fields(AShareRDIConfig)}
        if set(raw) != allowed:
            raise ResearchStudyError(f"study fields mismatch: missing={sorted(allowed - set(raw))}, "
                                     f"unknown={sorted(set(raw) - allowed)}")
        if raw["start_date"] >= raw["end_date"] or raw["end_date"] > raw["as_of_cutoff"]:
            raise ResearchStudyError("date range must be chronological and <= as_of_cutoff")
        if not isinstance(raw.get("horizons"), list) or not raw["horizons"]:
            raise ResearchStudyError("horizons must be a non-empty list")
        return AShareRDIConfig(
            study_id=raw["study_id"],
            hypothesis_name=raw["hypothesis_name"],
            hypothesis_description=raw["hypothesis_description"],
            market=raw["market"],
            pool_id=raw["pool_id"],
            symbols=tuple(raw["symbols"]),
            benchmark=raw["benchmark"],
            price_mode=raw["price_mode"],
            start_date=raw["start_date"],
            end_date=raw["end_date"],
            as_of_cutoff=raw["as_of_cutoff"],
            horizons=tuple(raw["horizons"]),
            event=raw.get("event"),
        )

    else:
        raise ResearchStudyError(
            f"unsupported study evaluator; unknown study_id '{study_id}'. "
            f"Supported: {sorted(SUPPORTED_STUDY_TEMPLATES.keys())}"
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


def initialize_study(path: Path, template: str = "us_tech_vol_reversal_v1") -> dict[str, Any]:
    """Create a user-editable study spec. Never overwrite an existing one."""
    if path.exists():
        raise ResearchStudyError(f"study specification already exists: {path}")
    save_receipt_exclusive(path, study_template(template))
    return {
        "status": "ready",
        "spec_path": str(path),
        "template": template,
        "research_only": True,
        "trade_ready": False,
    }


# ---------------------------------------------------------------------------
# Unified Dispatcher: run_study, inspect_study, compare_studies
# ---------------------------------------------------------------------------


def run_study(
    spec: Path | None,
    root: Path,
    output: Path | None = None,
    *,
    bypass_archive_check_for_test: bool = False,
) -> dict[str, Any]:
    """Run a frozen study spec and retain both successful and blocked outcomes."""
    if spec is None:
        cfg = DEFAULT_WALK_FORWARD_CONFIG
    else:
        cfg = load_study_spec(spec)

    if isinstance(cfg, WalkForwardConfig):
        from src.research.walkforward.pipeline import run_walkforward_study
        result = run_walkforward_study(cfg, root=root)
        payload = result.to_dict()
    elif isinstance(cfg, CrossSectionalXGBConfig):
        from src.research.studies.xgb_study import run_cross_sectional_xgb_study
        payload = run_cross_sectional_xgb_study(cfg, root=root)
    elif isinstance(cfg, FactorExplorationConfig):
        from src.research.studies.factor_study import run_factor_exploration_study
        payload = run_factor_exploration_study(cfg, root=root)
    elif isinstance(cfg, AShareRDIConfig):
        from src.research.studies.rdi_study import run_ashare_rdi_study
        payload = run_ashare_rdi_study(cfg, root=root, bypass_archive_check_for_test=bypass_archive_check_for_test)
    else:
        raise ResearchStudyError(f"unsupported study config type: {type(cfg)}")

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
        "oos_net_return": payload.get("overall_oos_net_return") if payload["status"] == "ready" else None,
        "benchmark_return": payload.get("overall_benchmark_cumulative_return") if payload["status"] == "ready" else None,
        "blocked_reasons": payload.get("blocked_reasons", []),
        "pit_certified": False,
        "research_only": True,
        "trade_ready": False,
    }


def inspect_study(path: Path) -> dict[str, Any]:
    """Open one saved receipt without touching its raw source or current strategy state."""
    receipt = _as_json(path)
    if receipt.get("research_only") is not True or receipt.get("trade_ready") is not False:
        raise ResearchStudyError("only research-only study receipts can be inspected")
    if receipt.get("status") not in {"ready", "blocked"}:
        raise ResearchStudyError("unknown study status")

    study_id = receipt.get("study_id")
    base = {
        "study_id": study_id,
        "status": receipt["status"],
        "hypothesis": receipt.get("hypothesis_name"),
        "study_hash": receipt.get("study_hash"),
        "source_commit": receipt.get("git_commit"),
        "pit_certified": False,
        "blocked_reasons": receipt.get("blocked_reasons", []),
        "pit_limitations": receipt.get("pit_limitations", []),
        "research_only": True,
        "trade_ready": False,
    }

    if study_id == "us_tech_vol_reversal_v1" or "folds" in receipt:
        folds = receipt.get("folds")
        if not isinstance(folds, list):
            raise ResearchStudyError("study receipt has no fold evidence")
        base.update({
            "oos_net_return": receipt.get("overall_oos_net_return") if receipt["status"] == "ready" else None,
            "qqq_or_benchmark_return": receipt.get("overall_benchmark_cumulative_return")
            if receipt["status"] == "ready" else None,
            "oos_net_excess_return": receipt.get("overall_oos_net_excess_return")
            if receipt["status"] == "ready" else None,
            "oos_sharpe": receipt.get("overall_oos_sharpe_ratio")
            if receipt["status"] == "ready" else None,
            "oos_max_drawdown": receipt.get("overall_oos_max_drawdown")
            if receipt["status"] == "ready" else None,
            "folds": [{
                "fold_id": fold.get("fold_id"),
                "status": fold.get("status"),
                "blocked_reasons": fold.get("blocked_reasons"),
                "selected_parameters": fold.get("selected_parameters"),
                "train_data_hash": fold.get("train_data_hash"),
                "test_data_hash": fold.get("test_data_hash"),
                "oos_net_return": fold.get("out_of_sample_net_return")
                if fold.get("status") == "ready" else None,
                "oos_sessions_count": fold.get("oos_sessions_count"),
            } for fold in folds if isinstance(fold, dict)],
        })
    elif study_id == "cross_sectional_xgb_v1":
        base.update({
            "oos_net_return": receipt.get("overall_oos_net_return") if receipt["status"] == "ready" else None,
            "benchmark_return": receipt.get("overall_benchmark_cumulative_return")
            if receipt["status"] == "ready" else None,
            "oos_net_excess_return": receipt.get("overall_oos_net_excess_return")
            if receipt["status"] == "ready" else None,
            "oos_sharpe": receipt.get("overall_oos_sharpe_ratio")
            if receipt["status"] == "ready" else None,
            "oos_max_drawdown": receipt.get("overall_oos_max_drawdown")
            if receipt["status"] == "ready" else None,
            "rank_ic": receipt.get("rank_ic") if receipt["status"] == "ready" else None,
            "ic_ir": receipt.get("ic_ir") if receipt["status"] == "ready" else None,
            "feature_importance": receipt.get("feature_importance")
            if receipt["status"] == "ready" else None,
            "train_data_hash": receipt.get("train_data_hash"),
            "test_data_hash": receipt.get("test_data_hash"),
            "oos_sessions_count": receipt.get("oos_sessions_count"),
        })
    elif study_id == "factor_exploration_v1":
        base.update({
            "mean_rank_ic": receipt.get("mean_rank_ic") if receipt["status"] == "ready" else None,
            "ic_ir": receipt.get("ic_ir") if receipt["status"] == "ready" else None,
            "factor_summaries": receipt.get("factor_summaries") if receipt["status"] == "ready" else None,
            "latest_rankings": receipt.get("latest_rankings") if receipt["status"] == "ready" else None,
            "evaluated_sessions_count": receipt.get("evaluated_sessions_count"),
            "data_hash": receipt.get("data_hash"),
        })
    elif study_id == "ashare_rdi_v1":
        base.update({
            "decision_session": receipt.get("decision_session"),
            "horizons": receipt.get("horizons"),
            "event_provenance": receipt.get("event_provenance"),
            "outcomes": receipt.get("outcomes") if receipt["status"] == "ready" else None,
            "data_hash": receipt.get("data_hash"),
        })
    return base


def compare_studies(left: Path, right: Path) -> dict[str, Any]:
    """Compare observations only under exactly matching study families and data frames."""
    first, second = _as_json(left), _as_json(right)
    for receipt in (first, second):
        if (receipt.get("status") != "ready" or receipt.get("research_only") is not True
                or receipt.get("trade_ready") is not False):
            raise ResearchStudyError("both research receipts must be ready and research-only")

    study_id = first.get("study_id")
    if study_id != second.get("study_id"):
        raise ResearchStudyError(f"cannot compare different study families: {study_id} vs {second.get('study_id')}")

    if first.get("code_source_sha256") and second.get("code_source_sha256"):
        if first.get("code_source_sha256") != second.get("code_source_sha256"):
            raise ResearchStudyError("different evaluator source; compare on an identical code revision")

    a_cfg = first.get("experiment_receipt") or {}
    b_cfg = second.get("experiment_receipt") or {}

    if study_id == "us_tech_vol_reversal_v1":
        if not isinstance(first.get("folds"), list) or not first["folds"]:
            raise ResearchStudyError("research receipt has no folds")
        if not isinstance(second.get("folds"), list) or not second["folds"]:
            raise ResearchStudyError("research receipt has no folds")
        comparable = ("study_id", "market", "pool_id", "symbols", "benchmark", "price_mode", "folds")
        different = [name for name in comparable if a_cfg.get(name) != b_cfg.get(name)]
        if different:
            raise ResearchStudyError(f"non-comparable study definitions differ: {different}")
        for a, b in zip(first["folds"], second["folds"], strict=True):
            if any(a.get(key) != b.get(key) for key in ("fold_id", "train_data_hash", "test_data_hash")):
                raise ResearchStudyError("non-comparable source data, cutoffs or fold identities")
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
            "study_id": study_id,
            "left_study_hash": first.get("study_hash"),
            "right_study_hash": second.get("study_hash"),
            "right_minus_left": deltas,
            "interpretation": "Descriptive deltas on matched research evidence; "
                              "not proof of alpha or prospective trade eligibility.",
            "pit_certified": False,
            "research_only": True,
            "trade_ready": False,
        }

    elif study_id == "cross_sectional_xgb_v1":
        comparable = ("market", "pool_id", "symbols", "benchmark", "train_start", "train_end", "test_start", "test_end")
        different = [k for k in comparable if a_cfg.get(k) != b_cfg.get(k)]
        if different:
            raise ResearchStudyError(f"non-comparable study definitions differ: {different}")
        if first.get("train_data_hash") != second.get("train_data_hash") or first.get("test_data_hash") != second.get("test_data_hash"):
            raise ResearchStudyError("non-comparable source data, cutoffs or fold identities")
        measures = ("overall_oos_net_return", "overall_benchmark_cumulative_return",
                    "overall_oos_net_excess_return", "overall_oos_sharpe_ratio",
                    "overall_oos_max_drawdown", "rank_ic", "ic_ir")
        deltas = {
            metric: round(float(second[metric]) - float(first[metric]), 6)
            for metric in measures
            if metric in first and metric in second and first[metric] is not None and second[metric] is not None
        }
        return {
            "status": "comparable",
            "study_id": study_id,
            "left_study_hash": first.get("study_hash"),
            "right_study_hash": second.get("study_hash"),
            "right_minus_left": deltas,
            "interpretation": "Descriptive deltas on matched XGBoost research evidence; "
                              "not proof of alpha or prospective trade eligibility.",
            "pit_certified": False,
            "research_only": True,
            "trade_ready": False,
        }

    elif study_id == "factor_exploration_v1":
        comparable = ("market", "pool_id", "symbols", "start_date", "end_date", "as_of_cutoff")
        different = [k for k in comparable if a_cfg.get(k) != b_cfg.get(k)]
        if different:
            raise ResearchStudyError(f"non-comparable study definitions differ: {different}")
        if first.get("data_hash") != second.get("data_hash"):
            raise ResearchStudyError("non-comparable source data hash")
        deltas = {}
        for m in ("mean_rank_ic", "ic_ir"):
            if first.get(m) is not None and second.get(m) is not None:
                deltas[m] = round(float(second[m]) - float(first[m]), 6)
        return {
            "status": "comparable",
            "study_id": study_id,
            "left_study_hash": first.get("study_hash"),
            "right_study_hash": second.get("study_hash"),
            "right_minus_left": deltas,
            "interpretation": "Descriptive deltas on matched factor exploration evidence; "
                              "not proof of alpha or prospective trade eligibility.",
            "pit_certified": False,
            "research_only": True,
            "trade_ready": False,
        }

    elif study_id == "ashare_rdi_v1":
        if first.get("data_hash") != second.get("data_hash"):
            raise ResearchStudyError("non-comparable source data hash")
        first_outcomes = first.get("outcomes", {})
        second_outcomes = second.get("outcomes", {})
        deltas = {}
        for h in first.get("horizons", []):
            h_str = str(h)
            if h_str in first_outcomes and h_str in second_outcomes:
                f_ret = first_outcomes[h_str].get("forward_return")
                s_ret = second_outcomes[h_str].get("forward_return")
                if f_ret is not None and s_ret is not None:
                    deltas[f"horizon_{h}_forward_return"] = round(float(s_ret) - float(f_ret), 6)
        return {
            "status": "comparable",
            "study_id": study_id,
            "left_study_hash": first.get("study_hash"),
            "right_study_hash": second.get("study_hash"),
            "right_minus_left": deltas,
            "interpretation": "Descriptive deltas on matched RDI event forward horizon evidence; "
                              "not proof of alpha or prospective trade eligibility.",
            "pit_certified": False,
            "research_only": True,
            "trade_ready": False,
        }

    else:
        raise ResearchStudyError(f"unsupported study comparison family: {study_id}")
