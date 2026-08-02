# Model Data Bundle v1

## Purpose

Alpha Engine has multiple governed data products: selected-pool prices, ETF reference data, point-in-time fundamentals, corporate actions and factor definitions. The model-data bundle gives them one common readiness contract so model runners and the Research Artifact Studio no longer infer status from unrelated files.

This layer does not replace source manifests. It indexes their immutable identities and records whether a declared training profile can use them.

## Component states

Every component has exactly one state:

- `ready`: satisfies its own complete promotion contract;
- `partial`: usable only by a profile whose declared minimum coverage accepts it;
- `blocked`: evidence exists but violates a required gate;
- `not_provided`: no usable source evidence was supplied;
- `not_applicable`: intentionally outside the component's market or instrument scope.

A missing or partial component is never silently promoted to ready.

## Supported component types

- selected-pool adjusted prices and provider manifests;
- QQQ / QQQI / TQQQ ETF reference bundle;
- fundamental-event coverage;
- corporate-action coverage;
- factor catalogs and computed factor panels;
- reference-instrument registry evidence.

Each normalized component records:

- component and pool identity;
- source manifest path and SHA-256;
- evidence cutoff and first/last dates;
- expected and ready symbol counts;
- missing, invalid and quarantined symbols;
- providers and professional-source status;
- research/trade boundary.

## Training profiles

A training profile declares the candidate pool, permitted references and required data components. Each requirement declares accepted component states and a minimum coverage ratio.

The evaluator blocks a profile when:

- a required component is absent;
- the component state is not accepted;
- coverage is below the declared minimum;
- component evidence exceeds the run cutoff;
- the component is bound to a different pool;
- a reference instrument appears in the candidate cross-section;
- any component claims `trade_ready=true`.

The initial profiles cover:

- US 87 price-only research;
- CN 130 price-only research;
- US/CN selected-pool research requiring fundamentals and corporate actions;
- the QQQI / QQQ / TQQQ rotation research line.

## Frontend indexes

The builder emits three compact files that can be written directly into the static export's `data/` directory:

- `model-data-readiness.json` — bundle-level status and ready/blocked profile summary;
- `data-components.json` — provider, coverage, cutoff and hash details;
- `training-profiles.json` — declared requirements and failed gates.

The research-bundle exporter classifies them as:

- `data_readiness_index`;
- `data_component_index`;
- `training_readiness_index`.

The root `alpha-engine-bundle.json` also exposes the model-data bundle ID, evidence cutoff and readiness summary. The browser therefore reads the same gate results used by model training.

## CLI

```bash
uv run python scripts/data/build_model_data_bundle.py \
  --evidence-cutoff 2026-07-31 \
  --component prices.us_selected_equities_v2:selected_pool_prices:/path/us-price-manifest.json:us \
  --component prices.cn_selected_equities_v3:selected_pool_prices:/path/cn-price-manifest.json:cn \
  --component references.qqqi_qqq_tqqq_reference_bundle_v1:etf_reference_bundle:/path/bundle_manifest.json:us \
  --output-root artifacts/data/model_data_bundle_v1 \
  --frontend-data-dir artifacts/site/data
```

Additional fundamental, corporate-action and factor components use the same repeated `--component` argument. Components may supply the native known manifest schema or the normalized component schema.

## Tiingo credential evidence

The ETF workflow treats `TIINGO_API_TOKEN` as usable only when all three ETFs:

- pass exact Tiingo identity checks;
- produce adjusted and raw history;
- pass independent Yahoo reconciliation;
- avoid `provider_missing` and `quarantine` states;
- are selected from Tiingo in the canonical bundle.

The workflow writes `tiingo_secret_status.json` containing only configuration/usability state, selected provider names and reconciliation results. The token value is never printed or persisted.

## Boundaries

- Research only; `trade_ready=false` remains mandatory.
- The bundle does not claim unfinished live fundamental or corporate-action coverage is complete.
- It does not modify model features, parameters, labels, portfolio construction or execution.
- It does not permit browser-side training or data mutation.
