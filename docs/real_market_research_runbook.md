# Real-Market Data Acceptance and Factor Research

This workflow is the canonical local path for real-market fixed-10D research.
It does not treat synthetic CI data as market evidence and never promotes a
factor or model automatically.

## 1. Install the locked environment

```bash
uv sync --frozen --extra dev
```

## 2. Update the operational market data

A full rebuild from the declared research start date is the cleanest initial
validation:

```bash
uv run python scripts/update_data.py --full --start 2021-01-01 --market all
```

The updater writes source CSV files under `data/csv_source/` and retains the
aggregate compatibility provider under `data/watchlist/`. A warning or partial
update is not equivalent to research acceptance.

## 3. Build canonical market-specific providers

CN and US research must not use the aggregate union calendar. Build independent
providers from the same source CSV evidence:

```bash
uv run python scripts/build_market_providers.py \
  --root . \
  --markets cn us
```

Canonical provider locations are:

```text
data/providers/cn/
data/providers/us/
```

Each provider contains only its own market sessions, instruments, features, and
`provider_manifest.json`. The manifest binds the calendar, instruments, feature
tree, and source CSV hashes into `provider_identity_sha256`. Missing, stale, or
cross-market manifests fail real-market acceptance.

`data/watchlist/` remains a temporary compatibility surface for older consumers;
it is not the canonical provider for fixed-10D CN or US research.

## 4. Run the canonical pipeline

CN:

```bash
uv run python scripts/run_real_market_research.py \
  --root . \
  --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml
```

US:

```bash
uv run python scripts/run_real_market_research.py \
  --root . \
  --spec configs/research_paradigms/us_10d_qqq_baseline.yaml
```

The command runs two ordered stages:

```text
real-market acceptance
  -> spec-bound single-factor diagnostics
```

Factor diagnostics are not executed when acceptance fails.

## 5. Review the evidence

For each experiment, inspect:

```text
artifacts/research_runs/{experiment_id}/real_market_acceptance.json
artifacts/research_runs/{experiment_id}/factor_diagnostics.json
artifacts/research_runs/{experiment_id}/real_market_research_manifest.json
```

The acceptance report is the source of truth for data blockers. Common blockers
include an invalid provider identity, incomplete market calendar coverage,
insufficient fully covered stocks, missing benchmark history, invalid source
OHLCV, and synthetic/test provider markers.

The factor diagnostic report is descriptive research evidence only. Review:

- finite-pair coverage;
- Rank IC and ICIR;
- Top-N minus Bottom-N spread;
- keep/invert orientation;
- per-window consistency;
- explicit static-universe survivorship bias.

## 6. Interpretation boundary

A completed factor-diagnostic run still has:

```text
diagnostic_only=true
promotion_eligible=false
promotion_evaluated=false
trade_ready=false
```

Changing the factor library, candidate grid, or model configuration requires a
separate reviewed commit. Model promotion requires a subsequent spec-bound model
run, execution identity, required evidence, and canonical PromotionDecision.
