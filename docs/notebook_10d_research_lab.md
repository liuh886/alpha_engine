# Notebook-first 10D Research Lab API

This PR keeps the existing notebook flow, but starts moving reusable research logic into backend modules that notebooks can call directly.

## New import pattern

```python
from src.research.notebook_lab_contracts import ResearchSessionConfig
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_research_api import daily_correlation_table
from src.research.notebook_training_api import prepare_training_frame
```

## Canonical 10D contract

The research lab keeps `holding_days=10` and `rebalance_days=10` fixed. The canonical raw return expression is:

```text
Ref($close, -10) / $close - 1
```

Processed labels such as rank or excess labels are training targets only. Economic evaluation should still use raw forward returns with `provenance=raw_forward_return` and `horizon=10`.

## Minimal notebook example

```python
config = ResearchSessionConfig(
    market="us",
    symbols=SYMBOLS,
    benchmark="QQQ",
    train_start="2021-01-01",
    train_end="2024-12-31",
    test_start="2025-01-01",
    test_end="2026-06-18",
    topk=15,
)

# features: DataFrame indexed by (datetime, instrument)
# raw_returns: DataFrame with one `return` column and attrs provenance/horizon
factor_table = daily_correlation_table(features, raw_returns)

result = run_10d_experiment(
    config=config,
    candidates={"factor:momentum": features[["momentum"]]},
    raw_returns=raw_returns,
    output_dir="artifacts/evidence/notebook_10d_lab",
)

result["comparison_report"]["summary"]
```

## Migration scope

This is the first extraction layer only. It does not rewrite every notebook JSON. The next PR can migrate `01_factor_research.ipynb` and `end_to_end_training_pipeline.ipynb` cell by cell to call these APIs.
