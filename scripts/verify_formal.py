import json
import sys
sys.path.insert(0, '.')
import numpy as np
import pandas as pd

# Load formal V1.2 trace
with open('data/research/formal_model_runs/byd_allocation/byd_v1_2_convex_momentum_budget_v1/byd_v1_2_convex_momentum_budget_v1-through-2026_08_07/performance.json') as f:
    perf = json.load(f)

formal = pd.DataFrame(perf['report'])
formal['date'] = pd.to_datetime(formal['date'])
formal = formal.set_index('date')
print('Formal V1.2 daily trace:')
print(f'  Rows: {len(formal)}')
print(f'  Date range: {formal.index[0].date()} to {formal.index[-1].date()}')

# Returns
formal_ret = formal['gross_return'] - formal['transaction_cost'] - formal['financing_cost']
formal_wealth = (1 + formal_ret).cumprod()
formal_tr = float(formal_wealth.iloc[-1] - 1)
years = len(formal_ret) / 252.0
formal_cagr = float(formal_wealth.iloc[-1] ** (1 / years) - 1)
formal_vol = float(formal_ret.std() * np.sqrt(252))
formal_sharpe = float(formal_ret.mean() / formal_ret.std() * np.sqrt(252))
formal_dd = float((formal_wealth / formal_wealth.cummax() - 1).min())

print(f'  Total Return: {formal_tr:.4f} ({formal_tr*100:.1f}%)')
print(f'  CAGR: {formal_cagr:.4f} ({formal_cagr*100:.2f}%)')
print(f'  Vol: {formal_vol:.4f}')
print(f'  Sharpe: {formal_sharpe:.4f}')
print(f'  MaxDD: {formal_dd:.4f}')
print(f'  Sum costs: {formal["transaction_cost"].sum():.4f}')
print(f'  Sum financing: {formal["financing_cost"].sum():.6f}')
print(f'  Financed sessions: {(formal["trend_expansion_active"] > 0).sum()}')
print(f'  Mean BYD w: {formal["weight_BYD"].mean():.4f}')
print(f'  Mean ETF w: {formal["weight_515180"].mean():.4f}')

# Check first active day
active = formal[formal['gross_return'] != 0]
print('\nFirst 3 active days:')
for dt, row in active.head(3).iterrows():
    print(f'  {dt.date()}: gross={row["gross_return"]:.6f}, BYDw={row["weight_BYD"]:.3f}, ETFw={row["weight_515180"]:.3f}')

# Period breakdown
for wname, (wstart, wend) in {
    'dev': ('2019-11-26', '2022-12-31'),
    'val': ('2023-01-01', '2024-12-31'),
    'rp25': ('2025-01-01', '2026-08-03'),
}.items():
    mask = (formal.index >= wstart) & (formal.index <= wend)
    wf = formal_ret.loc[mask]
    ww = (1 + wf).cumprod()
    wy = len(wf) / 252.0
    wcagr = float(ww.iloc[-1] ** (1 / wy) - 1) if wy > 0 else 0
    print(f'  {wname}: CAGR={wcagr:.4f} ({wcagr*100:.2f}%), n={len(wf)}')
