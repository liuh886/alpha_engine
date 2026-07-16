# Issue #124 Current-Contract Real-Market Evidence (2026-07-16)

This report documents the CN and US real-market evidence generated on 2026-07-16 after the Issue #124 pipeline was re-run against the latest `main` branch (post-fix for the yfinance inclusive-end and refresh-quality bugs). The prior evidence packages (`docs/evidence/issue-124/`, `docs/evidence/post-150-current-2026-07-13/`, `docs/evidence/post-160-cn-verification-2026-07-13/`) are not overwritten.

## Provenance

- source main commit: `9c84a0adb8cf4ad6634ebc21d34eb0aded00b53c`;
- evidence generated locally from this working tree (not a CI artifact);
- evidence schemas: `1.3` (acceptance and diagnostics), `1.1` (manifest);
- declared `test_end`: `2026-06-18`;
- research universes: `cn_curated_equities_v1.yaml` (SHA-256 `5b5ba466266f8c7ae4a174207c89381e8658ff7e726bc136d1f856f2abf22215`) and `us_curated_equities_v1.yaml` (SHA-256 `cb311655be341213f70cd0753d88aa33f2afd594691c4704c0ad3b206ef75fd2`);
- declared contract: CN `2ac84cc006830376dcde264824fea223832daadac3b1446e770170dd562d6479`, US `b928b4d42ee8d36b50962ab5d25451df80cd7dfcb3b6727d83a1c3dc78c89732`.

## Pipeline exit code

Both markets completed with **exit code 0** (`status: "completed"`, both stages `"passed"` in their respective manifests).

## Manifest status and stages

| Market | Status | Acceptance stage | Diagnostics stage |
|--------|--------|-----------------|-------------------|
| CN     | completed | passed | passed |
| US     | completed | passed | passed |

## Acceptance check summary

| Market | Pass | Warn | Fail |
|--------|----:|----:|----:|
| CN     | 10  | 1   | 0   |
| US     | 10  | 1   | 0   |

Both markets have one warning: the `survivorship_bias` check notes the universe uses `static_curated` membership as of 2026-07-11, which is acceptable for exploratory research but not an unbiased historical estimate.

## Provider directory and instrument count

| Market | Provider directory | Provider instruments | Requested symbols | Canonical symbols | Covered | Minimum | Unavailable |
|--------|------------------|---------------------:|------------------:|------------------:|--------:|--------:|------------:|
| CN     | `data/providers/cn` | 214 | 223 | 223 | 197 | 50 | 17 |
| US     | `data/providers/us` | 137 | 133 | 133 | 120 | 30 | 0 |

CN unavailable symbols (17): `000786`, `000800`, `000999`, `001979`, `002007`, `002236`, `002252`, `300782`, `600050`, `600837`, `600893`, `601006`, `601009`, `601336`, `601766`, `601878`, `601881`.

CN boundary-failure (partial-coverage) symbols (9): `301291`, `301308`, `301309`, `301666`, `600938`, `601728`, `601989`, `688525`, `688676`.

US boundary-failure symbols (13): `ALAB`, `APP`, `ARM`, `CEG`, `CRCL`, `GEHC`, `HOOD`, `IREN`, `NBIS`, `SNDK`, `TEM`, `TYGO`, `CRDO`.

## Benchmark and CSV integrity

| Market | Benchmark | Benchmark coverage | CSVs inspected | Invalid | Missing | Too short |
|--------|-----------|-------------------|---------------:|--------:|-------:|----------:|
| CN     | 000300    | 2021-01-04 to 2026-07-15 | 198 | 0 | 0 | 0 |
| US     | QQQ       | 2021-01-04 to 2026-07-15 | 121 | 0 | 0 | 0 |

All CSV files pass OHLC order validation (any roundoff artifacts are sub-machine-precision and ignored). CN symbols with ignored roundoffs: `002304` (1), `601898` (1), `601919` (2), `601998` (3), `603288` (1), `603833` (1). US symbols with ignored roundoffs: `FER` (2), `HIMX` (2).

## Provider identity verification

| Market | Provider identity SHA-256 |
|--------|--------------------------|
| CN     | `d34a5f28c024554d84fd9a07ecdf0efe080d6de806ece4f2458a9ce4b8455cd9` |
| US     | `3b28cb19e2ef8e7dba9a7831669600cfed4d96cd13c4bfcccb2c37ca9cd75184` |

## Acceptance and diagnostics SHA-256

| File | SHA-256 |
|------|---------|
| `cn/real_market_acceptance.json` | `8bb137e44667d75face5193670fce6344d10013db749de38a8988fabae4cfcbb` |
| `cn/factor_diagnostics.json` | `8fe3b24fb571ce184462b695fafe0a6157b0779dab91d91bd834bb73481b9042` |
| `cn/real_market_research_manifest.json` | `1c76c0eb4a44d85982cbb7f9b6623e0c18b788b89dff466c1edd8922c009adaf` |
| `us/real_market_acceptance.json` | `a2673567bfa5e3073986b20ea75af6e1206bf7f957afc804a9245ec2bd0cc1d1` |
| `us/factor_diagnostics.json` | `f9655a7917dac97abd90fe4a47bcd466543e77389d1b828c751afc0c4800646b` |
| `us/real_market_research_manifest.json` | `5f9b06114d46f211e7a0d2ca3f8f44a213f1ebfe799cd4dd17abf4ee363f25cc` |

The acceptance SHA-256 values recorded inside each manifest match the computed file hashes above.

## Factor count and sampled rebalance-date count

| Market | Unique expressions | Factor IDs | Sampled rebalance dates |
|--------|------------------:|-----------:|------------------------:|
| CN     | 23                | 47         | 46                      |
| US     | 9                 | 24         | 48                      |

## Compact factor table — CN unique expressions (sorted by oriented ICIR)

Each row represents the first canonical occurrence of a unique expression. `raw Rank IC` and `raw ICIR` are the pre-orientation values; orientation and oriented metrics reflect the pipeline's recommended transformation.

| ID | Expression | Cov | raw Rank IC | raw ICIR | Orientation | Oriented ICIR | Oriented spread | Pos-win ratio | Dir agree |
|:--------|:-----------|----:|----------:|--------:|:------------|------------:|----------------:|:-------------:|:---------:|
| `cn:volatility:std_ret1_5d` | `Std($close/Ref($close,1)-1,5)` | 0.917235 | -0.052425 | -0.221144 | invert_score | 0.221144 | 0.000134 | 0.750000 | true |
| `cn:reversal:ref5_close_inv` | `Ref($close,5)/$close-1` | 0.916845 | 0.040336 | 0.211117 | keep_score | 0.211117 | 0.007986 | 0.500000 | true |
| `cn:momentum:ret_5d` | `$close/Ref($close,5)-1` | 0.916845 | -0.040333 | -0.211100 | invert_score | 0.211100 | 0.007986 | 0.500000 | true |
| `cn:pressure:hl_ratio` | `($high/$low-1)` | 0.917235 | -0.041061 | -0.187186 | invert_score | 0.187186 | 0.008243 | 0.750000 | true |
| `cn:volatility:hl_range_pct` | `($high-$low)/($close+1e-12)` | 0.917235 | -0.040487 | -0.183748 | invert_score | 0.183748 | 0.006748 | 0.750000 | true |
| `cn:liquidity:vol_vs_ma5` | `$volume/Mean($volume,5)-1` | 0.916943 | 0.015437 | 0.132776 | keep_score | 0.132776 | -0.000523 | 0.750000 | false |
| `cn:risk_adjusted:ret20_per_vol20:v2` | `($close/Ref($close,20)-1)/(Std($close/Ref($close,1)-1,20)+1e-12)` | 0.916650 | -0.027315 | -0.127770 | invert_score | 0.127770 | -0.000409 | 1.000000 | false |
| `cn:volatility:std_ret1_10d` | `Std($close/Ref($close,1)-1,10)` | 0.917235 | -0.034588 | -0.121389 | invert_score | 0.121389 | -0.006953 | 0.750000 | false |
| `cn:mean_reversion:close_vs_ma20` | `$close/Mean($close,20)-1` | 0.917235 | -0.025260 | -0.114351 | invert_score | 0.114351 | 0.005496 | 0.750000 | true |
| `cn:risk_adjusted:ret5_per_vol5:v2` | `($close/Ref($close,5)-1)/(Std($close/Ref($close,1)-1,5)+1e-12)` | 0.916845 | -0.018428 | -0.108300 | invert_score | 0.108300 | -0.000949 | 0.500000 | false |
| `cn:momentum:ret_20d` | `$close/Ref($close,20)-1` | 0.916650 | -0.024172 | -0.103386 | invert_score | 0.103386 | 0.000757 | 1.000000 | true |
| `cn:volatility:std_ret1_20d` | `Std($close/Ref($close,1)-1,20)` | 0.917235 | -0.028549 | -0.094628 | invert_score | 0.094628 | -0.009405 | 0.750000 | false |
| `cn:mean_reversion:close_vs_ma5` | `$close/Mean($close,5)-1` | 0.917235 | -0.014593 | -0.086128 | invert_score | 0.086128 | 0.004677 | 0.750000 | true |
| `cn:mean_reversion:close_vs_ma10` | `$close/Mean($close,10)-1` | 0.917235 | -0.016253 | -0.083417 | invert_score | 0.083417 | 0.004695 | 0.500000 | true |
| `cn:liquidity:vol_vs_ma10` | `$volume/Mean($volume,10)-1` | 0.917138 | -0.009068 | -0.071594 | invert_score | 0.071594 | 0.004085 | 0.500000 | true |
| `cn:risk_adjusted:ret10_per_vol10:v2` | `($close/Ref($close,10)-1)/(Std($close/Ref($close,1)-1,10)+1e-12)` | 0.916650 | 0.009746 | 0.050629 | keep_score | 0.050629 | 0.004621 | 0.500000 | true |
| `cn:pressure:ret5_x_vol_shock_10:v2` | `($close/Ref($close,5)-1)*($volume/Mean($volume,10)-1)` | 0.916748 | 0.007356 | 0.046382 | keep_score | 0.046382 | -0.000495 | 0.500000 | false |
| `cn:momentum:ret_10d` | `$close/Ref($close,10)-1` | 0.916650 | 0.008384 | 0.038863 | keep_score | 0.038863 | 0.000855 | 0.500000 | true |
| `cn:reversal:ref1_close_inv` | `Ref($close,1)/$close-1` | 0.917235 | 0.004934 | 0.025357 | keep_score | 0.025357 | 0.003430 | 0.500000 | true |
| `cn:pressure:ret1_x_vol_shock_5:v2` | `($close/Ref($close,1)-1)*($volume/Mean($volume,5)-1)` | 0.916943 | -0.003489 | -0.022881 | invert_score | 0.022881 | -0.003015 | 0.500000 | false |
| `cn:liquidity:vol_vs_ma20` | `$volume/Mean($volume,20)-1` | 0.917235 | -0.001606 | -0.012410 | invert_score | 0.012410 | 0.001024 | 0.500000 | true |
| `cn:momentum:ret_3d` | `$close/Ref($close,3)-1` | 0.917040 | -0.001077 | -0.006269 | invert_score | 0.006269 | -0.002609 | 0.500000 | false |
| `cn:reversal:ref3_close_inv` | `Ref($close,3)/$close-1` | 0.917040 | 0.001075 | 0.006259 | keep_score | 0.006259 | -0.002609 | 0.500000 | false |

**CN interpretation:** The strongest CN unique expression (5-day volatility inverted) has oriented ICIR 0.221144 but a near-zero oriented top-bottom spread (0.000134), indicating weak separation power despite consistent direction. The 5-day reversal and its momentum complement mirror each other near 0.211 oriented ICIR. Several other factors have positive oriented ICIR but negative oriented spread, so their `direction_agreement` is false.

## Compact factor table — US unique expressions

| ID | Expression | Cov | raw Rank IC | raw ICIR | Orientation | Oriented ICIR | Oriented spread | Pos-win ratio | Dir agree |
|:--------|:-----------|----:|----------:|--------:|:------------|------------:|----------------:|:-------------:|:---------:|
| `us:risk_controlled:ret20_per_vol20` | `($close/Ref($close,20)-1)/(Std($close/Ref($close,1)-1,20)+1e-12)` | 0.982926 | 0.043495 | 0.286949 | keep_score | 0.286949 | 0.010407 | 0.500000 | true |
| `us:momentum:ret_20d` | `$close/Ref($close,20)-1` | 0.982926 | 0.048485 | 0.284229 | keep_score | 0.284229 | 0.011093 | 0.750000 | true |
| `us:volatility:std_ret1_20d` | `Std($close/Ref($close,1)-1,20)` | 0.984336 | 0.050903 | 0.168160 | keep_score | 0.168160 | 0.034373 | 1.000000 | true |
| `us:volatility:std_ret1_10d` | `Std($close/Ref($close,1)-1,10)` | 0.984336 | 0.045852 | 0.160755 | keep_score | 0.160755 | 0.026762 | 1.000000 | true |
| `us:momentum:ret_5d` | `$close/Ref($close,5)-1` | 0.984023 | 0.028402 | 0.150492 | keep_score | 0.150492 | 0.009445 | 0.750000 | true |
| `us:risk_controlled:ret10_per_vol10` | `($close/Ref($close,10)-1)/(Std($close/Ref($close,1)-1,10)+1e-12)` | 0.983709 | 0.023469 | 0.141083 | keep_score | 0.141083 | 0.003235 | 0.750000 | true |
| `us:momentum:ret_10d` | `$close/Ref($close,10)-1` | 0.983709 | 0.015510 | 0.079735 | keep_score | 0.079735 | 0.004425 | 0.750000 | true |
| `us:volume:vol_vs_ma20` | `$volume/Mean($volume,20)-1` | 0.984336 | 0.004017 | 0.036704 | keep_score | 0.036704 | 0.009112 | 0.250000 | true |
| `us:volume:vol_mom_10d` | `$volume/Ref($volume,10)-1` | 0.982456 | -0.000947 | -0.011363 | invert_score | 0.011363 | -0.000930 | 0.500000 | false |

**US interpretation:** 20-day momentum and risk-controlled momentum lead the US library but the best oriented ICIR is ~0.29. Volatility expressions show strong positive-window ratios (1.0) and the widest top-bottom spreads, though their ICIRs (~0.16-0.17) are modest. Direction agreement is true for all leading US factors. The risk-controlled leader is positive in only half the OOS windows despite the highest ICIR.

## Diagnostic-status flags

| Market | diagnostic_only | promotion_eligible | trade_ready | research_only |
|--------|:---------------:|:------------------:|:-----------:|:-------------:|
| CN     | true            | false              | false       | true          |
| US     | true            | false              | false       | true          |

`promotion_evaluated` is also `false` for both markets. This pipeline **never promotes** — all outputs are factor diagnostics for review only.

## Initial old-path failure and data-update warnings

The first attempt ran the canonical research command immediately after `update_data`. That updater writes the compatibility provider under `data/watchlist` and source files under `data/csv_source`, while current acceptance requires market-specific providers under `data/providers/{market}`. Both first acceptance attempts therefore rejected six provider/coverage checks and correctly did not run diagnostics. The required `scripts/build_market_providers.py --root . --markets cn us` step then built the canonical providers, after which both pipelines passed.

The full update itself exited nonzero because its current-snapshot quality check found 12 stale CN instruments; it also warned that all 137 US instruments ended before the local run date, which occurred before a complete 2026-07-16 US close was available. Individual provider fallbacks also recorded unavailable symbols and an OHLCV consistency warning for `000001`. These warnings remain in the updater diagnostics and were not replaced with synthetic data or neutral values.

The retained provider covers 197 research symbols with full data across the declared interval (`requested_start=2021-01-01` to `requested_end=2026-06-18`). The provider calendar's effective end session is `2026-06-18` with zero end-boundary gap, confirming the fixed interval is fully covered. The data-update warnings (survivorship bias, OHLC roundoff artifacts) are inherent to static-curated universes and floating-point representation; they do not invalidate the declared-interval research contract.

No model-quality or promotion claim is made from this evidence.

## Interpretation boundary

These outputs are factor diagnostics, not a deployable model or trading signal. Factor-library changes, orientation changes, combination research, model fitting, promotion, or trade readiness require separate reviewed work. This evidence package is raw intermediate output for review before any factor-selection or research decision.
