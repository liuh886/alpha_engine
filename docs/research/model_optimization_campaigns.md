# Fixed-context model optimization campaigns

Optimization campaigns let multiple agents propose model candidates without
changing the conditions used to compare them. A campaign owner freezes the base
experiment, model-data bundle, factor library, frozen parent model, provider
identity, cutoff, windows, costs, evaluator and bounded search space. Agents edit
only a separate submissions file.

The compiler fails closed when any frozen file or model-data identity changes. It
also rejects undeclared fields, seed changes, out-of-space values, duplicate
candidates and blocked training profiles. All accepted challengers are compiled
into one cross-sectional experiment, so the runner loads the union feature set
once per window instead of launching one full data pass per agent.

## Campaign contract

```yaml
schema_version: '1.0'
campaign_id: us_x1_3_calibration_v1
research_only: true
trade_ready: false

base_experiment:
  path: configs/research_experiments/us_x1_2_calibrated_risk_control_v1.yaml
  sha256: <exact file sha256>

immutable_files:
  - path: configs/factor_libraries/ohlcv.yaml
    sha256: <exact file sha256>
  - path: configs/research_paradigms/us_x1_1_frozen_v1.yaml
    sha256: <exact file sha256>

model_data_bundle:
  root: data/research/model_data_bundle_v1
  bundle_id: <exact model-data bundle id>
  required_ready_profiles:
    - us_selected_price_only_v1

baseline_candidate_id: baseline_7factor
candidate_template_id: risk_controlled_9factor_sampled
max_challengers: 8

search_space:
  factor_groups:
    - [momentum_volatility_volume]
    - [momentum_volatility_volume, risk_controlled_momentum]
  xgb_native:
    learning_rate: [0.03, 0.05]
    colsample_bytree: [0.8, 1.0]
    reg_lambda: [1.0, 2.0]
```

`seed` is intentionally unavailable as a search axis. Add only values that were
pre-registered before candidate results are observed.

## Agent submissions

```yaml
schema_version: '1.0'
campaign_id: us_x1_3_calibration_v1
research_only: true
trade_ready: false
candidates:
  - candidate_id: agent_a_lower_lr
    xgb_native:
      learning_rate: 0.03
  - candidate_id: agent_b_full_columns
    factor_groups: [momentum_volatility_volume]
    xgb_native:
      colsample_bytree: 1.0
```

Compile first, then rebuild the exact provider for the compiled spec, then
execute the verified manifest:

```bash
uv run python scripts/run_model_optimization_campaign.py \
  --campaign configs/research_optimization/us_x1_3_calibration_v1.yaml \
  --submissions configs/research_optimization/submissions/us_x1_3_candidates.yaml \
  --output-dir artifacts/model_optimization_campaigns/us_x1_3_calibration_v1

uv run python scripts/rebuild_active_research_providers.py \
  --spec artifacts/model_optimization_campaigns/us_x1_3_calibration_v1/compiled-experiment.yaml

uv run python scripts/run_model_optimization_campaign.py \
  --manifest artifacts/model_optimization_campaigns/us_x1_3_calibration_v1/campaign-manifest.json \
  --execute
```

The campaign manifest contains one context hash shared by every candidate and a
distinct trial ID for each materialized delta. Execution never updates a formal
baseline automatically; the existing research review and promotion gates still
apply.
