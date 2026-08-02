# Selected-Pool Ranker Retest Contract

## Research question

The previous static-curated US comparison produced strong apparent economics:

- LightGBM LambdaRank compounded QQQ-relative excess: 65.04%;
- XGBoost `rank:ndcg` compounded QQQ-relative excess: 70.35%;
- positive excess windows: 3/4 and 4/4;
- worst drawdown: -27.34% and -25.63%.

That evidence does not transfer automatically to the current opportunity set.
This experiment asks whether the same frozen ranker remains useful inside the
user's fixed selected pools after the price-data foundation has been rebuilt.
It changes the opportunity set, not the model search.

## Declared pools

- US: `us_selected_equities_v2`, exactly 87 equities, with QQQ as reference only;
- CN: `cn_selected_equities_v3`, exactly 130 equities, with CSI 300 as reference only.

Static selected membership is an acknowledged limitation. It is accepted for
this personal-pool research objective and does not establish broad-market
validity.

## Data prerequisite

PR #294 established the source-aware price-data contract used here. Every run
must rebuild the exact market provider with
`scripts/data/refresh_selected_pool_prices_v2.py` and pass all of the following
before model fitting:

- exact candidate and benchmark file sets;
- zero refresh failures;
- provider-manifest hash verification;
- evidence cutoff no later than 2026-06-18;
- no silent ticker substitution, including TIGO versus TYGO;
- `promotion_eligible=true`;
- CN Yahoo-only sources and legacy copied sources are prohibited.

A green network request is not sufficient evidence. Failure of any promotion
gate ends the market run as `selected_pool_ranker_data_blocked`.

## Frozen US replication

The US contract preserves the historical comparison for:

- factor-library declaration;
- LightGBM and XGBoost model families;
- one fixed calibration;
- label and economic-return formula;
- Top-15 and Bottom-15 diagnostics;
- 20 bps cost;
- walk-forward windows and embargo;
- evaluation gates.

Only the universe declaration changes from the old static pool to
`us_selected_equities_v2`.

## CN extension

The CN run uses the same two ranker families, calibration, horizon, Top/Bottom
construction, costs and walk-forward policy. It uses the frozen
`cn_balanced_ohlcv` feature group because the historical US feature IDs are
market-namespaced. This is a cross-market extension, not a byte-identical US
replication.

## Listing and coverage policy

The pool membership remains exactly 87/130. Pre-listing observations are never
fabricated. The runtime may use only coverage-qualified members in a given
window under the previously frozen `alignment_mode=auto` and `min_symbols=30`
contract. Every unavailable or dropped symbol must be reported, and no result
may be described as evidence on all 87/130 simultaneously when a window used a
smaller cross-section.

## No-search boundary

After results are observed, no feature, Alpha158 subset, model parameter,
Top-K, holding period, label, cost, pool membership or benchmark search is
allowed in this experiment. A weak result is recorded as a weak result rather
than tuned away.

## Execution

The GitHub Actions workflow independently rebuilds the promoted US and CN Qlib
providers, verifies the promotion manifest, runs the frozen market contract and
uploads provider identity plus all model evidence.

Local form:

```bash
uv run python scripts/data/refresh_selected_pool_prices_v2.py \
  --market us --source-csv-dir data/csv_clean \
  --output-root artifacts/selected_pool_price_refresh/us \
  --start 2021-01-01 --cutoff 2026-06-18 --max-rounds 1 --full-refresh

uv run python scripts/run_selected_pool_ranker_retest.py \
  --market us \
  --us-provider-uri artifacts/selected_pool_price_refresh/us/data/providers/us
```

Use the equivalent `cn` arguments for the A-share run.

## Interpretation

After evidence review, each market must be classified as one of:

- `selected_pool_ranker_not_supported`;
- `selected_pool_ranker_research_candidate`;
- `selected_pool_ranker_data_blocked`.

`evidence_run_completed` means execution finished; it is not itself a positive
model verdict. No result is automatically trade ready. `trade_ready=false`
remains binding.
