"""QQQR R31-50: SGOV 50-100% sweep, state 1 fine-tuning, state 2 SGOV buffer, combined."""
from __future__ import annotations
import json, math
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd

BACKTEST = Path("data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json")
COST = 10.0; ASSETS = ["QQQI","QQQ","TQQQ","SGOV"]

def load():
    d=json.loads(BACKTEST.read_text(encoding="utf-8"))
    report=pd.DataFrame(d["report"]); report["date"]=pd.to_datetime(report["date"])
    positions=pd.DataFrame(d["positions"]); positions["date"]=pd.to_datetime(positions["date"])
    ar={}
    for a in ["QQQI","QQQ","TQQQ"]:
        ap=positions[positions["instrument"]==a].set_index("date")["price"]
        ar[a]=ap.pct_change().fillna(0.0)
    ar["SGOV"]=pd.Series(0.0,index=ar["QQQ"].index)
    rf=pd.DataFrame(ar).reindex(report["date"]).fillna(0.0)
    return report, rf

def compute(report,rf,s0,s1,s2,panic,defense_split):
    daily=report[["date","position_state","panic_repair_active","slow_bear_defense_active","bench_qqq"]].copy().set_index("date")
    w=pd.DataFrame(0.0,index=daily.index,columns=ASSETS)
    for i in range(len(daily)):
        st=int(daily["position_state"].iloc[i])
        ws={0:s0,1:s1,2:s2}.get(st,s0)
        for a in ASSETS: w.iloc[i,w.columns.get_loc(a)]=ws.get(a,0.0)
        if daily["panic_repair_active"].iloc[i] and panic>0 and st in(0,1):
            ct=ws.get("TQQQ",0.0); cq=ws.get("QQQI",0.0)
            b=min(panic,cq); w.iloc[i,w.columns.get_loc("TQQQ")]=ct+b; w.iloc[i,w.columns.get_loc("QQQI")]=cq-b
        if daily["slow_bear_defense_active"].iloc[i]:
            qp,sp=defense_split; w.iloc[i,w.columns.get_loc("QQQI")]=qp; w.iloc[i,w.columns.get_loc("SGOV")]=sp
            for a in["QQQ","TQQQ"]: w.iloc[i,w.columns.get_loc(a)]=0.0
    arf=rf.reindex(daily.index).fillna(0.0)
    gr=(w.values*arf.values).sum(axis=1)
    wc=w.diff().abs().sum(axis=1); wc.iloc[0]=w.iloc[0].abs().sum()
    tc=wc*COST/10000.0; nr=gr-tc.values
    eq=(1.0+pd.Series(nr,index=daily.index)).cumprod()
    dd=float((eq/eq.cummax()-1.0).min()); tr=float(eq.iloc[-1]-1.0)
    nd=len(daily); ny=max(nd/252.0,0.01)
    cagr=float(eq.iloc[-1]**(1.0/ny)-1.0)
    av=float(pd.Series(nr).std()*np.sqrt(252))
    sh=float(cagr/av) if av>0 else 0.0
    cm=float(cagr/abs(dd)) if dd!=0 else 0.0
    br=float(daily["bench_qqq"].iloc[-1]/daily["bench_qqq"].iloc[0]-1.0)
    return {"total_return":tr,"cagr":cagr,"max_drawdown":dd,"sharpe":sh,"calmar":cm,"excess":tr-br,"cost":float(tc.sum()),"turnover":float(wc.sum())}

def main():
    report,rf=load()
    # Baseline R975
    s0b={"QQQI":0.5,"QQQ":0.0,"TQQQ":0.0,"SGOV":0.5}
    s1b={"QQQI":0.9,"QQQ":0.1,"TQQQ":0.0,"SGOV":0.0}
    s2b={"QQQI":0.0,"QQQ":0.0,"TQQQ":1.0,"SGOV":0.0}
    bl=compute(report,rf,s0b,s1b,s2b,0.0,(0.75,0.25))
    print(f"R975 baseline: Calmar={bl['calmar']:.4f} CAGR={bl['cagr']:.4f} DD={bl['max_drawdown']:.4f}")

    results=[]
    # R31-40: SGOV sweep 55-100%
    for i,sg in enumerate(range(55,105,5)):
        qq=round(1.0-sg/100.0,2)
        s0={**s0b,"QQQI":qq,"SGOV":sg/100.0}
        r=compute(report,rf,s0,s1b,s2b,0.0,(0.75,0.25))
        r["label"]=f"R{31+i}_s0_sgov{sg}"; results.append(r)

    # R41-45: State 1 fine-tuning
    for i,(qqi,qqq) in enumerate([(0.92,0.08),(0.95,0.05),(0.97,0.03),(0.98,0.02),(1.0,0.0)]):
        s1={**s1b,"QQQI":qqi,"QQQ":qqq}
        r=compute(report,rf,s0b,s1,s2b,0.0,(0.75,0.25))
        r["label"]=f"R{41+i}_s1_qqqi{int(qqi*100)}"; results.append(r)

    # R46-48: State 2 SGOV buffer
    for i,(tq,sg) in enumerate([(0.95,0.05),(0.90,0.10),(0.85,0.15)]):
        s2={"QQQI":0.0,"QQQ":0.0,"TQQQ":tq,"SGOV":sg}
        r=compute(report,rf,s0b,s1b,s2,0.0,(0.75,0.25))
        r["label"]=f"R{46+i}_s2_tqqq{int(tq*100)}_sgov{int(sg*100)}"; results.append(r)

    # R49-50: Combined best of best
    # Best SGOV from R31-40
    sgov_best=max([r for r in results if "s0_sgov" in r["label"]],key=lambda r:r["calmar"])
    sgov_pct=int(sgov_best["label"].split("sgov")[-1])
    best_s0={"QQQI":round(1.0-sgov_pct/100.0,2),"QQQ":0.0,"TQQQ":0.0,"SGOV":sgov_pct/100.0}
    # Best S1 from R41-45
    s1_best=max([r for r in results if "s1_" in r["label"]],key=lambda r:r["calmar"])
    qqi_pct=int(s1_best["label"].split("qqqi")[-1])
    best_s1={"QQQI":qqi_pct/100.0,"QQQ":round(1.0-qqi_pct/100.0,2),"TQQQ":0.0,"SGOV":0.0}

    r49=compute(report,rf,best_s0,best_s1,s2b,0.0,(0.75,0.25))
    r49["label"]="R49_best_s0_s1"; results.append(r49)
    r50=compute(report,rf,best_s0,best_s1,s2b,0.0,(0.8,0.2))
    r50["label"]="R50_best_all_def80"; results.append(r50)

    # Sort and display
    results.sort(key=lambda r:r["calmar"],reverse=True)
    print(f"\nQQQR R31-50 Results:")
    for r in results:
        print(f"  {r['label']:<30s} Calmar={r['calmar']:.4f} CAGR={r['cagr']:.4f} DD={r['max_drawdown']:.4f} Sharpe={r['sharpe']:.4f} Cost={r['cost']:.4f}")

    best=results[0]
    print(f"\nBEST: {best['label']} Calmar={best['calmar']:.4f} (vs R975: {bl['calmar']:.4f}, +{(best['calmar']/bl['calmar']-1)*100:.1f}%)")

    out=Path("artifacts/evidence/qqqr_rounds_31_50_v1/results.json"); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"r975_baseline":bl,"results":[{k:v for k,v in r.items()} for r in results],"best":best["label"]},indent=2,default=str))

if __name__=="__main__": main()
