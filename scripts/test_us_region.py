import qlib
from qlib.data import D

qlib.init(provider_uri='data/watchlist', region='us')
df = D.features(['600519'], ['$close'], start_time='2025-01-01')
print(df.head())
