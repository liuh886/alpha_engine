# Notebook-first core interfaces for strategy research

This package exposes notebook-friendly, side-effect-light interfaces so strategy logic can be validated in `ipynb` before being handed to agent workflows.

## Modules

- `signals.py` — load model artifacts and generate per-instrument scores
- `selection.py` — select TopN with optional long-side guardrails and BottomN without filters
- `portfolio.py` — build fixed rebalance schedules or rolling holding sleeves
- `metrics.py` — compute spread and benchmark-relative alpha metrics

## Example

```python
from src.core import (
    GuardrailInputs,
    build_rolling_portfolio,
    compute_spread_metrics,
    generate_scores,
    load_model,
    select_bottomn,
    select_topn,
)

model = load_model("models/us_regressor.pkl")
scores = generate_scores(model, feature_df)
long_names = select_topn(scores, 10, guardrail=GuardrailInputs(prices=close, moving_average=ma60))
short_names = select_bottomn(scores, 10)
```
