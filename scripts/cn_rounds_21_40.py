"""CN x1.1 R21-40: sector/name fine grid, more factor groups, combined optimization."""
from __future__ import annotations
import json, math
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd, yaml

from src.research.daily_ranker import prepare_ranker_frame
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import load_window_benchmark_returns, normalize_qlib_frame_index
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window
from src.research.xgb_native_calibration import XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker

FACTOR_LIB = Path("configs/factor_libraries/ohlcv.yaml")
SECTOR_CFG = Path("configs/research_classifications/cn130_sector_industry_v1.yaml")
UNIVERSE_CFG = Path("configs/research_universes/cn_selected_equities_v3.yaml")
WINDOWS = ("2024H1","2024H2","2025H1","2025H2")
RET = "Ref($close, -10) / $close - 1"
BM = "000300"

def _load_yaml(p): d=yaml.safe_load(Path(p).read_text(encoding="utf-8")); return d if isinstance(d,dict) else {}
def _compound(v): return math.prod(1.0+x for x in v)-1.0

def load_sectors():
    raw=_load_yaml(SECTOR_CFG); return {str(k):str(v.get("sector","Unknown")) for k,v in raw.get("symbols",{}).items()}

def get_exprs(groups):
    lib=load_factor_library(FACTOR_LIB); sel=select_factor_groups(lib,groups)
    e,s=[],set()
    for g in sel:
        for f in g.factors:
            if f.expression not in s: e.append(f.expression); s.add(f.expression)
    return e

def eval_sector_port(scores,returns,bench,smap,edates,ns=3,nn=1,cost=20,cad=10):
    rd=[edates[i] for i in range(0,len(edates),cad)]; pr=[]
    for d in rd:
        try: ds=scores.xs(d,level="datetime"); dr=returns.xs(d,level="datetime")
        except KeyError: continue
        if len(ds)<ns: continue
        ss=defaultdict(list)
        for inst,row in ds.iterrows(): ss[smap.get(str(inst),"Unknown")].append(float(row["score"]))
        sa={sec:np.mean(sc) for sec,sc in ss.items() if len(sc)>=nn}
        ts=sorted(sa,key=lambda s:sa[s],reverse=True)[:ns]
        sel=[]
        for sec in ts:
            stocks=[(str(i),ds.loc[str(i),"score"]) for i in ss[sec] if str(i) in dr.index]
            stocks.sort(key=lambda x:x[1],reverse=True)
            for inst,_ in stocks[:nn]: sel.append(inst)
        if not sel: sel=[str(s) for s in ds.sort_values("score",ascending=False).index[:ns*nn]]
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

# Best calibration from Phase C
BEST_CAL = XGBNativeCalibration.from_dict({"n_gain_bins":5,"num_boost_round":300,"max_leaves":31,"max_depth":0,"min_child_weight":1.0,"learning_rate":0.03,"subsample":0.8,"colsample_bytree":0.8,"reg_alpha":0.0,"reg_lambda":1.0,"seed":42})

# R21-40 configs
CONFIGS = [
    # R21-26: More sector/name combos
    ("r21_s2_n1",["cn_balanced_ohlcv"],BEST_CAL,2,1,"R21_port"),
    ("r22_s2_n2",["cn_balanced_ohlcv"],BEST_CAL,2,2,"R22_port"),
    ("r23_s3_n3",["cn_balanced_ohlcv"],BEST_CAL,3,3,"R23_port"),
    ("r24_s5_n1",["cn_balanced_ohlcv"],BEST_CAL,5,1,"R24_port"),
    ("r25_s5_n2",["cn_balanced_ohlcv"],BEST_CAL,5,2,"R25_port"),
    ("r26_s6_n2",["cn_balanced_ohlcv"],BEST_CAL,6,2,"R26_port"),
    # R27-32: Factor group variants with best cal
    ("r27_balanced_only",["cn_balanced_ohlcv"],BEST_CAL,3,1,"R27_factor"),
    ("r28_pressure",["cn_balanced_ohlcv","cn_price_volume_pressure"],BEST_CAL,3,1,"R28_factor"),
    ("r29_volrev",["cn_balanced_ohlcv","cn_volatility_reversal"],BEST_CAL,3,1,"R29_factor"),
    ("r30_revliq",["cn_balanced_ohlcv","cn_short_reversal_liquidity"],BEST_CAL,3,1,"R30_factor"),
    ("r31_all_groups",["cn_balanced_ohlcv","cn_volatility_reversal","cn_price_volume_pressure","cn_short_reversal_liquidity"],BEST_CAL,3,1,"R31_factor"),
    ("r32_pressure_revliq",["cn_balanced_ohlcv","cn_price_volume_pressure","cn_short_reversal_liquidity"],BEST_CAL,3,1,"R32_factor"),
    # R33-38: Top-K variants (no sector)
    ("r33_top10",["cn_balanced_ohlcv"],BEST_CAL,None,None,"R33_topk"),
    ("r34_top12",["cn_balanced_ohlcv"],BEST_CAL,None,None,"R34_topk"),
    ("r35_top20",["cn_balanced_ohlcv"],BEST_CAL,None,None,"R35_topk"),
    ("r36_top8",["cn_balanced_ohlcv"],BEST_CAL,None,None,"R36_topk"),
    ("r37_top25",["cn_balanced_ohlcv"],BEST_CAL,None,None,"R37_topk"),
    ("r38_top15_baseline",["cn_balanced_ohlcv"],BEST_CAL,None,None,"R38_topk"),
    # R39-40: Combined best
    ("r39_s2_n1_pressure",["cn_balanced_ohlcv","cn_price_volume_pressure"],BEST_CAL,2,1,"R39_combo"),
    ("r40_s3_n1_all",["cn_balanced_ohlcv","cn_volatility_reversal","cn_price_volume_pressure","cn_short_reversal_liquidity"],BEST_CAL,3,1,"R40_combo"),
]

def main():
    root=Path.cwd()
    universe=_load_yaml(UNIVERSE_CFG); smap=load_sectors()
    runtime=QlibCNExecutionRuntime(provider_uri="data/providers/cn"); runtime.initialize(root)
    req=[str(s) for s in universe.get("symbols",[])]
    av=runtime.available_symbols()
    norm=normalize_market_symbols("cn",req,available_symbols=av)
    symbols=[i.normalized_symbol for i in norm if i.normalized_symbol in av]
    print(f"Symbols: {len(symbols)}")

    config_exprs={}
    for cid,groups,_,_,_,_ in CONFIGS: config_exprs[cid]=get_exprs(groups)
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
        bench=load_window_benchmark_returns(runtime,benchmark_instrument=BM,return_expression=RET,evaluation_dates=ed,start=ed.min().strftime("%Y-%m-%d"),end=ed.max().strftime("%Y-%m-%d"),provenance="raw_forward_return",horizon=10)

        for cid,groups,cal,ns,nn,tag in CONFIGS:
            ei=[e2i[e] for e in config_exprs[cid]]; nf=len(ei)
            cf=fa.iloc[:,ei].copy(); cf.columns=[f"f{i}" for i in range(nf)]
            cft=cf.loc[tm].copy(); rt=ra.loc[tm].copy()
            cft,rt=purge_training_tail(cft,rt,holding_days=10)
            v,_=validate_no_nan_inputs(cft,context=f"{window.label}/{cid}")
            if not v: continue
            xr,yr,gr=prepare_ranker_frame(cft,rt)
            fitted=fit_xgb_native_daily_ranker(xr,yr,gr,calibration=cal)
            cfe=fa.loc[testm].iloc[:,ei].copy(); cfe.columns=[f"f{i}" for i in range(nf)]
            scores=predict_xgb_native_daily_ranker(fitted,cfe); rte=ra.loc[testm].copy()
            for cost in (20,60):
                if ns is None:  # Top-K without sector
                    res=eval_sector_port(scores,rte,bench,{s:"All" for s in symbols},ed,ns=1,nn=15 if nn is None else max(ns or 15,nn or 1),cost=cost)
                else: res=eval_sector_port(scores,rte,bench,smap,ed,ns=ns,nn=nn,cost=cost)
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
        ce=sn/bn-1.0; dd=min(r["max_drawdown"] for r in o)
        e60=None
        if len(data["w60"])==4:
            o60=[data["w60"][w] for w in WINDOWS]
            e60=math.prod(1.0+r["strategy_compound"] for r in o60)/math.prod(1.0+r["benchmark_compound"] for r in o60)-1.0
        agg.append({"config":cid,"tag":o[0]["tag"],"exc20":ce,"exc60":e60,"dd":dd,"pw":{r["window"]:{"exc":r["relative_excess"],"dd":r["max_drawdown"]} for r in o}})

    agg.sort(key=lambda r:r["exc20"],reverse=True)
    print(f"\nCNx R21-40 Results:")
    for r in agg:
        e60s=f'{r["exc60"]:.4f}' if r["exc60"] else 'N/A'
        print(f"  {r['config']:<25s} {r['tag']:<12s} exc20={r['exc20']:.4f} dd={r['dd']:.4f} exc60={e60s}")

    out=Path("artifacts/evidence/cn_rounds_21_40_v1/results.json"); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(agg,indent=2,default=str))
    print(f"\nSaved to {out}")

if __name__=="__main__": main()
