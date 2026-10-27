"""Multi-Factor Rank IC & Cross-Sectional Monotonicity Study Module.

Governed under Track B and ADR-0005.
Evaluates cross-sectional factor rankings, Spearman Rank IC, and IC-IR
across candidate equities on governed data slices.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import scipy.stats as stats

from src.data.research_slice import DataSliceRequest, get_research_data_slice

if TYPE_CHECKING:
    from src.research.study_workspace import FactorExplorationConfig


def _get_git_commit(root: Path) -> str:
    import subprocess
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    try:
        repo_root = Path(__file__).resolve().parents[3]
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    raise RuntimeError(f"git_commit_unavailable: git rev-parse HEAD failed with code {res.returncode}")


def _get_code_source_sha256(root: Path) -> dict[str, str]:
    sources = {
        "factor_study": Path(__file__).resolve(),
        "study_workspace": (Path(__file__).resolve().parents[1] / "study_workspace.py").resolve(),
        "research_data_slice": (Path(__file__).resolve().parents[2] / "data" / "research_slice.py").resolve(),
    }
    return {
        k: hashlib.sha256(p.read_bytes()).hexdigest()
        for k, p in sorted(sources.items())
        if p.exists()
    }


def run_factor_exploration_study(
    cfg: FactorExplorationConfig,
    root: Path,
) -> dict[str, Any]:
    """Execute multi-factor Rank IC, IC-IR, and cross-sectional monotonicity study."""
    git_commit = _get_git_commit(root)
    code_sources = _get_code_source_sha256(root)

    req = DataSliceRequest(
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=cfg.symbols,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        as_of_cutoff=cfg.as_of_cutoff,
        price_mode=cfg.price_mode,
        required_fields=("open", "high", "low", "close", "volume"),
    )
    slice_res = get_research_data_slice(req, root=root)

    if slice_res.receipt.get("status") != "ready" or slice_res.data is None:
        blocked = []
        if slice_res.receipt and slice_res.receipt.get("blocked_reasons"):
            for b in slice_res.receipt["blocked_reasons"]:
                code = b.get("code") if isinstance(b, dict) else str(b)
                if code not in blocked:
                    blocked.append(code)
        if not blocked:
            blocked.append("underlying_data_slice_blocked")
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": blocked,
            "hypothesis_name": cfg.hypothesis_name,
            "hypothesis_description": cfg.hypothesis_description,
            "market": cfg.market,
            "pool_id": cfg.pool_id,
            "symbols": list(cfg.symbols),
            "benchmark": cfg.benchmark,
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
            "pit_limitations": [
                "observation_cutoff_verified_not_revision_certified",
                "vendor_availability_timestamps_not_fully_certified",
            ],
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    df = slice_res.data
    close_wide = df.pivot(index="time", columns="symbol", values="close")
    volume_wide = df.pivot(index="time", columns="symbol", values="volume")

    factors_dict = {}
    if "momentum_20" in cfg.factors:
        factors_dict["momentum_20"] = (close_wide / close_wide.shift(20)) - 1.0
    if "volatility_20" in cfg.factors:
        factors_dict["volatility_20"] = close_wide.pct_change(fill_method=None).rolling(20).std()
    if "volume_ratio_20" in cfg.factors:
        factors_dict["volume_ratio_20"] = (volume_wide / volume_wide.rolling(20).mean()) - 1.0

    fwd_ret = (close_wide.shift(-cfg.forward_horizon) / close_wide) - 1.0

    factor_summaries = {}
    primary_mean_ic = 0.0
    primary_ic_ir = 0.0

    sessions = list(close_wide.index)
    for f_name, f_table in factors_dict.items():
        daily_ics = []
        for d in sessions:
            if d not in fwd_ret.index:
                continue
            f_vals = f_table.loc[d]
            r_vals = fwd_ret.loc[d]
            valid = (~f_vals.isna()) & (~r_vals.isna())
            if valid.sum() >= 2:
                ic, _ = stats.spearmanr(f_vals[valid], r_vals[valid])
                if not np.isnan(ic):
                    daily_ics.append(float(ic))

        m_ic = float(np.mean(daily_ics)) if daily_ics else 0.0
        s_ic = float(np.std(daily_ics, ddof=1)) if len(daily_ics) > 1 else 0.0
        ir = float(m_ic / s_ic) if s_ic > 1e-8 else 0.0
        pos_rate = float(np.mean([x > 0 for x in daily_ics])) if daily_ics else 0.0
        factor_summaries[f_name] = {
            "mean_rank_ic": round(m_ic, 4),
            "std_rank_ic": round(s_ic, 4),
            "ic_ir": round(ir, 4),
            "positive_ic_rate": round(pos_rate, 4),
            "observations_count": len(daily_ics),
        }
        if f_name == "momentum_20" or primary_mean_ic == 0.0:
            primary_mean_ic = m_ic
            primary_ic_ir = ir

    latest_time = str(close_wide.index[-1])
    sorted_symbols = sorted(
        cfg.symbols,
        key=lambda s: (factors_dict["momentum_20"].loc[latest_time].get(s) is not None,
                       factors_dict["momentum_20"].loc[latest_time].get(s, float("-inf"))),
        reverse=True,
    ) if "momentum_20" in factors_dict else list(cfg.symbols)

    latest_rankings = {
        sym: {
            "rank": rank + 1,
            **{f_name: round(float(f_table.loc[latest_time, sym]), 6)
               if not pd.isna(f_table.loc[latest_time, sym]) else None
               for f_name, f_table in factors_dict.items()},
        }
        for rank, sym in enumerate(sorted_symbols)
    }

    payload = {
        "schema_version": "1.0",
        "study_id": cfg.study_id,
        "status": "ready",
        "blocked_reasons": [],
        "hypothesis_name": cfg.hypothesis_name,
        "hypothesis_description": cfg.hypothesis_description,
        "market": cfg.market,
        "pool_id": cfg.pool_id,
        "symbols": list(cfg.symbols),
        "benchmark": cfg.benchmark,
        "code_source_sha256": code_sources,
        "experiment_receipt": cfg.to_dict(),
        "data_hash": slice_res.receipt.get("data_hash"),
        "evaluated_sessions_count": len(sessions),
        "mean_rank_ic": round(primary_mean_ic, 4),
        "ic_ir": round(primary_ic_ir, 4),
        "factor_summaries": factor_summaries,
        "latest_rankings": latest_rankings,
        "research_only": True,
        "trade_ready": False,
        "git_commit": git_commit,
        "pit_certified": False,
        "pit_limitations": [
            "observation_cutoff_verified_not_revision_certified",
            "vendor_availability_timestamps_not_fully_certified",
        ],
    }
    raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return payload
