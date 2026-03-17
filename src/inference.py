import os
import pickle
import subprocess
import sys
from pathlib import Path

import fire
import numpy as np
import pandas as pd
import yaml
from qlib.data import D
from qlib.data.dataset.handler import DataHandlerLP

from src.common.inference_features import (
    build_default_inference_features,
    resolve_inference_feature_list,
)
from src.common.guardrail_utils import apply_amount_fallback
from src.common.market import get_region_for_market
from src.guardrails.rules import apply_guardrails

def load_watchlist(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)

def load_name_map(config_path="configs/name_map.yaml"):
    if os.path.exists(config_path):
        with open(config_path, encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

from src.research.service import ResearchService
from src.common.paths import MODELS_DIR

def run_inference(market: str = "all", watchlist_config="configs/watchlist.yaml", data_dir="data/watchlist"):
    research = ResearchService(PROJECT_ROOT)
    
    if market == "all":
        print("=== Running Inference for ALL Markets ===")
        for m in ["cn", "us"]:
            cmd = [sys.executable, "-m", "src.inference", "--market", m]
            subprocess.run(cmd, check=True)
        return

    watchlist = load_watchlist(watchlist_config)
    name_map = load_name_map()
    
    # Define model paths
    model_paths = {
        'cn': MODELS_DIR / 'cn_model.pkl',
        'us': MODELS_DIR / 'us_model.pkl',
        'hk': MODELS_DIR / 'cn_model.pkl'
    }

    if market not in model_paths:
        print(f"Error: Unknown market {market}")
        return
    
    tickers = watchlist.get(market, [])
    if not tickers:
        print(f"No tickers for market {market}")
        return

    from src.common.qlib_utils import ensure_qlib_init
    region = get_region_for_market(market)
    ensure_qlib_init(provider_uri=data_dir, region=region)

    try:
        profile_path = Path("configs") / f"strategy_profile_{market}.json"
        if not profile_path.exists():
            profile_path = Path("configs") / "strategy_profile.json"

        results = research.run_inference(market, model_paths[market], tickers, profile_path=profile_path)
        final_df = results["results"]
        latest_date = results["date"]

        # Consolidate Report (keeping report generation logic here for now or moving to reporting service)
        if not final_df.empty:
            final_df = final_df.sort_values("score", ascending=False)
            if isinstance(final_df.index, pd.MultiIndex):
                final_df = final_df.reset_index()
            
            final_df['name'] = final_df['instrument'].apply(lambda x: name_map.get(str(x), name_map.get(str(x).upper(), str(x))))

            print("\n=== Inference Results ===")
            print(final_df[['name', 'score', 'passed', 'market']].head(20))
            
            # Save Report
            report_dir = Path("reports")
            report_dir.mkdir(exist_ok=True)
            report_path = report_dir / "watchlist_report.md"
            
            with open(report_path, "w", encoding='utf-8') as f:
                f.write("# Watchlist Inference Report\n")
                f.write(f"**Date:** {latest_date.date()}\n\n")
                
                f.write("## Top Picks (Passed Guardrails)\n")
                picks = final_df[final_df['passed'] == True].head(10)
                if picks.empty:
                    f.write("No candidates passed guardrails.\n")
                else:
                    f.write("| Instrument | Name | Market | Score | Close Price |\n")
                    f.write("|------------|------|--------|-------|-------------|\n")
                    for _, row in picks.iterrows():
                        f.write(f"| {row['instrument']} | {row['name']} | {row['market'].upper()} | {row['score']:.4f} | {row['close']:.2f} |\n")
                    
                f.write("\n\n## Full List\n")
                f.write("| Instrument | Name | Market | Score | Passed | Reason | Close Price |\n")
                f.write("|------------|------|--------|-------|--------|--------|-------------|\n")
                for _, row in final_df.iterrows():
                    reason = "OK"
                    if not row['passed']:
                        details = row['guardrail_result']['details']
                        reasons = [v['reason'] for v in details.values() if not v['passed']]
                        reason = "; ".join(reasons) if reasons else "Unknown"
                    f.write(f"| {row['instrument']} | {row['name']} | {row['market'].upper()} | {row['score']:.4f} | {row['passed']} | {reason} | {row['close']:.2f} |\n")
                
            print(f"Report saved to {report_path}")
        else:
            print("No results generated.")

    except Exception as e:
        print(f"  [!] Inference failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fire.Fire(run_inference)
