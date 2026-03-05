import os
import pickle
import subprocess
import sys
from pathlib import Path

import fire
import numpy as np
import pandas as pd
import qlib
import yaml
from qlib.data import D
from qlib.data.dataset.handler import DataHandlerLP

from src.common.guardrail_utils import apply_amount_fallback
from src.common.market import get_region_for_market
from src.guardrails.rules import apply_guardrails

# Feature definitions matching the workflows
CN_FEATURES = [
    "$close/Ref($close, 1)-1",
    "$close/Ref($close, 5)-1",
    "$close/Ref($close, 10)-1",
    "$close/Ref($close, 20)-1",
    "$close/Mean($close, 5)-1",
    "$close/Mean($close, 20)-1",
    "$close/Mean($close, 60)-1",
    "Std($close, 20)/Mean($close, 20)",
    "($high-$low)/$close",
    "$volume/Mean($volume, 5)",
    "$volume/Mean($volume, 20)",
    "$mkt_cn_ma20_dev",
    "$mkt_cn_ma60_dev"
]

US_FEATURES = [
    "$close/Ref($close, 1)-1",
    "$close/Ref($close, 5)-1",
    "$close/Ref($close, 10)-1",
    "$close/Ref($close, 20)-1",
    "$close/Mean($close, 5)-1",
    "$close/Mean($close, 20)-1",
    "$close/Mean($close, 60)-1",
    "Std($close, 20)/Mean($close, 20)",
    "($high-$low)/$close",
    "$volume/Mean($volume, 5)",
    "$volume/Mean($volume, 20)",
    "$mkt_us_ma20_dev",
    "$mkt_us_ma60_dev"
]

def load_watchlist(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)

def load_name_map(config_path="configs/name_map.yaml"):
    if os.path.exists(config_path):
        with open(config_path, encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def _ensure_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _build_alpha158_plus_extra_features(extra_features):
    from qlib.contrib.data.loader import Alpha158DL

    alpha_features = Alpha158DL.get_feature_config(
        {
            "kbar": {},
            "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
            "rolling": {},
        }
    )[0]
    return list(alpha_features) + _ensure_list(extra_features)


def resolve_inference_feature_list(profile: dict, market_name: str, default_features: list[str]) -> list[str]:
    """Resolve inference features from either compiled workflow config or raw strategy profile schema."""
    if not isinstance(profile, dict):
        return list(default_features)

    compiled_feats = (
        (profile.get("task", {}) or {})
        .get("dataset", {})
        .get("kwargs", {})
        .get("handler", {})
        .get("kwargs", {})
        .get("data_loader", {})
        .get("kwargs", {})
        .get("config", {})
        .get("feature")
    )
    if compiled_feats and isinstance(compiled_feats, list):
        return list(compiled_feats)

    model = profile.get("model", {}) if isinstance(profile.get("model", {}), dict) else {}
    feature_pack = str(model.get("feature_pack") or "").lower()
    if feature_pack == "alpha158":
        return _build_alpha158_plus_extra_features(model.get("extra_features"))

    model_features = model.get("features")
    if model_features:
        return _ensure_list(model_features)

    return list(default_features)

def run_inference(market: str = "all", watchlist_config="configs/watchlist.yaml", data_dir="data/watchlist"):
    if market == "all":
        print("=== Running Inference for ALL Markets ===")
        for m in ["cn", "us"]:
            cmd = [sys.executable, "-m", "src.inference", "--market", m]
            subprocess.run(cmd, check=True)
        return

    watchlist = load_watchlist(watchlist_config)
    name_map = load_name_map()
    
    # Define markets mapping
    markets = {
        'cn': {'tickers': watchlist.get('cn', []), 'model_path': 'models/cn_model.pkl'},
        'us': {'tickers': watchlist.get('us', []), 'model_path': 'models/us_model.pkl'},
        'hk': {'tickers': watchlist.get('hk', []), 'model_path': 'models/cn_model.pkl'} # Use CN model for HK
    }

    # Only process requested market
    if market not in markets:
        print(f"Error: Unknown market {market}")
        return
    
    market_info = {market: markets[market]}
    
    # Read all available instruments directly from file to avoid API issues
    instruments_path = Path(data_dir) / "instruments" / "all.txt"
    all_instruments = []
    if instruments_path.exists():
        with open(instruments_path) as f:
            for line in f:
                parts = line.strip().split("\t")
                if parts:
                    all_instruments.append(parts[0])
    else:
        print(f"Warning: Instruments file not found at {instruments_path}")
    
    print(f"Loaded {len(all_instruments)} instruments from Qlib data.")
    
    results = []
    
    for market_name, info in market_info.items():
        tickers = info['tickers']
        if not tickers:
            continue
            
        print(f"\nProcessing {market_name.upper()} market ({len(tickers)} tickers)...")

        # Initialize Qlib per market to align calendars
        region = get_region_for_market(market_name)
        try:
            qlib.init(provider_uri=data_dir, region=region)
        except Exception:
            pass
        
        model_path = info['model_path']
        if not os.path.exists(model_path):
            print(f"  [!] Model not found at {model_path}. Skipping.")
            continue
            
        print(f"  Loading model from {model_path}")
        with open(model_path, "rb") as f:
            model = pickle.load(f)
            
        # Filter tickers that exist in data
        target_instruments = []
        for t in tickers:
            # We need to match the symbol format in Qlib
            # Try variations
            t_str = str(t)
            candidates = [t_str, t_str.replace('.', '_'), t_str.upper(), t_str.upper().replace('.', '_')]
            
            # Special handling for HK/CN suffixes if needed
            if market_name == 'hk':
                 t_clean = t_str.upper().replace('.HK', '').replace('.hk', '')
                 if len(t_clean) == 5 and t_clean.startswith('0'):
                     t_clean = t_clean[1:]
                 candidates.append(f"{t_clean}_HK")
            
            found = False
            for cand in candidates:
                if cand in all_instruments:
                    target_instruments.append(cand)
                    found = True
                    break
            
            if not found:
                # Fuzzy match in all_instruments
                pass

        target_instruments = list(set(target_instruments))
        print(f"  Matched {len(target_instruments)} instruments in data.")
        
        if not target_instruments:
            continue

        # Prepare Dataset
        # Get recent global calendar to check for data availability
        recent_cal = D.calendar(start_time=pd.Timestamp.now() - pd.Timedelta(days=10))
        
        # Check data availability by fetching a simple field
        check_df = D.features(target_instruments, ["$close"], start_time=recent_cal[0], end_time=recent_cal[-1])
        
        if check_df.empty:
             print(f"  [!] No data found for {market_name} in recent days.")
             continue
             
        # Get the latest date available for these instruments
        latest_date = check_df.index.get_level_values("datetime").max()
        print(f"  Inference Date: {latest_date}")
        
        # Ensure we have enough history for indicators (e.g. 252 days vol)
        start_date = latest_date - pd.Timedelta(days=400)
        
        try:
            # Load features from strategy profile if available for consistency
            profile_path = Path("configs") / f"strategy_profile_{market_name}.json"
            if not profile_path.exists():
                profile_path = Path("configs") / "strategy_profile.json"
            
            features = CN_FEATURES if market_name in ['cn', 'hk'] else US_FEATURES
            if profile_path.exists():
                try:
                    import json
                    with open(profile_path, encoding="utf-8") as f:
                        prof = json.load(f)
                        features = resolve_inference_feature_list(prof, market_name=market_name, default_features=features)
                        print(f"  Loaded {len(features)} features from {profile_path}")
                except Exception:
                    pass

            data_loader_config = {
                "feature": features,
                "label": ["Ref($close, -1) / $close - 1"] # Dummy label
            }
            
            handler_kwargs = {
                "start_time": start_date, 
                "end_time": latest_date,
                "instruments": target_instruments,
                "data_loader": {
                    "class": "QlibDataLoader",
                    "kwargs": {"config": data_loader_config}
                },
                "infer_processors": [
                    {'class': 'CSZScoreNorm', 'kwargs': {'fields_group': 'feature'}},
                    {'class': 'Fillna', 'kwargs': {'fields_group': 'feature'}}
                ],
                "learn_processors": [{'class': 'DropnaLabel'}]
            }
            
            dh = DataHandlerLP(**handler_kwargs)
            
            # Wrap in DatasetH for prediction
            from qlib.data.dataset import DatasetH
            ds_inference = DatasetH(handler=dh, segments={"test": (latest_date, latest_date)})
            
            # Predict
            # Model usually returns a Series or DataFrame
            pred_score = model.predict(ds_inference, segment="test")
            
            # Fetch index from handler for alignment
            df_test = dh.fetch(col_set="feature", start_time=latest_date, end_time=latest_date)
            
            # Convert to DataFrame with robust index alignment
            if isinstance(pred_score, pd.Series):
                pred_df = pred_score.to_frame(name="score")
            elif isinstance(pred_score, np.ndarray):
                # Ensure we don't crash if lengths differ
                if len(pred_score) == len(df_test):
                    pred_df = pd.DataFrame(pred_score, index=df_test.index, columns=["score"])
                else:
                    print(f"  [!] Prediction length mismatch: pred={len(pred_score)}, data={len(df_test)}")
                    # Fallback: use whatever labels we have or skip
                    min_len = min(len(pred_score), len(df_test))
                    pred_df = pd.DataFrame(pred_score[:min_len], index=df_test.index[:min_len], columns=["score"])
            else:
                pred_df = pd.DataFrame(pred_score, columns=["score"])
                if pred_df.index.empty or len(pred_df) != len(df_test):
                     print(f"  [!] Unexpected prediction format or length mismatch.")
                     # Try to align if it has instrument in index
                     if 'instrument' in df_test.index.names:
                         pred_df.index = df_test.index[:len(pred_df)]
                
            # Filter out any NaN scores
            pred_df = pred_df.dropna(subset=["score"])
            
            if pred_df.empty:
                print(f"  [!] All predictions for {market_name} were NaN or empty.")
                continue
                
            # Add Guardrails check
            print("  Checking guardrails...")
            fields = ["$close", "Mean($close, 20)", "Std($close/Ref($close,1)-1, 20)", "Std($close/Ref($close,1)-1, 252)", "$amount", "$volume"]
            names = ["close", "ma20", "vol20", "vol252", "amount", "volume"]
            
            feat = D.features(target_instruments, fields, start_time=latest_date, end_time=latest_date)
            if feat.empty:
                 print("  [!] Failed to fetch guardrail features.")
                 # Add dummy
                 feat = pd.DataFrame(index=pred_df.index, columns=names)
                 feat[:] = 0
            else:
                feat.columns = names
                feat = apply_amount_fallback(feat)
                feat = feat.xs(latest_date, level='datetime')
            
            combined = pred_df.join(feat)
            
            # Apply guardrails
            combined['guardrail_result'] = combined.apply(lambda row: apply_guardrails(row), axis=1)
            combined['passed'] = combined['guardrail_result'].apply(lambda x: x['passed'])
            combined['market'] = market_name
            
            results.append(combined)
            
        except Exception as e:
            print(f"  [!] Inference failed: {e}")
            import traceback
            traceback.print_exc()

    # Consolidate Report
    if results:
        final_df = pd.concat(results)
        final_df = final_df.sort_values("score", ascending=False)
        
        # Add Names
        # Reset index to make instrument accessible, but keep original index for reference if needed
        # The index is likely MultiIndex (datetime, instrument) or just instrument if we xs'd earlier
        # Based on logic above: pred_df index is likely MultiIndex from qlib
        
        # If index is MultiIndex, reset it
        if isinstance(final_df.index, pd.MultiIndex):
             final_df = final_df.reset_index()
        
        # Map names
        final_df['name'] = final_df['instrument'].apply(lambda x: name_map.get(str(x), name_map.get(str(x).upper(), str(x))))

        print("\n=== Inference Results ===")
        print(final_df[['name', 'score', 'passed', 'market']].head(20))
        
        # Save Report
        report_dir = Path("reports")
        report_dir.mkdir(exist_ok=True)
        report_path = report_dir / "watchlist_report.md"
        
        with open(report_path, "w", encoding='utf-8') as f:
            f.write("# Watchlist Inference Report\n")
            f.write(f"**Date:** {pd.Timestamp.now().date()}\n\n")
            
            f.write("## Top Picks (Passed Guardrails)\n")
            picks = final_df[final_df['passed'] == True].head(10)
            if picks.empty:
                f.write("No candidates passed guardrails.\n")
            else:
                # Format table
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
                    # Extract the first failure reason
                    details = row['guardrail_result']['details']
                    reasons = [v['reason'] for v in details.values() if not v['passed']]
                    reason = "; ".join(reasons) if reasons else "Unknown"
                f.write(f"| {row['instrument']} | {row['name']} | {row['market'].upper()} | {row['score']:.4f} | {row['passed']} | {reason} | {row['close']:.2f} |\n")
            
        print(f"Report saved to {report_path}")
    else:
        print("No results generated.")

if __name__ == "__main__":
    fire.Fire(run_inference)
