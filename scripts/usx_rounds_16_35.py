"""USx R16-35: sector cap fine-tuning, bottom-N exclusion, factor combos, Top-K variants."""
from __future__ import annotations
import json, math, sys
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd, yaml

from src.research.daily_ranker import prepare_ranker_frame
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import load_window_benchmark_returns, normalize_qlib_frame_index
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window
from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker

FACTOR_LIB = Path("configs/factor_libraries/ohlcv.yaml")
SECTOR_CFG = Path("configs/research_classifications/us87_sector_industry_v1.yaml")
UNIVERSE_CFG = Path("configs/research_universes/us_selected_equities_v2.yaml")
WINDOWS = ("2024H1","2024H2","2025H1","2025H2")
RET = "Ref($close, -10) / $close - 1"

def _load_yaml(p): d=yaml.safe_load(Path(p).read_text(encoding="utf-8")); return d if isinstance(d,dict) else {}
def _compound(v): return math.prod(1.0+x for x in v)-1.0

def load_sectors():
    raw=_load_yaml(SECTOR_CFG); return {str(k):str(v.get("sector","Unknown")) for k,v in raw.get("records",{}).items()}

def get_exprs(groups):
    lib=load_factor_library(FACTOR_LIB); sel=select_factor_groups(lib,groups)
    e,s=[],set()
    for g in sel:
        for f in g.factors:
            if f.expression not in s: e.append(f.expression); s.add(f.expression)
    return e

def select_capped(ranked, smap, tn=15, mps=4):
    selected,counts=[],{}
    for _,row in ranked.sort_values("score",ascending=False).iterrows():
        sym=str(row["instrument"]); sec=smap.get(sym,"Unknown")
        if counts.get(sec,0)>=mps: continue
        selected.append(sym); counts[sec]=counts.get(sec,0)+1
        if len(selected)>=tn: break
    if len(selected)<tn:
        for _,row in ranked.sort_values("score",ascending=False).iterrows():
            sym=str(row["instrument"])
            if sym not in selected: selected.append(sym)
            if len(selected)>=tn: break
    return selected[:tn]

def select_bottom_exclude(ranked, tn=15, bn=5):
    all_syms=ranked.sort_values("score",ascending=False)
    exclude=set(str(s) for s in all_syms["instrument"].iloc[-bn:])
    selected=[str(s) for _,s in all_syms.iterrows() if str(s["instrument"]) not in exclude][:tn]
    return selected

def eval_port(scores, returns, bench, smap, edates, tn=15, mps=4, bn=0, cost=20, cad=10):
    rd=[edates[i] for i in range(0,len(edates),cad)]
    pr=[]
    for d in rd:
        try:
            ds=scores.xs(d,level="datetime"); dr=returns.xs(d,level="datetime")
        except KeyError: continue
        dsdf=ds.reset_index(); dsdf.columns=["instrument","score"]
        if bn>0: sel=select_bottom_exclude(dsdf,tn,bn)
        elif mps: sel=select_capped(dsdf,smap,tn,mps)
        else: sel=[str(s) for s in dsdf.sort_values("score",ascending=False)["instrument"].iloc[:tn]]
        sr=dr[dr.index.isin(sel)]
        if len(sr)==0: continue
        cf=1.0-(cost/10000.0)/cad; pr.append(float(sr["return"].mean())*cf)
    if not pr: return None
    ps=pd.Series(pr,index=pd.DatetimeIndex([rd[i] for i in range(len(pr))]))
    cm=ps.index.intersection(bench.index)
    if len(cm)==0: return None
    pa=ps[cm]; ba=bench.loc[cm,"return"]
    sc=_compound([float(r) for r in pa]); bc=_compound([float(r) for r in ba])
    re=(1.0+sc)/(1.0+bc)-1.0
    cum=(1.0+pa).cumprod(); dd=float(((cum-cum.cummax())/cum.cummax()).min())
    return {"strategy_compound":float(sc),"benchmark_compound":float(bc),"relative_excess":float(re),"max_drawdown":float(dd),"n_periods":len(pa)}

# Models to test
BEST_CAL = XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":300,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})
STD_CAL = XGBNativeCalibration.from_dict({"n_gain_bins":7,"num_boost_round":200,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.05,"subsample":1.0,"colsample_bytree":1.0,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})

# R16-20: Sector cap granularity + bottom-N
# R21-25: Factor combos with best cal
# R26-30: Top-K variants with best cal + sector cap
# R31-35: Combined extremes

CONFIGS = [
    # R16-20: Sector cap variants
    ("r16_cap2", ["momentum_volatility_volume"], BEST_CAL, 15, 2, 0, "R16_sector"),
    ("r17_cap3", ["momentum_volatility_volume"], BEST_CAL, 15, 3, 0, "R17_sector"),
    ("r18_cap5", ["momentum_volatility_volume"], BEST_CAL, 15, 5, 0, "R18_sector"),
    ("r19_cap6", ["momentum_volatility_volume"], BEST_CAL, 15, 6, 0, "R19_sector"),
    ("r20_bottom5", ["momentum_volatility_volume"], BEST_CAL, 15, None, 5, "R20_bottom"),
    # R21-25: Factor combos
    ("r21_mvv_rev", ["momentum_volatility_volume"], BEST_CAL, 15, 4, 0, "R21_factor"),
    ("r22_mvv_meanrev", ["momentum_volatility_volume"], BEST_CAL, 15, 4, 0, "R22_factor"),
    ("r23_all_groups", ["momentum_volatility_volume","risk_controlled_momentum"], BEST_CAL, 15, 4, 0, "R23_factor"),
    ("r24_baseline_extended", ["momentum_volatility_volume"], BEST_CAL, 15, 4, 0, "R24_baseline"),
    ("r25_std_cal", ["momentum_volatility_volume"], STD_CAL, 15, 4, 0, "R25_baseline"),
    # R26-30: Top-K variants
    ("r26_top10_cap4", ["momentum_volatility_volume"], BEST_CAL, 10, 4, 0, "R26_topk"),
    ("r27_top12_cap4", ["momentum_volatility_volume"], BEST_CAL, 12, 4, 0, "R27_topk"),
    ("r28_top20_cap4", ["momentum_volatility_volume"], BEST_CAL, 20, 4, 0, "R28_topk"),
    ("r29_top15_cap3_bottom5", ["momentum_volatility_volume"], BEST_CAL, 15, 3, 5, "R29_combo"),
    ("r30_top12_cap3", ["momentum_volatility_volume"], BEST_CAL, 12, 3, 0, "R30_topk"),
    # R31-35: Extreme/combined
    ("r31_top10_cap2", ["momentum_volatility_volume"], BEST_CAL, 10, 2, 0, "R31_extreme"),
    ("r32_top15_cap8", ["momentum_volatility_volume"], BEST_CAL, 15, 8, 0, "R32_loose"),
    ("r33_top20_cap6", ["momentum_volatility_volume"], BEST_CAL, 20, 6, 0, "R33_broad"),
    ("r34_top15_cap4_bottom10", ["momentum_volatility_volume"], BEST_CAL, 15, 4, 10, "R34_bottom"),
    ("r35_top15_cap4_nosec", ["momentum_volatility_volume"], BEST_CAL, 15, None, 0, "R35_uncapped"),
]

# Custom factor expressions for R21, R22
REV_IDS = ["ohlcv.reversal.inv_ret_1d","ohlcv.reversal.inv_ret_3d","ohlcv.reversal.inv_ret_5d"]
MEANREV_IDS = ["ohlcv.mean_reversion.close_vs_ma_5d","ohlcv.mean_reversion.close_vs_ma_10d","ohlcv.mean_reversion.close_vs_ma_20d"]

def get_custom_exprs(base_groups, extra_ids):
    raw=_load_yaml(FACTOR_LIB); factors_raw=raw.get("factors",{})
    base_e=get_exprs(base_groups); seen=set(base_e)
    for fid in extra_ids:
        if fid in factors_raw and factors_raw[fid]["expression"] not in seen:
            base_e.append(factors_raw[fid]["expression"]); seen.add(factors_raw[fid]["expression"])
    return base_e

def main():
    root=Path.cwd()
    universe=_load_yaml(UNIVERSE_CFG); smap=load_sectors()
    runtime=QlibUSExecutionRuntime(provider_uri="data/providers/us"); runtime.initialize(root)
    requested=[str(s) for s in universe.get("symbols",[])]
    available=runtime.available_symbols()
    normalized=normalize_market_symbols("us",requested,available_symbols=available)
    symbols=[i.normalized_symbol for i in normalized]
    print(f"Symbols: {len(symbols)}")

    # Pre-compute expressions per config
    config_exprs={}
    for cid,groups,_,_,_,_,_ in CONFIGS:
        if cid=="r21_mvv_rev": config_exprs[cid]=get_custom_exprs(groups,REV_IDS)
        elif cid=="r22_mvv_meanrev": config_exprs[cid]=get_custom_exprs(groups,MEANREV_IDS)
        else: config_exprs[cid]=get_exprs(groups)
        print(f"  {cid}: {len(config_exprs[cid])} factors")

    all_e=set(); [all_e.update(v) for v in config_exprs.values()]
    all_exprs=sorted(all_e); e2i={e:i for i,e in enumerate(all_exprs)}

    cal=runtime.calendar("2021-01-01","2025-12-31")
    ae=min(pd.Timestamp("2025-12-31"),cal.max()).strftime("%Y-%m-%d")
    wp=build_window_sampling_plan(cal,"2021-01-01",ae,first_test_year=2024,last_test_year=2025,min_complete_windows=4,partial_window_policy="complete_windows_only",min_partial_window_eligible_sessions=None,horizon_sessions=10,cadence_sessions=10)
    windows=list(wp.selected_windows)
    edbw=horizon_eligible_dates_by_window(wp,cal)

    all_results=[]
    for window in windows:
        ed=edbw[window.label]
        print(f"\nWindow: {window.label} ({len(ed)} dates)")
        fa=normalize_qlib_frame_index(runtime.features(symbols,all_exprs,window.train_start,window.test_end)).replace([np.inf,-np.inf],np.nan)
        fa.columns=[f"f{i}" for i in range(len(all_exprs))]
        ra=normalize_qlib_frame_index(runtime.features(symbols,[RET],window.train_start,window.test_end))
        ra.columns=["return"]
        d=fa.index.get_level_values("datetime"); tm=(d>=pd.Timestamp(window.train_start))&(d<=pd.Timestamp(window.train_end)); testm=d.isin(ed)
        bench=load_window_benchmark_returns(runtime,benchmark_instrument="QQQ",return_expression=RET,evaluation_dates=ed,start=ed.min().strftime("%Y-%m-%d"),end=ed.max().strftime("%Y-%m-%d"),provenance="raw_forward_return",horizon=10)

        for cid,groups,cal,tn,mps,bn,tag in CONFIGS:
            ei=[e2i[e] for e in config_exprs[cid]]
            cf=fa.iloc[:,ei].copy(); cf.columns=[f"f{i}" for i in range(len(ei))]
            cft=cf.loc[tm].copy(); rt=ra.loc[tm].copy()
            cft,rt=purge_training_tail(cft,rt,holding_days=10)
            v,_=validate_no_nan_inputs(cft,context=f"{window.label}/{cid}")
            if not v: continue
            xr,yr,gr=prepare_ranker_frame(cft,rt)
            fitted=fit_xgb_native_daily_ranker(xr,yr,gr,calibration=cal)
            cfe=fa.loc[testm].iloc[:,ei].copy(); cfe.columns=[f"f{i}" for i in range(len(ei))]
            scores=predict_xgb_native_daily_ranker(fitted,cfe)
            rte=ra.loc[testm].copy()
            for cost in (20,60):
                res=eval_port(scores,rte,bench,smap,ed,tn=tn,mps=mps,bn=bn,cost=cost)
                if res is None: continue
                res["config"]=cid; res["window"]=window.label; res["cost"]=cost; res["tag"]=tag
                all_results.append(res)

        w20=[r for r in all_results if r["window"]==window.label and r["cost"]==20]
        w20.sort(key=lambda r:r["relative_excess"],reverse=True)
        for r in w20[:3]: print(f"  {r['config']}: exc={r['relative_excess']:.4f} dd={r['max_drawdown']:.4f}")

    # Aggregate
    by_c=defaultdict(lambda:{"w20":{},"w60":{}})
    for r in all_results:
        if r["cost"]==20: by_c[r["config"]]["w20"][r["window"]]=r
        else: by_c[r["config"]]["w60"][r["window"]]=r
    agg=[]
    for cid,data in by_c.items():
        if len(data["w20"])!=4: continue
        o=[data["w20"][w] for w in WINDOWS]
        sn=math.prod(1.0+r["strategy_compound"] for r in o); bn=math.prod(1.0+r["benchmark_compound"] for r in o)
        ce=sn/bn-1.0; dd=min(r["max_drawdown"] for r in o); pos=sum(1 for r in o if r["relative_excess"]>0)
        ss=max(r["relative_excess"] for r in o)/sum(r["relative_excess"] for r in o if r["relative_excess"]>0) if sum(r["relative_excess"] for r in o if r["relative_excess"]>0)>0 else 1.0
        e60=None
        if len(data["w60"])==4:
            o60=[data["w60"][w] for w in WINDOWS]
            e60=math.prod(1.0+r["strategy_compound"] for r in o60)/math.prod(1.0+r["benchmark_compound"] for r in o60)-1.0
        agg.append({"config":cid,"tag":o[0]["tag"],"exc20":ce,"exc60":e60,"dd":dd,"pos":pos,"share":ss,"pw":{r["window"]:{"exc":r["relative_excess"],"dd":r["max_drawdown"]} for r in o}})

    agg.sort(key=lambda r:r["exc20"],reverse=True)
    print(f"\nUSx R16-35 Results:")
    for r in agg:
        e60s=f'{r["exc60"]:.4f}' if r["exc60"] else 'N/A'
        print(f"  {r['config']:<25s} {r['tag']:<12s} exc20={r['exc20']:.4f} dd={r['dd']:.4f} exc60={e60s} pos={r['pos']}")

    out=Path("artifacts/evidence/usx_rounds_16_35_v1/results.json"); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(agg,indent=2,default=str))
    print(f"\nSaved to {out}")

if __name__=="__main__": main()
