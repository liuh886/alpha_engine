"""Zero-fit E6 comparisons from the sealed E5 score package, using one engine."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.e5_execution_review import latency_scores
from src.research.e5_score_reconstruction import sha, write_json
from src.research.e6_capacity import capacity_screen, source_pairs
from src.research.execution_selection import make_selection
from src.research.portfolio_ledger import replay_ledger, summarize_ledger

CONTRACT_SHA = "1a034d711b6b8e6fd4cb5bb8a0877e769c68d05e585450585984ccfefe964424"


def contract(path: Path) -> dict:
    if sha(path) != CONTRACT_SHA:
        raise ValueError("E6 contract differs from pre-result frozen bytes")
    return json.loads(path.read_bytes())


class E5Inputs:
    def __init__(self, archive: Path, cfg: dict):
        if sha(archive) != cfg["source_e5_archive_sha256"]:
            raise ValueError("E5 source package SHA mismatch")
        self.zip = zipfile.ZipFile(archive)
        manifest_raw = self.zip.read("manifest.json")
        if hashlib.sha256(manifest_raw).hexdigest() != cfg["source_e5_manifest_sha256"]:
            raise ValueError("E5 source manifest SHA mismatch")
        manifest = json.loads(manifest_raw)
        names = self.zip.namelist()
        if len(names) != len(set(names)) or set(names) != {"manifest.json"} | {f["path"] for f in manifest["files"]}:
            raise ValueError("E5 package member inventory mismatch")
        for f in manifest["files"]:
            raw = self.zip.read(f["path"])
            if len(raw) != f["size"] or hashlib.sha256(raw).hexdigest() != f["sha256"]:
                raise ValueError("E5 package member hash mismatch")
        self.close = self.frame("source_snapshot/close.parquet")
        self.volume = self.frame("source_snapshot/volume.parquet")
        self.qqq = self.frame("source_snapshot/qqq.parquet")["close"]
        self.plan = self.doc("source_snapshot/plan.json")

    def frame(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(io.BytesIO(self.zip.read(name)))

    def doc(self, name: str) -> dict:
        return json.loads(self.zip.read(name))

    def close_file(self) -> None:
        self.zip.close()


def evaluate_one(inputs: E5Inputs, cfg: dict, arm: dict, strategy: str, fold: str,
                 pairs: pd.DataFrame, output: Path) -> dict:
    old = inputs.doc(f"results/{strategy}/{fold}/result.json")
    dates = inputs.frame(f"results/{strategy}/{fold}/original-daily.parquet")["date"].tolist()
    calendar = list(inputs.close.index)
    sessions = [calendar[calendar.index(dates[0])-1], *dates]
    scores = inputs.frame(f"scores/{strategy}/{fold}/scores.parquet")
    shifted, mapping = latency_scores(scores,sessions,calendar)
    # Prove the legacy delayed control before any E6 policy comparison.
    control, control_assets = replay_ledger(scores=shifted,prices=inputs.close,qqq=inputs.qqq,
        sessions=sessions,signal_sessions=mapping,mode="delayed_close_1session")
    legacy = summarize_ledger(control,control_assets)
    for key in ("net_return","net_excess","max_drawdown","turnover"):
        if abs(legacy[key]-old["delayed"][key])>1e-12:
            raise ValueError(f"E5 delayed control parity failed: {strategy}/{fold}/{key}")
    selector = make_selection(arm,symbols=list(scores.columns),calendar=calendar,
                              salt=cfg["contract_id"],top_k=cfg["execution"]["top_k"])
    daily,assets = replay_ledger(scores=shifted,prices=inputs.close,qqq=inputs.qqq,sessions=sessions,
        signal_sessions=mapping,mode="delayed_close_1session",selection=selector,
        friction=cfg["execution"]["friction_per_turnover"])
    capacity,cap_summary = capacity_screen(daily,assets,pairs,inputs.close,
        window=cfg["capacity"]["lagged_adv_sessions"],
        participation=cfg["capacity"]["participation_cap_scenario"])
    output.mkdir(parents=True,exist_ok=False)
    daily.to_parquet(output/"daily.parquet",index=False)
    assets.to_parquet(output/"assets.parquet",index=False)
    capacity.to_parquet(output/"capacity-screen.parquet",index=False)
    summary = summarize_ledger(daily,assets)
    row = {"arm_id":arm["id"],"configuration_id":strategy,"fold_id":fold,
        "contract_sha256":CONTRACT_SHA,"e5_delayed_control_parity":"PASS",
        "summary":summary,"capacity":cap_summary,"model_fits":0,
        "evaluator_git_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parents[2],text=True).strip(),
        "code_sha256":{name:sha(Path(__file__).parent/name) for name in
            ("e6_execution.py","e6_capacity.py","execution_selection.py","portfolio_ledger.py","walkforward/pipeline.py")},
        "files":{name:sha(output/name) for name in ("daily.parquet","assets.parquet","capacity-screen.parquet")},
        "research_only":True,"trade_ready":False,"pit_certified":False}
    write_json(output/"result.json",row)
    return row


def compare(rows: list[dict], cfg: dict) -> dict:
    expected={(a["id"],c,f) for a in cfg["arms"] for c in cfg["strategies"] for f in cfg["folds"]}
    index={(r["arm_id"],r["configuration_id"],r["fold_id"]):r for r in rows}
    if len(index)!=len(rows) or set(index)!=expected:
        raise ValueError("E6 matrix is incomplete or duplicated")
    paired=[]
    import statistics
    for arm in cfg["arms"]:
        for model in ("xgb_p03","lgb_p05"):
            for baseline in cfg["historical_diagnostic_acceptance"]["baselines"]:
                a=[index[(arm["id"],model,f)]["summary"] for f in cfg["folds"]]
                b=[index[(arm["id"],baseline,f)]["summary"] for f in cfg["folds"]]
                if any(x["sessions"]!=y["sessions"] or abs(x["qqq_return"]-y["qqq_return"])>1e-12 for x,y in zip(a,b)):
                    raise ValueError("E6 paired evidence is not calendar aligned")
                deltas=[100*(x["net_return"]-y["net_return"]) for x,y in zip(a,b)]
                ratio=sum(x["turnover"] for x in a)/sum(x["turnover"] for x in b)
                limits=cfg["historical_diagnostic_acceptance"]
                passed=(statistics.median(deltas)>limits["paired_median_net_advantage_pp_min_exclusive"] and
                        sum(v>0 for v in deltas)>=limits["positive_folds_min"] and
                        ratio<=limits["turnover_ratio_vs_each_baseline_max"])
                paired.append({"arm_id":arm["id"],"model":model,"baseline":baseline,
                    "fold_deltas_pp":deltas,"median_delta_pp":statistics.median(deltas),
                    "positive_folds":sum(d>0 for d in deltas),"turnover_ratio":ratio,
                    "predeclared_historical_screen_pass":passed})
    primary=[p for p in paired if p["arm_id"]==cfg["primary_forward_policy"]]
    return {"schema_version":"e6_execution_comparison_v1","contract_sha256":CONTRACT_SHA,
        "completed_policy_config_folds":len(rows),"paired":paired,"rows":rows,
        "primary_policy":cfg["primary_forward_policy"],"primary_model_screens":{
            model:all(p["predeclared_historical_screen_pass"] for p in primary if p["model"]==model)
            for model in ("xgb_p03","lgb_p05")},
        "capacity_actual_gate":"BLOCKED_VOLUME_UNITS_AND_HISTORICAL_AVAILABILITY",
        "historical_evidence":"RETROSPECTIVE_ALREADY_CONSUMED_NOT_INDEPENDENT_OOS",
        "model_fits":0,"research_only":True,"trade_ready":False,"pit_certified":False}


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract",type=Path,required=True)
    p.add_argument("--e5-package",type=Path,required=True)
    p.add_argument("--raw-source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--arm")
    p.add_argument("--strategy")
    p.add_argument("--fold")
    args=p.parse_args(argv)
    cfg=contract(args.contract)
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("E6 private outputs must be outside checkout")
    inputs=E5Inputs(args.e5_package,cfg)
    try:
        pairs,receipt=source_pairs(args.raw_source,inputs.close,inputs.volume)
        args.output.mkdir(parents=True,exist_ok=False)
        pairs.to_parquet(args.output/"capacity-source-pairs.parquet",index=False)
        write_json(args.output/"capacity-source-receipt.json",receipt)
        rows=[]
        selected_arms=[a for a in cfg["arms"] if not args.arm or args.arm==a["id"]]
        selected_strategies=[s for s in cfg["strategies"] if not args.strategy or args.strategy==s]
        selected_folds=[f for f in cfg["folds"] if not args.fold or args.fold==f]
        if not selected_arms or not selected_strategies or not selected_folds:
            raise ValueError("selection outside the frozen E6 matrix")
        for arm in selected_arms:
            for strategy in selected_strategies:
                for fold in selected_folds:
                    row=evaluate_one(inputs,cfg,arm,strategy,fold,pairs,args.output/"results"/arm["id"]/strategy/fold)
                    rows.append(row)
                    print("E6_POSTFIT",len(rows),arm["id"],strategy,fold,flush=True)
        if len(rows)==224:
            write_json(args.output/"comparison.json",compare(rows,cfg))
        else:
            write_json(args.output/"slice.json",{"status":"PARTIAL_VERTICAL_SLICE","results":len(rows),"model_fits":0})
    finally:
        inputs.close_file()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
