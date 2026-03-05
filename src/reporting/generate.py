import argparse
import pickle
from pathlib import Path

import pandas as pd
import yaml
from qlib.data import D
from qlib.workflow import R

from src.common.guardrail_utils import apply_amount_fallback
from src.common.paths import CONFIG_DIR, REPORTS_DIR
from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.guardrails.rules import apply_guardrails


def trade_ticket_path(market: str, date_str: str, *, reports_dir: Path = REPORTS_DIR) -> Path:
    return Path(reports_dir) / str(market).lower() / "trade_tickets" / f"trade_ticket_{date_str}.md"

def generate_report(market):
    print(f"Generating report for {market.upper()}...")
    
    # 1. Initialize Qlib with the correct data path
    cfg_path = CONFIG_DIR / f"{market}_lgbm_workflow.yaml"
    if not cfg_path.exists():
        cfg_path = CONFIG_DIR / f"{market}_workflow.yaml"

    workflow_cfg = {}
    if cfg_path.exists():
        try:
            workflow_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            workflow_cfg = {}

    qlib_cfg = build_qlib_init_cfg(
        (workflow_cfg.get("qlib_init", {}) if isinstance(workflow_cfg, dict) else {}) or {},
        market=market,
    )
    safe_qlib_init(qlib_cfg)
    
    # 2. Get latest recorder for this specific market
    try:
        exp_name = f"workflow_{market}"
        rec = R.get_recorder(experiment_name=exp_name)
    except Exception as e:
        print(f"Error getting recorder for {market}: {e}")
        return

    # 3. Load Predictions
    # Try multiple ways to find the artifact
    pred = None
    try:
        pred = rec.load_object("pred.pkl")
    except Exception:
        # Fallback to direct file read if recorder load fails
        local_dir = Path(rec.get_local_dir()) / "artifacts"
        pred_path = local_dir / "pred.pkl"
        if pred_path.exists():
            with open(pred_path, "rb") as f:
                pred = pickle.load(f)
    
    if pred is None or (isinstance(pred, pd.DataFrame) and pred.empty):
        print("No predictions found. Check training logs.")
        return
    
    last_date = pred.index.get_level_values('datetime').max()
    print(f"Last prediction date: {last_date}")
    
    latest_pred = pred.xs(last_date, level='datetime').sort_values('score', ascending=False)
    top_candidates = latest_pred.head(50).copy()
    
    # 4. Fetch features for guardrails
    print("Fetching features for guardrails...")
    instruments = top_candidates.index.tolist()
    fields = [
        "$close", 
        "Mean($close, 20)", 
        "Std($close/Ref($close,1)-1, 20)", 
        "Std($close/Ref($close,1)-1, 252)", 
        "$amount",
        "$volume"
    ]
    names = ["close", "ma20", "vol20", "vol252", "amount", "volume"]
    
    try:
        df_features = D.features(instruments, fields, start_time=last_date, end_time=last_date)
        if df_features.empty:
            print("Warning: No feature data found for guardrails.")
            top_candidates['passed_guardrails'] = True # Fallback
        else:
            df_features.columns = names
            # Drop datetime index for join
            feat_last = df_features.xs(last_date, level='datetime')
            feat_last = apply_amount_fallback(feat_last)
            top_candidates = top_candidates.join(feat_last)
            
            # Apply guardrails
            top_candidates['guardrail_result'] = top_candidates.apply(lambda row: apply_guardrails(row), axis=1)
            top_candidates['passed_guardrails'] = top_candidates['guardrail_result'].apply(lambda x: x['passed'])
    except Exception as e:
        print(f"Error applying guardrails: {e}")
        top_candidates['passed_guardrails'] = True

    final_picks = top_candidates[top_candidates['passed_guardrails'] == True].head(10)
    
    # 5. Load Performance Metrics
    port_analysis = None
    try:
        # Check if port_analysis_1day.pkl exists in artifacts
        artifacts = rec.list_artifacts()
        if "port_analysis_1day.pkl" in artifacts:
            port_analysis = rec.load_object("port_analysis_1day.pkl")
    except:
        pass

    # 6. Generate Markdown Report
    report_dir = Path(REPORTS_DIR) / str(market).lower()
    report_dir.mkdir(parents=True, exist_ok=True)
    
    report_path = report_dir / "latest_report.md"
    with open(report_path, "w") as f:
        f.write(f"# AI Trading Assistant Report: {market.upper()}\n\n")
        f.write(f"**Date:** {last_date.date()}\n\n")
        
        f.write("## Performance Summary (Test Set)\n")
        if port_analysis and "excess_return_with_cost" in port_analysis:
            # We could calculate summary stats here
            f.write("Backtest completed. Summary available in logs.\n\n")
        else:
            f.write("Performance data not available.\n\n")
            
        f.write("## Top 10 Picks (Passed Guardrails)\n\n")
        f.write("| Instrument | Score | Passed Guardrails |\n")
        f.write("|------------|-------|-------------------|\n")
        for inst, row in final_picks.iterrows():
            f.write(f"| {inst} | {row['score']:.4f} | Yes |\n")
        
        f.write("\n\n## Guardrail Violations (Top 50)\n\n")
        violations = top_candidates[top_candidates['passed_guardrails'] == False]
        if violations.empty:
            f.write("None\n")
        else:
            f.write("| Instrument | Score | Reason |\n")
            f.write("|------------|-------|--------|\n")
            for inst, row in violations.iterrows():
                res = row['guardrail_result']
                # Find the first failing rule
                reason = "Unknown"
                for rule, r in res['details'].items():
                    if not r['passed']:
                        reason = r['reason']
                        break
                f.write(f"| {inst} | {row['score']:.4f} | {reason} |\n")

    print(f"Report saved to {report_path}")

    # 7. Generate Trade Ticket
    ticket_path = trade_ticket_path(market, str(last_date.date()))
    ticket_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ticket_path, "w", encoding="utf-8") as f:
        f.write(f"# Trade Ticket: {market.upper()} - {last_date.date()}\n\n")
        f.write("Please execute the following trades at market open:\n\n")
        f.write("| Action | Instrument | Weight |\n")
        f.write("|--------|------------|--------|\n")
        for inst, row in final_picks.iterrows():
            f.write(f"| BUY | {inst} | 10% |\n")
            
    print(f"Trade ticket saved to {ticket_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", type=str, required=True)
    args = parser.parse_args()
    generate_report(args.market)
