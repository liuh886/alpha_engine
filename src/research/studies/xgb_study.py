"""Cross-Sectional XGBoost Ranking Study Execution Module.

Governed under Track B and ADR-0005.
Implements institutional-grade causal simulation for tree-based ranking:
- Signals are computed strictly at session t-1 close.
- Returns are realized over session (t-1, t].
- In-sample anchor session T_anchor initializes the first Out-of-Sample session.
- Benchmark returns on test day 1 are evaluated from T_anchor close to T_test_start close.
- Full asset weight drift and turnover frictions with terminal liquidation closure.
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
import xgboost as xgb

from src.data.research_slice import DataSliceRequest, get_research_data_slice
from src.research.walkforward.pipeline import SimulationBlockError, _simulate_portfolio
from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker

if TYPE_CHECKING:
    from src.research.study_workspace import CrossSectionalXGBConfig


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
        "xgb_study": Path(__file__).resolve(),
        "study_workspace": (Path(__file__).resolve().parents[1] / "study_workspace.py").resolve(),
        "research_data_slice": (Path(__file__).resolve().parents[2] / "data" / "research_slice.py").resolve(),
        "xgb_native_calibration": (Path(__file__).resolve().parents[1] / "xgb_native_calibration.py").resolve(),
        "walkforward_pipeline": (Path(__file__).resolve().parents[1] / "walkforward" / "pipeline.py").resolve(),
    }
    return {
        k: hashlib.sha256(p.read_bytes()).hexdigest()
        for k, p in sorted(sources.items())
        if p.exists()
    }


def run_cross_sectional_xgb_study(
    cfg: CrossSectionalXGBConfig,
    root: Path,
) -> dict[str, Any]:
    """Execute cross-sectional multi-factor XGBoost ranker study with strict temporal causality."""
    git_commit = _get_git_commit(root)
    code_sources = _get_code_source_sha256(root)

    # 1. Fetch In-Sample training slice
    train_req = DataSliceRequest(
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=cfg.symbols,
        start_date=cfg.train_start,
        end_date=cfg.train_end,
        as_of_cutoff=cfg.train_end,
        price_mode=cfg.price_mode,
        required_fields=("open", "high", "low", "close", "volume"),
    )
    train_res = get_research_data_slice(train_req, root=root)

    # 2. Fetch Out-of-Sample test slice
    test_req = DataSliceRequest(
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=cfg.symbols,
        start_date=cfg.test_start,
        end_date=cfg.test_end,
        as_of_cutoff=cfg.as_of_cutoff,
        price_mode=cfg.price_mode,
        required_fields=("open", "high", "low", "close", "volume"),
    )
    test_res = get_research_data_slice(test_req, root=root)

    # 3. Fetch Benchmark slices (both train and test for continuous anchoring)
    bench_req = DataSliceRequest(
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=(cfg.benchmark,),
        start_date=cfg.train_start,
        end_date=cfg.test_end,
        as_of_cutoff=cfg.as_of_cutoff,
        price_mode=cfg.price_mode,
        required_fields=("open", "high", "low", "close", "volume"),
    )
    bench_res = get_research_data_slice(bench_req, root=root)

    blocked = []
    for s, name in ((train_res, "train_slice"), (test_res, "test_slice"), (bench_res, "benchmark_slice")):
        if s.receipt.get("status") != "ready" or s.data is None:
            reasons = s.receipt.get("blocked_reasons", [])
            if reasons:
                for r in reasons:
                    code = r.get("code") if isinstance(r, dict) else str(r)
                    if code not in blocked:
                        blocked.append(code)
            else:
                blocked.append(f"{name}_blocked")

    if blocked:
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

    # 4. Training Feature Generation & Model Calibration
    train_df = train_res.data
    train_close = train_df.pivot(index="time", columns="symbol", values="close")
    train_volume = train_df.pivot(index="time", columns="symbol", values="volume")

    t_ret5 = train_close.pct_change(5, fill_method=None)
    t_ret20 = train_close.pct_change(20, fill_method=None)
    t_vol20 = train_close.pct_change(1, fill_method=None).rolling(20).std()
    t_vol_ratio20 = train_volume / train_volume.rolling(20).mean() - 1.0
    t_fwd5 = train_close.shift(-5) / train_close - 1.0
    t_fwd5_rank = t_fwd5.rank(axis=1, pct=True)

    valid_train_dates = [
        d for d in train_close.index
        if not pd.isna(t_ret20.loc[d]).any() and not pd.isna(t_fwd5_rank.loc[d]).any()
    ]
    if len(valid_train_dates) < 5:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": ["insufficient_training_sessions"],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "symbols": list(cfg.symbols),
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    rows_x, rows_y, groups_train = [], [], []
    for d in valid_train_dates:
        for sym in cfg.symbols:
            rows_x.append({
                "return_5d": float(t_ret5.loc[d, sym]),
                "return_20d": float(t_ret20.loc[d, sym]),
                "volatility_20d": float(t_vol20.loc[d, sym]),
                "volume_ratio_20d": float(t_vol_ratio20.loc[d, sym]),
            })
            rows_y.append(float(t_fwd5_rank.loc[d, sym]))
        groups_train.append(len(cfg.symbols))

    X_train = pd.DataFrame(rows_x)
    y_train = pd.Series(rows_y)

    calib = XGBNativeCalibration(
        n_gain_bins=int(cfg.xgb_params.get("n_gain_bins", 5)),
        num_boost_round=int(cfg.xgb_params.get("num_boost_round", 20)),
        max_depth=int(cfg.xgb_params.get("max_depth", 3)),
        learning_rate=float(cfg.xgb_params.get("learning_rate", 0.05)),
        seed=int(cfg.xgb_params.get("seed", 42)),
    )
    ranker = fit_xgb_native_daily_ranker(X_train, y_train, groups_train, calibration=calib)
    raw_scores = ranker.model.get_score(importance_type="gain")
    total_gain = sum(raw_scores.values()) if raw_scores else 1.0
    feature_importance = {k: round(v / total_gain, 4) for k, v in sorted(raw_scores.items())}

    # 5. Temporal Causality Setup: In-Sample Anchor Session T_anchor
    train_sessions = sorted(train_df["time"].unique())
    test_sessions = sorted(test_res.data["time"].unique())

    prior_anchor_sessions = [s for s in train_sessions if s <= cfg.train_end and s < cfg.test_start]
    if not prior_anchor_sessions:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": ["missing_prior_anchor_session"],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "symbols": list(cfg.symbols),
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    t_anchor = prior_anchor_sessions[-1]
    all_sim_sessions = [t_anchor, *test_sessions]

    # Warmup feature generation combining IS tail (>= 30 sessions prior to test) with test data
    warmup_sessions_tail = train_sessions[-35:]
    warmup_df = train_df[train_df["time"].isin(warmup_sessions_tail)]
    full_eval_df = pd.concat([warmup_df, test_res.data], ignore_index=True).drop_duplicates(subset=["symbol", "time"])

    full_close = full_eval_df.pivot(index="time", columns="symbol", values="close")
    full_volume = full_eval_df.pivot(index="time", columns="symbol", values="volume")

    f_ret5 = full_close.pct_change(5, fill_method=None)
    f_ret20 = full_close.pct_change(20, fill_method=None)
    f_vol20 = full_close.pct_change(1, fill_method=None).rolling(20).std()
    f_vol_ratio20 = full_volume / full_volume.rolling(20).mean() - 1.0

    # 6. Generate OOS Scores for every session in all_sim_sessions (including T_anchor)
    score_rows: dict[str, dict[str, float]] = {}
    for sess in all_sim_sessions:
        sess_features = []
        for sym in cfg.symbols:
            sess_features.append({
                "return_5d": float(f_ret5.loc[sess, sym]),
                "return_20d": float(f_ret20.loc[sess, sym]),
                "volatility_20d": float(f_vol20.loc[sess, sym]),
                "volume_ratio_20d": float(f_vol_ratio20.loc[sess, sym]),
            })
        dmat = xgb.DMatrix(pd.DataFrame(sess_features))
        preds = ranker.model.predict(dmat)
        score_rows[sess] = {sym: float(preds[i]) for i, sym in enumerate(cfg.symbols)}

    oos_scores_df = pd.DataFrame.from_dict(score_rows, orient="index")

    # 7. Prepare Benchmark Series covering all_sim_sessions
    bench_df = bench_res.data
    bench_close = bench_df.set_index("time")["close"]
    missing_bench = [s for s in all_sim_sessions if s not in bench_close.index]
    if missing_bench:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": [f"missing_benchmark_data_for_anchor_or_test: {missing_bench[:3]}"],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "symbols": list(cfg.symbols),
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    # 8. Causal Institutional Portfolio Simulation via _simulate_portfolio
    friction_per_turnover = (cfg.cost_bps + cfg.slippage_bps) / 10000.0
    try:
        daily_gross, daily_net, daily_turnover, daily_bench = _simulate_portfolio(
            scores=oos_scores_df,
            prices=full_close,
            bench_series=bench_close,
            sessions=all_sim_sessions,
            top_k=cfg.top_k,
            friction_per_turnover=friction_per_turnover,
            liquidate_at_end=True,
        )
    except SimulationBlockError as exc:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": [str(exc)],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "symbols": list(cfg.symbols),
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    # 9. Strictly Causal Rank IC calculation: yesterday's signal predicting today's asset returns
    daily_ic_list: list[float] = []
    for k in range(1, len(all_sim_sessions)):
        prev_sess = all_sim_sessions[k - 1]
        curr_sess = all_sim_sessions[k]
        yesterday_scores = np.array([oos_scores_df.loc[prev_sess, sym] for sym in cfg.symbols])
        today_realized_returns = np.array([
            (float(full_close.loc[curr_sess, sym]) / float(full_close.loc[prev_sess, sym])) - 1.0
            for sym in cfg.symbols
        ])
        ic_val, _ = stats.spearmanr(yesterday_scores, today_realized_returns)
        if not np.isnan(ic_val):
            daily_ic_list.append(float(ic_val))

    mean_ic = float(np.mean(daily_ic_list)) if daily_ic_list else 0.0
    std_ic = float(np.std(daily_ic_list, ddof=1)) if len(daily_ic_list) > 1 else 0.0
    ic_ir = float(mean_ic / std_ic) if std_ic > 1e-8 else 0.0

    # 10. Compounding & Drawdown with Initial Baseline 1.0
    comp_strategy = 1.0
    comp_bench = 1.0
    strat_curve = [1.0]
    bench_curve = [1.0]

    for r_s, r_b in zip(daily_net, daily_bench):
        comp_strategy *= (1.0 + r_s)
        comp_bench *= (1.0 + r_b)
        strat_curve.append(comp_strategy)
        bench_curve.append(comp_bench)

    strat_cum_net = comp_strategy - 1.0
    bench_cum_ret = comp_bench - 1.0
    gross_cum_ret = float(np.prod(1.0 + np.array(daily_gross)) - 1.0)

    # Maximum Drawdown from 1.0 baseline
    peak = 1.0
    max_dd = 0.0
    for val in strat_curve:
        if val > peak:
            peak = val
        dd = (val - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Annualized Sharpe Ratio
    rets = np.array(daily_net)
    mean_ret = np.mean(rets)
    std_ret = np.std(rets, ddof=1)
    sharpe = float(mean_ret / std_ret * np.sqrt(252)) if std_ret > 1e-8 else 0.0

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
        "train_data_hash": train_res.receipt.get("data_hash"),
        "test_data_hash": test_res.receipt.get("data_hash"),
        "oos_sessions_count": len(test_sessions),
        "overall_oos_gross_return": round(gross_cum_ret, 4),
        "overall_oos_net_return": round(strat_cum_net, 4),
        "overall_benchmark_cumulative_return": round(bench_cum_ret, 4),
        "overall_oos_net_excess_return": round(strat_cum_net - bench_cum_ret, 4),
        "overall_oos_sharpe_ratio": round(sharpe, 4),
        "overall_oos_max_drawdown": round(max_dd, 4),
        "rank_ic": round(mean_ic, 4),
        "ic_ir": round(ic_ir, 4),
        "feature_importance": feature_importance,
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
