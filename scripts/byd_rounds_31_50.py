"""BYD R31-50: defense finer sweep, momentum thresholds, multi-ETF, combined extremes."""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np, pandas as pd

BACKTEST = Path("data/research/formal_backtests/byd_v1_2_convex_momentum_budget_v1.json")
COST = 20.0

def load():
    d=json.loads(BACKTEST.read_text(encoding="utf-8"))
    report=pd.DataFrame(d["report"]); report["date"]=pd.to_datetime(report["date"])
    positions=pd.DataFrame(d["positions"]); positions["date"]=pd.to_datetime(positions["date"])
    byd=positions[positions["instrument"]=="BYD"].set_index("date")["price"]
    etf=positions[positions["instrument"]=="515180.SH"].set_index("date")["price"]
    br=byd.pct_change().fillna(0.0); er=etf.pct_change().fillna(0.0)
    rf=pd.DataFrame({"BYD":br,"515180":er}).reindex(report["date"]).fillna(0.0)
    return report, rf

def mom_scale(m20,fi,cp,mf):
    if m20<=0: return 0.0,0.0
    s=min(1.0,m20/fi)**cp; inc=s*mf; return s,inc

def compute(report,rf,def_byd,off_byd,exp_max,fi,cp,mf,mom_entry,mom_exit,cost):
    daily=report[["date","momentum_20","benchmark_return"]].copy().set_index("date")
    wb,we,wc=[],[],[]
    for i in range(len(daily)):
        m20=float(daily["momentum_20"].iloc[i])
        s,inc=mom_scale(max(0.0,m20),fi,cp,mf)
        if m20>mom_entry: tb=min(off_byd+inc,exp_max); wb.append(tb); we.append(0.0); wc.append(1.0-tb)
        elif m20<=mom_exit: wb.append(def_byd); we.append(1.0-def_byd); wc.append(0.0)
        else: wb.append(def_byd); we.append(1.0-def_byd); wc.append(0.0)
    wdf=pd.DataFrame({"BYD":wb,"515180":we,"cash":wc},index=daily.index)
    ar=rf.reindex(daily.index).fillna(0.0)
    gr=(wdf["BYD"].values*ar["BYD"].values+wdf["515180"].values*ar["515180"].values)
    wch=pd.DataFrame({"BYD":abs(wdf["BYD"].diff().fillna(0)),"515180":abs(wdf["515180"].diff().fillna(0))}).sum(axis=1)
    wch.iloc[0]=abs(wdf["BYD"].iloc[0])+abs(wdf["515180"].iloc[0])
    tc=wch*cost/10000.0
    fin=np.maximum(np.array(wb)-1.0,0.0); fcost=fin*0.06/252.0
    nr=gr-tc.values-fcost
    eq=(1.0+pd.Series(nr,index=daily.index)).cumprod()
    dd=float((eq/eq.cummax()-1.0).min()); tr=float(eq.iloc[-1]-1.0)
    ny=max(len(daily)/252.0,0.01); cagr=float(eq.iloc[-1]**(1.0/ny)-1.0)
    av=float(pd.Series(nr).std()*np.sqrt(252)); sh=float(cagr/av) if av>0 else 0.0
    cm=float(cagr/abs(dd)) if dd!=0 else 0.0
    return {"total_return":tr,"cagr":cagr,"max_drawdown":dd,"sharpe":sh,"calmar":cm,"cost":float(tc.sum()+fcost.sum()),"turnover":float(wch.sum())}

def main():
    report,rf=load()
    bl=compute(report,rf,0.0,1.0,1.125,0.15,4.0,0.125,0.0,0.0,COST)
    print(f"R3 baseline: Calmar={bl['calmar']:.4f} CAGR={bl['cagr']:.4f} DD={bl['max_drawdown']:.4f}")

    results=[]
    # R31-38: Defense finer sweep + momentum thresholds
    for i,(db,me,mx) in enumerate([(0.0,0.0,0.0),(0.1,0.0,0.0),(0.2,0.0,0.0),(0.3,-0.02,-0.02),(0.4,-0.05,-0.05),(0.0,0.02,-0.02),(0.0,0.05,-0.05),(0.25,-0.02,0.0)]):
        r=compute(report,rf,db,1.0,1.125,0.15,4.0,0.125,me,mx,COST)
        r["label"]=f"R{31+i}_def{int(db*100):d}_entry{int(me*100):d}_exit{int(mx*100):d}"
        results.append(r)

    # R39-44: Convex power + increment sweeps
    for i,(cp,fi,mf) in enumerate([(2.0,0.15,0.125),(6.0,0.15,0.125),(8.0,0.15,0.125),(4.0,0.10,0.125),(4.0,0.20,0.125),(4.0,0.15,0.20)]):
        r=compute(report,rf,0.0,1.0,1.125,fi,cp,mf,0.0,0.0,COST)
        r["label"]=f"R{39+i}_pow{int(cp)}_fi{int(fi*100)}_mf{int(mf*1000)}"
        results.append(r)

    # R45-48: Expansion max + defense with momentum hysteresis
    for i,(em,db) in enumerate([(1.0,0.0),(1.25,0.0),(1.5,0.0),(1.125,0.0)]):
        r=compute(report,rf,db,1.0,em,0.15,4.0,0.125,0.0,0.0,COST)
        r["label"]=f"R{45+i}_exp{int(em*100)}_def{int(db*100)}"
        results.append(r)

    # R49-50: Combined extremes
    r49=compute(report,rf,0.0,1.0,1.5,0.15,6.0,0.125,0.0,0.0,COST)
    r49["label"]="R49_max_exp_pow6"
    r50=compute(report,rf,0.0,1.0,1.125,0.10,8.0,0.20,0.05,-0.02,COST)
    r50["label"]="R50_aggressive_combo"
    results.extend([r49,r50])

    results.sort(key=lambda r:r["calmar"],reverse=True)
    print(f"\nBYD R31-50 Results:")
    for r in results:
        print(f"  {r['label']:<35s} Calmar={r['calmar']:.4f} CAGR={r['cagr']:.4f} DD={r['max_drawdown']:.4f} Sharpe={r['sharpe']:.4f}")

    best=results[0]
    print(f"\nBEST: {best['label']} Calmar={best['calmar']:.4f} (vs R3: {bl['calmar']:.4f})")

    out=Path("artifacts/evidence/byd_rounds_31_50_v1/results.json"); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"r3_baseline":bl,"results":results,"best":best["label"]},indent=2,default=str))

if __name__=="__main__": main()
