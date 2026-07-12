# Issue #124 CN/US real-market evidence

Generated on 2026-07-12 from commit `0c4220da807309bbd048c59eb8d417230baf068a`
(`origin/main`, including PR #123).

## Execution contract

- Data refresh command: `uv run python scripts/update_data.py --full --start 2021-01-01 --market all`
- CN pipeline command: `uv run python scripts/run_real_market_research.py --root . --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml`
- US pipeline command: `uv run python scripts/run_real_market_research.py --root . --spec configs/research_paradigms/us_10d_qqq_baseline.yaml`
- Provider directory: `data/watchlist`
- Provider instruments: CN 176, US 137, HK 5 (318 total)
- `fixture_manifest.json`: absent
- Data refresh exit code: 1
- Data refresh block: `quality coverage mismatch for market=cn: expected=233 actual=176`

No synthetic data, fixture provider, zero-filled replacement, copied instrument metadata,
or manually fabricated evidence was used.

## CN acceptance

- Pipeline exit code: 2
- Manifest status: `blocked`
- Acceptance counts: 6 passed, 1 warning, 3 failed
- Versioned research universe: 223 requested, 166 fully covered, minimum 50
- Provider market instruments: 176
- Provider calendar: 2021-01-04 through 2026-07-10
- Declared interval: 2021-01-01 through 2026-06-18
- Benchmark: `000300`, excluded from ranking, but missing full provider coverage
- CSV integrity: failed; 166 inspected, 20 invalid, 0 missing
- Invalid CSV symbols: `000333`, `002304`, `002555`, `002558`, `600000`,
  `600016`, `600028`, `601166`, `601169`, `601225`, `601229`, `601328`,
  `601600`, `601658`, `601668`, `601800`, `601808`, `601919`, `601998`,
  `603833`
- Committed acceptance SHA-256: `5a12ab2e6342a72da239b7e6f5375a200b30d6d8fb095e08b13120c307b8bf95`

Blocked checks:

1. `calendar_coverage`: provider starts on 2021-01-04 while the declared interval starts
   on 2021-01-01.
2. `benchmark_provider_coverage`: reference benchmark `000300` is missing or lacks full
   coverage.
3. `source_csv_integrity`: 20 fully covered candidate CSVs contain invalid OHLCV rows.

The survivorship-bias check warned because the current static curated membership is suitable
only for exploratory research, not an unbiased historical estimate.

## US acceptance

- Pipeline exit code: 2
- Manifest status: `blocked`
- Acceptance counts: 7 passed, 1 warning, 2 failed
- Versioned research universe: 133 requested, 120 fully covered, minimum 30
- Provider market instruments: 137
- Provider calendar: 2021-01-04 through 2026-07-10
- Declared interval: 2021-01-01 through 2026-06-18
- Benchmark: `QQQ`, available across the declared interval and excluded from ranking
- CSV integrity: failed; 121 inspected, 2 invalid, 0 missing
- Invalid CSV symbols: `FER`, `KDP`
- Committed acceptance SHA-256: `862045001f59bdd5a3ca74686b1b3c2730ef756b798fbac95fe326cdcfecec27`

Blocked checks:

1. `calendar_coverage`: provider starts on 2021-01-04 while the declared interval starts
   on 2021-01-01.
2. `source_csv_integrity`: `FER` and `KDP` contain invalid OHLCV rows.

The survivorship-bias check warned for the same static-membership limitation as CN.

## Factor-diagnostic disposition

Both manifests record:

- `blocking_stage=real_market_acceptance`
- `stages.real_market_acceptance=rejected`
- `stages.factor_diagnostics=not_run`
- `diagnostic_only=true`
- `promotion_eligible=false`
- `promotion_evaluated=false`
- `trade_ready=false`

Consequently, no `factor_diagnostics.json` was generated for either market. Factor count and
sampled rebalance-date count are both not applicable, and no factor table, ICIR, spread,
return, model-quality, readiness, or promotion claim is reported. This is the required
fail-closed behavior: rejected acceptance prevents factor diagnostics from running.

## Evidence files

- `artifacts/research_runs/cn_10d_csi300_baseline/real_market_acceptance.json`
- `artifacts/research_runs/cn_10d_csi300_baseline/real_market_research_manifest.json`
- `artifacts/research_runs/us_10d_qqq_baseline/real_market_acceptance.json`
- `artifacts/research_runs/us_10d_qqq_baseline/real_market_research_manifest.json`
