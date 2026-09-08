# CN_27 V1.3 formal research release

CN_27 V1.3 was published on 2026-09-07 as an independent formal research
baseline after explicit user direction to release now and accumulate forward
evidence over time. It is registered as strategy `cn_27`, model family
`cn_27_rotation`, model version `cn_27_v1_3`.

This decision does not rewrite the historical experiment. The frozen screen
remains unsupported: 19 of 21 gates passed, while timing-perturbation Sharpe
and bootstrap Sharpe p05 failed. Prospective validation remains `pending`.
Every artifact is `research_only=true` and `trade_ready=false`; no order
submission or live-trading claim is authorized.

## Published model

The fixed recipe is `k2_projected_22_45_n8`:

- frozen seven-factor CN_27 V1.2 signal;
- 12-name selection with sector membership limits;
- 120-session, 50% shrinkage covariance;
- minimum-distance projection with 22% single-equity-sleeve share, 45% sector
  share, and at least 8 effective names;
- 30-session rebalance cadence;
- signal at session close and execution at the next eligible open, retaining a
  locked target and retrying daily when trading is unavailable;
- asymmetric costs: stock buy 5 bps, stock sell 10 bps, ETF buy/sell 2 bps.

The candidate pool remains the frozen 27-name strategy-specific pool. It is
separate from the governed CN130 model pool and does not claim selected-pool
readiness.

## Historical evidence

The exact k2 path was deterministically reconstructed from the frozen contract
and matched to the sealed candidate summary without reopening model selection.
The native Bundle v2 contains all required formal sections: summary,
performance, risk, robustness, portfolio, trades, attribution, diagnostics,
and lineage.

- evaluation: 2023-09-01 through 2026-09-04, 729 sessions;
- cumulative return: 127.36%;
- CAGR: 32.83%;
- annualized volatility: 23.14%;
- Sharpe: 1.1567;
- maximum drawdown: -19.50%;
- annual one-way turnover: 1.6606x;
- double-cost Sharpe: 1.1479;
- all six chronological folds positive;
- parameter-neighborhood minimum Sharpe: 1.0808;
- leave-one-sector-out minimum Sharpe: 1.1021.

The failed frozen requirements remain explicit:

- worst timing-perturbation Sharpe: 0.8293 versus 0.90 required;
- block-bootstrap Sharpe p05: 0.2552 versus 0.30 required.

## Publication artifacts

- model contract: `configs/models/cn_27_v1_3.yaml`;
- explicit promotion receipt:
  `data/research/experiment_receipts/cn_27_v1_3_user_directed_promotion_v1.json`;
- formal publication receipt:
  `data/research/experiment_receipts/cn_27_v1_3_formal_publication_v1.json`;
- governed source package:
  `data/research/historical_model_evidence/cn_27_v1_3.json`;
- preview/formal catalogs: `data/research/model_runs/catalog.json` and
  `data/research/formal_model_runs/catalog.json`.

Rebuild and verify the release with:

```bash
python scripts/publish_cn_27_v1_3_user_directed.py
```

The publisher verifies the frozen discovery manifest and every source hash,
replays the exact recipe, reconciles attribution, reproduces the retained
metrics and bootstrap result, validates the complete formal Bundle v2, and
checks catalog parity with the active strategy registry.

The release retains the frozen source OHLCV and predecessor/discovery evidence
under the original `artifacts/evidence/cn_27*` and
`artifacts/evidence/cn_all_weather_alpha_rotation_v1` paths in Git. A fresh
checkout can verify the sealed hashes and reproduce the release without a
local download cache or an expiring workflow artifact. Install the locked
dependencies with `uv sync --frozen --extra dev` before running the publisher.

The separate `all_weather_alpha_rotation_v1` research candidate is preserved in
`configs/strategies/research_candidates.json`. The active strategy registry
accepts formal baselines only; candidate research remains available through its
existing contracts and runners without entering the formal publication gate.

## Prospective accumulation

Forward observations must be strictly after 2026-09-04. The parameters, pool,
costs and execution policy remain unchanged for at least 12 calendar months and
an expected minimum of 240 sessions. Each cumulative source package must retain
provider identity, raw and adjusted OHLCV, corporate actions, listing and
tradability events, extraction/query metadata, revision policy and hashes.

Run the frozen observation cycle with:

```bash
python scripts/run_cn_27_v1_3_prospective.py \
  --source-manifest PATH/TO/source_manifest.json
```

The runner is append-only and retains daily targets, executed weights, deferred
trades, costs, turnover and equity. A later successful prospective result may
confirm the baseline and open a separate trade-readiness review; it is not
required for the present formal research publication and cannot retroactively
change the historical gate result.

## Rollback

Rollback removes the `cn_27` entry from `configs/strategies/registry.json` and
the CN_27 record from the two active Bundle v2 catalogs, while retaining the
receipts and formal bundle as immutable historical audit evidence. CN130
`cn_x1_2` and all other active strategy identities are unaffected.
