# Selected-pool event population execution

## Scope

This implementation converts the previously merged source adapters into one exact-pool execution path for:

- US87 SEC Company Facts fundamentals and Yahoo explicit dividends/splits;
- CN130 Sina statement values joined to CNINFO disclosure dates and Eastmoney explicit dividends.

Validation providers remain outside canonical event stores.

## Outputs

For each market the command writes:

- `fundamentals/events.jsonl`;
- `fundamentals/coverage.json`;
- `fundamentals/component_manifest.json`;
- `corporate_actions/events.jsonl`;
- `corporate_actions/coverage.json`;
- `corporate_actions/component_manifest.json`;
- `event_population_manifest.json`.

Every selected symbol must have an explicit status. Empty corporate-action history is recorded as `no_event_observed`; provider and identity failures remain visible and lower readiness.

## Usage

```bash
uv run python scripts/data/populate_selected_pool_events.py \
  --market us \
  --start 2021-01-01 \
  --cutoff 2026-07-31 \
  --output-root artifacts/data/event_population/us
```

Use `--market cn` for CN130. Add `--price-manifest`, `--model-data-output` and `--frontend-data-dir` to compose the event components with an immutable selected-pool price snapshot through `model_data_bundle_v1`.

## Readiness semantics

Fundamentals count a symbol as ready only when point-in-time events are present. Corporate actions count a successfully queried no-event result as covered. Missing identity, provider failure and unresolved conflict are never hidden.

## CI and live evidence

Pull requests build exact 87/130 fixture artifacts without external calls. Main pushes, monthly schedules and manual runs execute the public-primary clients and upload source-bound artifacts. The issue should close only after a live artifact is reviewed; a green fixture build is not presented as live coverage.

All outputs remain research-only and `trade_ready=false`.
