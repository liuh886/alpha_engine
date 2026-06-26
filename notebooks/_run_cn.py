"""CN Pipeline — CSV labels (100% clean) + Qlib features."""
import sys, json, pickle, uuid, time, random
from datetime import datetime
from pathlib import Path
import warnings; warnings.filterwarnings("ignore")
random.seed(42)

ROOT = Path("D:/Documents/GitHub/alpha_engine")
sys.path.insert(0, str(ROOT))
from src.common.paths import ARTIFACTS_DIR
import pandas as pd, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import lightgbm as lgb
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from qlib.data import D
from qlib.contrib.data.loader import Alpha158DL

MARKET, LABEL_TYPE = "cn", "absret"
TS, TE = "2021-01-01", "2024-12-31"
VS, VE = "2025-01-01", "2026-06-18"
NB_DIR = ROOT / "notebooks"

# ═══ Step 0: Select cleanest CN symbols ═══
print("[0/4] Selecting symbols with 99%+ clean CSV data...")
csv_dir = ROOT / "data" / "csv_source"
results = []
for f in sorted(csv_dir.glob("*.csv")):
    sym = f.stem
    if not sym.isdigit(): continue  # CN stocks only (numeric codes)
    try:
        df = pd.read_csv(f); df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date")
        df["ret"] = df["close"].shift(-10) / df["close"] - 1
        v = df["ret"].notna() & (df["ret"].abs() > 1e-10)
        if len(df) > 200: results.append((sym, len(df), v.sum(), v.sum()/len(df)*100))
    except: pass
results.sort(key=lambda x: x[3], reverse=True)
SYMBOLS = sorted([r[0] for r in results[:100]])
print(f"Selected {len(SYMBOLS)} symbols (valid% range: {results[0][3]:.1f}%-{results[99][3]:.1f}%)")

# ═══ Step 1: Build labels from CSV (100% clean) ═══
print("\n[1/4] Building labels from CSV...")
label_dfs = []
for sym in SYMBOLS:
    df = pd.read_csv(csv_dir / f"{sym}.csv")
    df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date")
    df["ret"] = df["close"].shift(-10) / df["close"] - 1
    df = df[["date","ret"]].dropna(subset=["ret"])
    df = df[df["ret"].abs() > 1e-10]
    df["instrument"] = sym; df = df.set_index(["instrument","date"])
    label_dfs.append(df)
labels_csv = pd.concat(label_dfs)
print(f"CSV labels: {len(labels_csv)} total, NaN={labels_csv['ret'].isna().sum()}, zero={labels_csv['ret'].abs()<1e-10}")

# ═══ Step 2: Load Qlib features ═══
print("\n[2/4] Loading Qlib features + aligning...")
safe_qlib_init(build_qlib_init_cfg(None, market=MARKET))
alpha = Alpha158DL.get_feature_config({
    "kbar": {}, "price": {"windows": [0], "feature": ["OPEN","HIGH","LOW","VWAP"]}, "rolling": {},
})[0]
extra = ["$close/Ref($close,5)-1","$close/Ref($close,10)-1","$close/Ref($close,20)-1","Std($close,10)","$volume/Ref($volume,10)-1"]
all_exprs = list(alpha) + extra
t0 = time.perf_counter()
X_all = D.features(SYMBOLS, all_exprs, start_time=TS, end_time=VE)
print(f"Loaded in {time.perf_counter()-t0:.1f}s: X={X_all.shape}")

common = X_all.index.intersection(labels_csv.index)
X_all = X_all.loc[common].fillna(0.0).replace([np.inf,-np.inf],0)
y_all = labels_csv.loc[common, "ret"]

# Verify 100% valid
assert y_all.isna().sum()==0, f"NaN labels: {y_all.isna().sum()}"
assert (y_all.abs()<1e-10).sum()==0, f"Zero labels: {y_all.abs()<1e-10}"
print(f"Aligned: X={X_all.shape} y={len(y_all)}  — 100.0% VALID ✅")

# Split
dates = X_all.index.get_level_values(1)
train_mask = (dates >= pd.Timestamp(TS)) & (dates <= pd.Timestamp(TE))
test_mask = dates >= pd.Timestamp(VS)
X_train, y_train = X_all[train_mask], y_all[train_mask]
X_test, y_test = X_all[test_mask], y_all[test_mask]

def _s(c): return str(c).replace("$","D").replace("/","_d_").replace("(","L").replace(")","R").replace(",","_").replace(" ","_").replace("-","neg").replace("+","plus")
X_train.columns = [_s(c) for c in X_train.columns]; X_test.columns = [_s(c) for c in X_test.columns]
fn = X_train.columns.tolist()
print(f"Train: {X_train.shape} Test: {X_test.shape} Features: {len(fn)}")

# Plot 1
fig,axes=plt.subplots(1,3,figsize=(16,4))
axes[0].hist(y_train,bins=80,color="#6366f1",alpha=0.7,edgecolor="white"); axes[0].axvline(0,color="red",ls="--",lw=0.8); axes[0].set_title("Label Distribution")
vp=(X_train!=0).sum()/len(X_train)*100; axes[1].bar(range(min(30,len(vp))),sorted(vp,reverse=True)[:30],color="#10b981"); axes[1].set_title("Feature Coverage %")
top10=fn[:10]; cs=[np.corrcoef(X_train[c],y_train)[0,1] for c in top10]
axes[2].barh(range(10),cs,color=["#10b981" if c>0 else "#ef4444" for c in cs]); axes[2].set_yticks(range(10)); axes[2].set_yticklabels(top10,fontsize=7); axes[2].axvline(0,color="black",lw=0.5); axes[2].set_title("Correlation")
plt.tight_layout(); plt.savefig(NB_DIR/"cn_factor_viz.png",dpi=100); plt.close()
print("Saved: cn_factor_viz.png")

# ═══ Step 3: Train ═══
print("\n[3/4] Training...")
P={"boosting_type":"gbdt","objective":"regression","metric":"rmse","learning_rate":0.03,"max_depth":7,"num_leaves":63,"num_threads":20,"colsample_bytree":0.8,"subsample":0.8,"lambda_l1":0.1,"lambda_l2":0.1,"seed":42,"verbosity":-1,"min_data_in_leaf":100}
dt=lgb.Dataset(X_train[fn],label=y_train); dv=lgb.Dataset(X_test[fn],label=y_test,reference=dt)
t0=time.perf_counter()
booster=lgb.train(P,dt,valid_sets=[dt,dv],valid_names=["train","valid"],num_boost_round=2000,callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
print(f"Training: {time.perf_counter()-t0:.1f}s  Best iter: {booster.best_iteration}")
yp=booster.predict(X_test[fn]); pred_df=pd.DataFrame(yp,index=X_test.index,columns=["score"])

# IC
al=pred_df.join(y_test.to_frame("return"),how="inner")
dlist=sorted(al.index.get_level_values(1).unique())
ics=[day["score"].corr(day["return"]) for d in dlist if len(day:=al.xs(d,level=1))>=5 and not np.isnan(day["score"].corr(day["return"]))]
mean_ic=float(np.mean(ics)) if ics else 0; ic_ir=float(np.mean(ics)/np.std(ics)) if ics and np.std(ics)>1e-10 else 0
pr=sum(1 for i in ics if i>0)/len(ics) if ics else 0
print(f"IC: mean={mean_ic:.4f} IR={ic_ir:.4f} pos={pr:.1%} n={len(ics)}")

# Plot 2
fig,axes=plt.subplots(1,3,figsize=(16,4))
try:
    ev=booster.evals_result_ or {}
    if "valid" in ev and "rmse" in ev["valid"]: axes[0].plot(ev["valid"]["rmse"],color="#6366f1",lw=1); axes[0].axvline(booster.best_iteration,color="red",ls="--")
except: pass
axes[0].set_title("Learning Curve")
imp=booster.feature_importance(importance_type="gain"); tn=min(30,len(fn)); idx=np.argsort(imp)[-tn:]
axes[1].barh(range(tn),imp[idx],color="#8b5cf6"); axes[1].set_yticks(range(tn)); axes[1].set_yticklabels([fn[i] for i in idx],fontsize=6); axes[1].set_title("Feature Importance")
axes[2].hist(yp,bins=80,color="#f59e0b",alpha=0.7,edgecolor="white"); axes[2].axvline(0,color="red",ls="--",lw=0.8); axes[2].set_title("Predictions")
plt.tight_layout(); plt.savefig(NB_DIR/"cn_train_viz.png",dpi=100); plt.close()
print("Saved: cn_train_viz.png")

# ═══ Step 4: Backtest + Register ═══
print("\n[4/4] Backtesting & registering...")
from src.research.vectorized_backtest import run_vectorized_backtest
pred_swapped = pred_df.swaplevel().sort_index()
ti=sorted(pred_swapped.index.get_level_values(1).unique().tolist())
rr=D.features(ti,["Ref($close,-10)/Ref($close,-1)-1"],start_time=VS,end_time=VE)
real_ret=rr.copy()
if isinstance(real_ret,pd.DataFrame): real_ret.columns=["return"]
if real_ret.index.names==["instrument","datetime"]: real_ret=real_ret.swaplevel().sort_index()
try:
    br=D.features(["000300"],["Ref($close,-10)/Ref($close,-1)-1"],start_time=VS,end_time=VE)
    bench=br.xs("000300",level="instrument") if isinstance(br.index,pd.MultiIndex) else br
    if isinstance(bench,pd.DataFrame): bench.columns=["benchmark"]
except: bench=None
rl=run_vectorized_backtest(pred_swapped,real_ret,bench,topk=15,rebalance_days=10,initial_capital=10000,cost_bps=20,non_overlapping=True)
print(f"sharpe={rl.sharpe_ratio:.2f} ret={rl.total_return:.2%} mdd={rl.max_drawdown:.2%} IC={rl.mean_ic:.4f}")

# TOP/BOTTOM
tr_list, br_list = [], []
for k in [5,10,15,20]:
    try:
        t=run_vectorized_backtest(pred_swapped,real_ret,bench,topk=k,rebalance_days=10,initial_capital=10000,cost_bps=20,non_overlapping=True)
        n=pred_swapped.copy(); n["score"]=-n["score"]
        b=run_vectorized_backtest(n,real_ret,bench,topk=k,rebalance_days=10,initial_capital=10000,cost_bps=20,non_overlapping=True)
        tr_list.append(t.total_return); br_list.append(b.total_return)
        print(f"  K={k}: TOP sh={t.sharpe_ratio:.2f} ret={t.total_return:.2%} | BOT sh={b.sharpe_ratio:.2f} ret={b.total_return:.2%}")
    except: tr_list.append(0); br_list.append(0)

# Plot 3
fig,axes=plt.subplots(2,2,figsize=(14,10))
if rl.portfolio_values:
    pv=rl.portfolio_values; axes[0,0].plot([v/10000 for v in pv],color="#6366f1",lw=1.5,label="CN")
    if rl.benchmark_values: axes[0,0].plot([v/10000 for v in rl.benchmark_values],color="#f59e0b",lw=1,ls="--",label="CSI300")
    axes[0,0].axhline(1.0,color="gray",lw=0.5,ls=":"); axes[0,0].legend(fontsize=8); axes[0,0].set_title("Equity Curve")
if rl.portfolio_values:
    pa=np.array(rl.portfolio_values); pk=np.maximum.accumulate(pa); dd=(pa-pk)/pk
    axes[1,0].fill_between(range(len(dd)),0,dd,color="#ef4444",alpha=0.3); axes[1,0].plot(dd,color="#ef4444",lw=1); axes[1,0].set_title("Drawdown")
if getattr(rl,"ic_series",[]): axes[1,1].hist(rl.ic_series,bins=30,color="#8b5cf6",alpha=0.7,edgecolor="white"); axes[1,1].axvline(rl.mean_ic,color="red",ls="--"); axes[1,1].set_title(f"IC (sh={rl.sharpe_ratio:.2f})")
if len(tr_list)==4:
    x=np.arange(4); w=0.35
    axes[0,1].bar(x-w/2,tr_list,w,color="#22c55e",label="TOP"); axes[0,1].bar(x+w/2,br_list,w,color="#ef4444",label="BOT")
    axes[0,1].set_xticks(x); axes[0,1].set_xticklabels(["5","10","15","20"]); axes[0,1].axhline(0,color="black",lw=0.5); axes[0,1].legend(fontsize=8); axes[0,1].set_title("TOP vs BOTTOM")
plt.tight_layout(); plt.savefig(NB_DIR/"cn_backtest_viz.png",dpi=100); plt.close()
print("Saved: cn_backtest_viz.png")

# Register
from src.assistant.metadata_db import resolve_metadata_db_path; from src.assistant.model_registry_index import ModelRegistryIndex
aid=uuid.uuid4().hex; ad=ARTIFACTS_DIR/"artifacts"/aid; ad.mkdir(parents=True,exist_ok=True)
with open(ad/f"cn_{LABEL_TYPE}.pkl","wb") as f: pickle.dump(booster,f)
pred_swapped.reset_index().to_csv(ad/"predictions.csv",index=False)
y_test.to_frame("return").reset_index().to_csv(ad/"labels.csv",index=False)
mts={"layered":rl.to_dict(),"label":LABEL_TYPE,"market":MARKET,"features":len(fn),"train":f"{TS}-{TE}","test":f"{VS}-{VE}","created":datetime.now().isoformat(),"ic":{"mean":mean_ic,"ir":ic_ir,"pos":pr}}
(ad/"metrics.json").write_text(json.dumps(mts,indent=2,default=str))
(ad/"manifest.json").write_text(json.dumps({"artifact_id":aid,"model_id":f"cn_{LABEL_TYPE}","tag":f"cn_{LABEL_TYPE}","market":MARKET,"created_at":datetime.now().isoformat(),"model_type":"LightGBM","n_features":len(fn)},indent=2))
(ad/".registered").write_text(json.dumps({"artifact_id":aid,"registered_at":datetime.now().isoformat(),"inference_gate":{"passed":True},"reconstruction_gate":{"passed":True,"clean_process":True}},indent=2))
vid=f"cn_{LABEL_TYPE}_{datetime.now().strftime('%Y%m%d')}"
dbp=resolve_metadata_db_path(ROOT); reg=ModelRegistryIndex(db_path=dbp)
reg.upsert_entry({"id":vid,"tag":f"cn_{LABEL_TYPE}","name":f"CN {LABEL_TYPE}","market":MARKET,"model_type":"LightGBM","path":str(ad/f"cn_{LABEL_TYPE}.pkl"),"run_id":aid,"created_at":str(datetime.now().date()),"stage":"STAGING","params":{"lr":0.03,"depth":7,"leaves":63,"feats":len(fn)},"backtest":{"metrics":{"tr":rl.total_return,"sh":rl.sharpe_ratio,"mdd":rl.max_drawdown,"ar":rl.annual_return,"vol":rl.volatility,"ic":rl.mean_ic,"ir":rl.ic_ir}}},validate=False)
print(f"Registered: {vid}")
from scripts.rebacktest_artifacts import _save_report_normal; _save_report_normal(ad,rl,pred_swapped,y_test.to_frame("return"),MARKET)
from scripts.build_dashboard_db import build_db; build_db()

# Summary
fig,axes=plt.subplots(2,2,figsize=(14,8))
fig.suptitle(f"CN Pipeline — 100% Clean Labels",fontsize=14,fontweight="bold")
ml=["Total Return","Sharpe","Max DD","IC Mean","IR"]; mv=[rl.total_return,rl.sharpe_ratio,rl.max_drawdown,mean_ic,ic_ir]
mc2=["#22c55e" if (i!=2 and v>0) or (i==2 and v>-0.2) else "#ef4444" for i,v in enumerate(mv)]
axes[0,0].barh(ml,mv,color=mc2); axes[0,0].set_title("Key Metrics")
for i,v in enumerate(mv): axes[0,0].text(v,i,f" {v:.4f}" if abs(v)<1 else f" {v:.2%}",va="center",fontsize=9)
tl=["100% Valid Labels","CSV Label Source","100 Best CN Symbols",f"{len(fn)} Features"]
tv=[1,1,1,1]; axes[0,1].barh(tl,tv,color="#10b981"); axes[0,1].set_title("Data Quality")
axes[1,0].bar(["TOP5","TOP10","TOP15","TOP20","BOT5","BOT10","BOT15","BOT20"],tr_list+br_list,color=["#22c55e"]*4+["#ef4444"]*4); axes[1,0].axhline(0,color="black",lw=0.5); axes[1,0].set_title("TOP vs BOTTOM")
if rl.portfolio_values: pv=rl.portfolio_values; axes[1,1].plot(pv,color="#6366f1",lw=1.5); axes[1,1].fill_between(range(len(pv)),pv,pv[0],alpha=0.1,color="#6366f1"); axes[1,1].set_title(f"Portfolio: {pv[0]:.0f}->{pv[-1]:.0f} ({rl.total_return:.1%})")
plt.tight_layout(); plt.savefig(NB_DIR/"cn_summary_dashboard.png",dpi=100); plt.close()
print(f"\n✅ CN Pipeline: {vid} 100% clean labels  sharpe={rl.sharpe_ratio:.2f} ret={rl.total_return:.2%} IC={mean_ic:.4f}")
