import qlib
from qlib.data import D

qlib.init(provider_uri="data/watchlist")
# Correct way to get list of instruments
inst_list = D.instruments(market='all')
print(f"Total instruments: {len(inst_list)}")
print(f"First 5: {inst_list[:5]}")

fields = ["$open", "$high", "$low", "$close", "$volume", "$amount"]
if inst_list:
    sample = inst_list[:5]
    df = D.features(sample, fields, start_time="2026-01-20", end_time="2026-01-23")
    print(df.head(20))
    print("\nNull counts:")
    print(df.isnull().sum())
