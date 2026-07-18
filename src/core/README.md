# Notebook-first core interfaces for strategy research

This package exposes notebook-friendly, side-effect-light interfaces so strategy logic can be validated in `ipynb` before being handed to agent workflows.

## Modules

- `signals.py` — load model artifacts and generate per-instrument scores
- `selection.py` — select top-K with optional guardrail filter and bottom-K without filters
- `portfolio.py` — build rolling rebalanced portfolios from MultiIndex panels
- `metrics.py` — compute spread, benchmark-relative alpha, and Information Coefficient series

## Example

```python
from src.core import (
    build_rolling_portfolio,
    compute_ic_series,
    compute_spread,
    generate_scores,
    select_bottomk,
    select_topk,
)

scores = generate_scores(model, feature_df)
long_names = select_topk(scores, k=10, guardrail=True, prices=close, ma=ma60)
short_names = select_bottomk(scores, k=10)

ic = compute_ic_series(score_panel, return_panel)
result = build_rolling_portfolio(score_panel, return_panel, k=10, holding_days=10)
spread = compute_spread(result.long_returns, result.short_returns, bench_returns=bench)
```
