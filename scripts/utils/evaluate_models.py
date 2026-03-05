import pickle

import pandas as pd
import qlib
from qlib.data import D
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP


def evaluate(market, model_path):
    print(f"\nEvaluating {market.upper()} Model: {model_path}")
    
    # 1. Init Qlib
    try:
        qlib.init(provider_uri="data/watchlist", region="us") # Use US region for neutral calendar
    except:
        pass
        
    # 2. Load Model
    with open(model_path, "rb") as f:
        model = pickle.load(f)
        
    # 3. Load Test Data
    # Must match the config used during training
    if market == 'cn':
        instruments = 'cn'
        benchmark = '000300'
    else:
        instruments = 'us'
        benchmark = 'SPY'
        
    handler_kwargs = {
        "start_time": "2025-01-05",
        "end_time": "2025-12-30",
        "instruments": instruments,
        # Re-use the minimalist fields config
        "data_loader": {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": [
                        ["$close/$open-1", "$high/$close-1", "$low/$close-1"], 
                        ["ret", "high_ret", "low_ret"]
                    ],
                    "label": [
                        ["Ref($close, -2) / Ref($close, -1) - 1"], 
                        ["label"]
                    ]
                }
            }
        }
    }
    
    # Manually create handler
    print("Loading Test Data...")
    handler = DataHandlerLP(**handler_kwargs)
    
    # Fetch data (dataframe)
    # DataHandlerLP usually prepares everything in .init
    # We can access ._data
    
    # Prepare dataset object for model.predict
    # We need to wrap it in a DatasetH-like structure or just pass the handler?
    # LGBModel.predict expects a Dataset object.
    
    dataset = DatasetH(handler=handler, segments={"test": ("2025-01-01", "2026-01-01")})
    
    # 4. Predict
    print("Predicting...")
    pred = model.predict(dataset)
    if isinstance(pred, pd.Series):
        pred = pred.to_frame("score")
        
    # 5. Get Labels (Actual Returns)
    # The label index matches the prediction index
    label = handler.fetch(col_set="label", data_key="label")
    
    # Align
    combined = pd.concat([pred, label], axis=1).dropna()
    combined.columns = ["score", "label"]
    
    # 6. Calc Metrics
    # IC
    ic = combined.groupby("datetime").apply(lambda df: df["score"].corr(df["label"], method="pearson"))
    mean_ic = ic.mean()
    ic_ir = mean_ic / ic.std() if ic.std() != 0 else 0
    
    print(f"IC: {mean_ic:.4f}")
    print(f"ICIR: {ic_ir:.4f}")
    
    # Simple Strategy: Top 10 Equal Weight
    def strategy_return(df):
        top_k = df.nlargest(10, "score")
        return top_k["label"].mean()
        
    daily_ret = combined.groupby("datetime").apply(strategy_return)
    
    # Benchmark Return
    # We need to load benchmark simple returns
    bench_df = D.features([benchmark], ["$close/Ref($close,1)-1"], start_time="2025-01-01", end_time="2026-01-01")
    bench_ret = bench_df.groupby("datetime").mean() # Should be 1 ticker
    
    # Merge
    perf = pd.concat([daily_ret, bench_ret], axis=1).dropna()
    perf.columns = ["strategy", "benchmark"]
    perf["excess"] = perf["strategy"] - perf["benchmark"]
    
    ann_excess = perf["excess"].mean() * 252
    win_rate = (perf["excess"] > 0).mean()
    
    print(f"Annualized Excess Return: {ann_excess:.2%}")
    print(f"Daily Win Rate: {win_rate:.2%}")
    
    return mean_ic, ann_excess

if __name__ == "__main__":
    evaluate('us', 'models/us_model_20260128_010128.pkl')
    evaluate('cn', 'models/cn_model_20260128_010200.pkl')
