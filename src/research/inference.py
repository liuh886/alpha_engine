import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from qlib.data import D
from qlib.data.dataset.handler import DataHandlerLP
from qlib.data.dataset import DatasetH
from src.common.inference_features import build_default_inference_features, resolve_inference_feature_list
from src.common.guardrail_utils import apply_amount_fallback
from src.guardrails.rules import apply_guardrails

def perform_inference(
    market: str,
    model_path: Path,
    tickers: list[str],
    latest_date: pd.Timestamp,
    profile_path: Path = None
) -> pd.DataFrame:
    """
    Perform model inference for a specific market and set of tickers.
    """
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found at {model_path}")
        
    with open(model_path, "rb") as f:
        model = pickle.load(f)
        
    # Prepare date range for enough history for indicators
    start_date = latest_date - pd.Timedelta(days=400)
    
    # Load features
    features = build_default_inference_features(market)
    if profile_path and profile_path.exists():
        try:
            import json
            with open(profile_path, encoding="utf-8") as f:
                prof = json.load(f)
                features = resolve_inference_feature_list(prof, market_name=market, default_features=features)
        except Exception:
            pass

    data_loader_config = {
        "feature": features,
        "label": ["Ref($close, -1) / $close - 1"] # Dummy label
    }
    
    handler_kwargs = {
        "start_time": start_date, 
        "end_time": latest_date,
        "instruments": tickers,
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
    ds_inference = DatasetH(handler=dh, segments={"test": (latest_date, latest_date)})
    
    # Predict
    pred_score = model.predict(ds_inference, segment="test")
    
    # Align and format results
    df_test = dh.fetch(col_set="feature", start_time=latest_date, end_time=latest_date)
    if isinstance(pred_score, pd.Series):
        pred_df = pred_score.to_frame(name="score")
    elif isinstance(pred_score, np.ndarray):
        if len(pred_score) == len(df_test):
            pred_df = pd.DataFrame(pred_score, index=df_test.index, columns=["score"])
        else:
            min_len = min(len(pred_score), len(df_test))
            pred_df = pd.DataFrame(pred_score[:min_len], index=df_test.index[:min_len], columns=["score"])
    else:
        pred_df = pd.DataFrame(pred_score, columns=["score"])
        if not pred_df.index.empty and len(pred_df) == len(df_test):
            pred_df.index = df_test.index
            
    return pred_df.dropna(subset=["score"])

def apply_inference_guardrails(
    pred_df: pd.DataFrame,
    tickers: list[str],
    inference_date: pd.Timestamp
) -> pd.DataFrame:
    """
    Apply guardrails to inference results.
    """
    fields = ["$close", "Mean($close, 20)", "Std($close/Ref($close,1)-1, 20)", "Std($close/Ref($close,1)-1, 252)", "$amount", "$volume"]
    names = ["close", "ma20", "vol20", "vol252", "amount", "volume"]
    
    feat = D.features(tickers, fields, start_time=inference_date, end_time=inference_date)
    if feat.empty:
        # Dummy fallback if needed, but usually we expect data to be there if inference passed
        feat = pd.DataFrame(index=pred_df.index, columns=names).fillna(0)
    else:
        feat.columns = names
        feat = apply_amount_fallback(feat)
        # Drop date from index if it's MultiIndex to align with pred_df if it was cross-sectioned
        if isinstance(feat.index, pd.MultiIndex):
            feat = feat.xs(inference_date, level='datetime')
    
    combined = pred_df.join(feat)
    combined['guardrail_result'] = combined.apply(lambda row: apply_guardrails(row), axis=1)
    combined['passed'] = combined['guardrail_result'].apply(lambda x: x['passed'])
    return combined
