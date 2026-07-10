# Structured 10D Research Paradigm

Architecture for config-driven, fail-closed research paradigm execution.

## Overview

The structured research paradigm system replaces ad-hoc experiment scripts with validated YAML specs, a Qlib-free dry-run mode, and explicit execution dispatch. Every run produces a standard artifact schema under `artifacts/research_runs/`.

## Key Components

| Component | Location | Role |
| :--- | :--- | :--- |
| Paradigm specs | `configs/research_paradigms/*.yaml` | Market, universe, strategy, walk-forward, evaluation, outputs |
| Factor libraries | `configs/factor_libraries/*.yaml` | Structured factor definitions with globally unique ids, factors nested within groups |
| `FactorSpec` / `FactorGroup` | `src/research/factor_library.py` | Frozen factor specs, YAML loading, duplicate-id rejection |
| `ResearchRunPaths` | `src/research/research_artifacts.py` | Standard artifact filenames and safe writers |
| `ResearchParadigmSpec` | `src/research/paradigm.py` | Validated paradigm spec, dry-run, and execution dispatch |
| `validate_research_paradigm_spec` | `src/research/paradigm.py` | Accepts `ResearchParadigmSpec`, validates against contract |
| CLI | `scripts/run_research_paradigm.py` | Entry point with `--dry-run` and `--execute-existing-runner` flags |

## Public API

### factor_library.py

```python
load_factor_library(path) -> dict[str, FactorGroup]
select_factor_groups(library, group_names) -> list[FactorGroup]
factor_groups_to_ranker_feature_groups(groups) -> list[RankerFeatureGroup]
factor_library_manifest(groups) -> dict
```

### paradigm.py

```python
load_research_paradigm_spec(path) -> ResearchParadigmSpec
validate_research_paradigm_spec(spec: ResearchParadigmSpec) -> None
build_ranker_candidates_from_spec(spec, root=None) -> list[RankerGridCandidate]
build_factor_baselines_from_spec(spec, root=None) -> dict[str, str]
run_research_paradigm(spec, root=None, *, dry_run=False, execution_mode=None, output_dir=None) -> dict
```

### research_artifacts.py

```python
research_run_dir(root, experiment_id) -> Path
build_research_run_paths(root, experiment_id) -> ResearchRunPaths
write_json(path, payload) -> None
write_run_status(paths, *, experiment_id, status, reason="", failed_stage="", trade_ready=False, extra=None) -> dict
build_frontend_payload(experiment_id, *, market, benchmark, run_status="", decision_status="", ...) -> dict
build_research_signals_payload(rows, *, market="", experiment_id="", candidate_name="", orientation="", holding_horizon_days=10, trade_ready=False) -> list[dict]
write_top_bottom_signals_csv(paths, rows) -> None
```

## CLI Usage

```bash
# Qlib-free dry run — validates config, writes manifests and frontend payload
python scripts/run_research_paradigm.py \
  --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml \
  --dry-run

# Execute the existing CN runner (boolean flag — dispatches by spec market)
python scripts/run_research_paradigm.py \
  --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml \
  --execute-existing-runner

# Custom output directory
python scripts/run_research_paradigm.py \
  --spec configs/research_paradigms/us_10d_qqq_baseline.yaml \
  --dry-run \
  --output-dir /custom/output/path
```

Exactly one execution mode must be specified. The script fails closed if neither or both `--dry-run` and `--execute-existing-runner` are given. `--execute-existing-runner` is a boolean flag that dispatches to `"cn"` mode when the spec's market is `cn`.

## Notebook Flow

```python
from src.research.paradigm import load_research_paradigm_spec, run_research_paradigm

spec = load_research_paradigm_spec("configs/research_paradigms/cn_10d_csi300_baseline.yaml")
result = run_research_paradigm(spec, dry_run=True)
print(f"Dry run complete: {result['n_candidates']} candidates in {result['run_dir']}")
```

## Schemas

### Research Paradigm Spec (schema 1.0)

```yaml
schema_version: "1.0"
experiment_id: "cn_10d_csi300_baseline"
market: "cn"
benchmark: "000300"

universe:
  source: "configs/watchlist.yaml"
  market_key: "cn"
  min_symbols: 50
  alignment_mode: "auto"

factor_library:
  source: "configs/factor_libraries/cn_ohlcv.yaml"
  groups:
    - "cn_short_reversal_liquidity"
    - "cn_volatility_reversal"
    - "cn_price_volume_pressure"
    - "cn_balanced_ohlcv"

candidate_grid:
  ranker:
    calibrations: [...]
  factor_baselines:
    - "factor:cn_momentum_10d"
    - "factor:cn_reversal_5d"
    - "factor:cn_volatility_10d"
    - "factor:cn_volume_shock_10d"

strategy:
  horizon_days: 10
  holding_days: 10
  rebalance_days: 10
  top_n: 15
  bottom_n: 15
  return_expression: "Ref($close, -10) / $close - 1"  # CANONICAL_10D_RETURN_EXPR
  return_provenance: "raw_forward_return"
  research_only: true

walk_forward:
  first_test_year: 2024
  last_test_year: 2026
  min_windows: 3
  train_embargo_sessions: 10

evaluation:
  benchmark_mode: "reference_only"
  metrics: ["mean_icir", "mean_rank_ic", "mean_spread", "worst_drawdown", "ready_ratio", "positive_icir_ratio", "positive_spread_ratio"]
  gates:
    mean_icir: 0.30          # >= 0.30 (non-lowered)
    worst_drawdown: -0.15    # >= -0.15 (non-lowered; -0.20 rejected)
    ready_ratio: 0.75        # >= 0.75 (non-lowered)

outputs:
  write_readiness: true
  write_factor_manifest: true
  write_candidate_manifest: true
  write_walk_forward_stability: true
  write_decision_pack: true
  write_top_bottom_signals: true
  write_frontend_payload: true
```

### Structured Factor Library (schema 1.0)

```yaml
schema_version: "1.0"
groups:
  group_name:
    description: "..."
    factors:
      - id: "market:family:name"
        expression: "..."
        family: "..."
        description: "..."
  factor_baselines:
    description: "Single-factor baselines for direction diagnostics"
    factors:
      - id: "factor:cn_momentum_10d"
        expression: "$close/Ref($close,10)-1"
        family: "baseline"
        description: "10-day raw momentum baseline"
```

All factor ids must be globally unique across all groups. Empty/missing expressions are rejected at load time. A `factor_baselines` group provides the baseline factors referenced by the paradigm spec.

### Run Artifacts

```
artifacts/research_runs/{experiment_id}/
  experiment_spec.json          # Copy of the paradigm spec used
  run_status.json               # Always written, even for skipped runs
  data_readiness.json           # Data-readiness details when available
  universe_report.json          # Universe coverage details when available
  factor_manifest.json          # Factor library manifest
  candidate_manifest.json       # Ranker grid candidate manifest
  walk_forward_windows.json     # Walk-forward windows when executed
  walk_forward_stability.json   # Stability summary when executed
  model_decision_pack.json      # Decision pack when executed
  model_decision_pack.md        # Human-readable decision pack when executed
  signals_latest.json           # Latest research-only top/bottom signal rows
  top_bottom_signals.csv        # Same signal rows as CSV
  metrics_summary.json          # Compact metrics summary when available
  frontend_payload.json         # Always written, even for skipped runs
```

### Frontend Payload (schema 1.0)

```json
{
  "schema_version": "1.0",
  "experiment_id": "...",
  "market": "cn",
  "benchmark": "000300",
  "run_status": "dry_run_complete",
  "decision_status": "",
  "trade_ready": false,
  "research_only": true,
  "metrics": {},
  "gates": {},
  "readiness": {},
  "top_signals": [],
  "bottom_signals": [],
  "windows": [],
  "artifact_paths": {
    "experiment_spec": ".../experiment_spec.json",
    "run_status": ".../run_status.json",
    "data_readiness": ".../data_readiness.json",
    "universe_report": ".../universe_report.json",
    "factor_manifest": ".../factor_manifest.json",
    "candidate_manifest": ".../candidate_manifest.json",
    "walk_forward_windows": ".../walk_forward_windows.json",
    "walk_forward_stability": ".../walk_forward_stability.json",
    "model_decision_pack": ".../model_decision_pack.json",
    "model_decision_markdown": ".../model_decision_pack.md",
    "signals_latest": ".../signals_latest.json",
    "top_bottom_signals_csv": ".../top_bottom_signals.csv",
    "metrics_summary": ".../metrics_summary.json",
    "frontend_payload": ".../frontend_payload.json"
  }
}
```

`trade_ready` is only set from the model decision pack — never hard-coded. No buy, sell, order, or execution keys are present.

### Latest Research Signals

`signals_latest.json` and `top_bottom_signals.csv` use the same research-only row schema:

```text
as_of_date,market,experiment_id,symbol,side,rank,score,candidate_name,orientation,holding_horizon_days,research_only,trade_ready
```

`side` is limited to `top` or `bottom`. These rows are ranking research outputs only; they are not orders, positions, or execution instructions.

## Fail-Closed Execution

- **Schema validation**: Unknown schema_version → ValueError
- **Contract validation**: `validate_research_paradigm_spec(spec)` checks every key (accepts `ResearchParadigmSpec`, not raw dict)
- **Source existence**: `universe.source` and `factor_library.source` must resolve
- **Alignment**: `strict` or `auto` only
- **Return expression**: Must match `CANONICAL_10D_RETURN_EXPR` from `notebook_lab_contracts`
- **Provenance**: Must be `raw_forward_return`
- **Research only**: `strategy.research_only` must be True
- **Factor ids**: Duplicate ids → ValueError; empty/missing expression → ValueError
- **Duplicate group names**: Rejected at load time
- **Group selection**: Unknown group name → ValueError
- **Gates**: Lowered gates (< 0.30 ICIR, < -0.15 drawdown, < 0.75 ready ratio) → ValueError
- **Horizon**: Non-10 day horizon/holding/rebalance → ValueError
- **Benchmark mode**: Must be `reference_only`
- **Metrics**: Full seven metrics required
- **Execution**: No explicit mode → ValueError; unsupported runner → ValueError
- **Markets**: Only `cn` and `us` accepted
- **Dry-run**: Must not import or initialize Qlib

## Reuse of #91 CN Feature-Quality Flow

The `--execute-existing-runner` boolean flag dispatches to `execution_mode="cn"` when the spec's market is `cn`, calling `scripts/run_cn_10d_validation.py` directly and normalizing its outputs into the standard artifact schema.

## Non-Goals

- No model improvement claims
- No gate rewriting (gates are non-lowered and fixed)
- No alignment/evaluation changes
- No frontend UI, broker, orders, or live trading
- No buy/sell/order/execution keys in any artifact
- No rewriting of `run_10d_experiment`, stability, decision pack, or #91 runner
- No Qlib dependency in factor_library, research_artifacts, or dry-run path
