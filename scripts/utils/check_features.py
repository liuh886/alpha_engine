import qlib
from qlib.data import D


def check_features(market='us'):
    qlib.init(provider_uri='data/watchlist')
    
    features = [
        "$close/Ref($close, 5)-1",
        "$close/Ref($close, 10)-1",
        "$close/Ref($close, 20)-1",
        "Std($close, 10)",
        "$volume/Ref($volume, 10)-1",
    ]
    
    # Get a few stocks
    instruments = D.list_instruments(D.instruments(market))
    target = list(instruments.keys())[:10]
    
    labels = ["Ref($close, -10) / Ref($close, -1) - 1"]
    
    print(f"Checking features and labels for {market} ({len(target)} instruments)...")
    
    df = D.features(target, features + labels, start_time='2024-01-01', end_time='2024-01-31')
    
    if df.empty:
        print("Dataframe is empty!")
        return
        
    print("\nFeature Statistics (Mean):")
    print(df.mean())
    
    print("\nNaN Count:")
    print(df.isna().sum())
    
    print("\nFirst 5 rows:")
    print(df.head())

if __name__ == "__main__":
    import sys
    market = sys.argv[1] if len(sys.argv) > 1 else 'us'
    check_features(market)
