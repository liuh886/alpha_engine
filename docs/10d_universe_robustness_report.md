# AlphaEngine 10D Universe Robustness Report

## Status

**Evidence generated**: 2026-07-07 via `scripts/run_best_blend_universe_robustness.py` against local
Qlib data. **All three universes skipped** due to insufficient historical date coverage — no
walk-forward evidence was produced. See coverage table below.

## What this validates

The #86 best 50/50 ranker + inverted momentum blend is the current strongest research candidate on a
10-symbol default watchlist. This robustness pass tests the frozen calibration/blend across three
fixed universe tiers:

| Universe | Source | Target symbols |
|---|---|---|
| `default_10_symbols` | Session symbols (typically 10) | ~10 |
| `expanded_50_symbols` | Session + watchlist + instrument files + Qlib | 50 total (nested) |
| `expanded_100_symbols` | expanded_50 + broader Qlib instruments | 100 total (nested) |

Universes are **nested**: `expanded_50_symbols` contains all `default_10_symbols` plus
locally-discovered symbols up to exactly 50 total; `expanded_100_symbols` contains all
`expanded_50_symbols` plus additional symbols up to exactly 100 total. Each tier is a
strict superset of the prior tier. Preserves local source order; symbols are never
invented. When local discovery yields too few symbols for a tier the coverage layer
marks it **skipped** — no evidence is generated.

**Frozen configuration** (no parameter search):

| Component | Setting |
|---|---|
| Ranker feature group | `momentum_volatility_volume` (7 expressions) |
| Ranker calibration | gain5, round100, leaves31, leaf10, lr0.05 |
| Ranker candidate name | `lgbm:daily_ranker:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05` |
| Blend weight | ranker0.5 / momentum0.5 (single 50/50 blend via `build_blend_candidates`) |
| Blend candidate name | `blend:ranker_momentum:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5` |
| Baseline | `factor:historical_momentum_10d` (historical momentum 10D, `$close/Ref($close,10)-1`) |
| Windows | half-year rolling, expanding training, 10-session embargo |
| Labels | canonical raw 10D forward returns (`Ref($close, -10) / $close - 1`) |

**Candidate naming contract**: Every rolling experiment must include exactly three
candidates — the frozen ranker, the 50/50 blend (produced by `build_blend_candidates`,
not manually composed), and the baseline factor.  Use `build_required_candidate_names()`
to produce the contract-correct names.

## Coverage

Coverage validates **actual date data**, not instrument-name existence. The runner loads
a minimal canonical field (`$close`) over the full evaluation range via
`load_symbol_date_coverage()`, and `filter_universe_by_coverage()` checks that each symbol
has usable data spanning the required `train_start` through `test_end`.  A documented
calendar-boundary tolerance of 14 calendar days prevents unfairly dropping symbols listed
or delisted near the range edges.  Severe missing coverage is never filled — the universe
is skipped with an explicit reason.

Coverage is **fail-closed**: symbols without sufficient date data are dropped, and
universes retaining fewer than `min_symbols` are **skipped** — they produce no evidence
and `retained_symbols` is emptied so an insufficient universe cannot leak symbols
downstream.

The `coverage_report.json` artifact records per-universe:

- `requested_symbols` — symbols listed in the universe spec
- `available_symbols` — symbols with sufficient date coverage (derived from actual data)
- `retained_symbols` — symbols meeting the min_symbols gate (empty when skipped)
- `dropped_symbols` — symbols dropped due to insufficient date coverage
- `coverage_ratio` — retained / requested
- `date_coverage` — per-symbol records with `first_valid_date`, `last_valid_date`,
  `observations`, and `sufficient_coverage` (nulls for symbols with no data)
- `date_range` — requested evaluation range `{start, end}`
- `sufficient` — whether retained >= min_symbols
- `skipped` — true when insufficient (no evidence generated)
- `skip_reason` — human-readable reason when skipped (e.g. "insufficient date coverage")

Symbol sources are discovered only from local `session_config.json`, `configs/watchlist.yaml`,
`data/watchlist/instruments/{market}.txt`, and Qlib instrument listings. Symbols are never
fabricated.

### Input validation

`validate_no_nan_inputs()` guards against all-NaN or NaN→0-filled features/returns.
Universes with unusable inputs are skipped with an explicit reason rather than
manufacturing model inputs from zeros.

## Coverage results

| Metric | default_10 | expanded_50 | expanded_100 |
|---|---|---|---|
| Requested symbols | 10 | 50 | 100 |
| Data present | 10 | 49 | 98 |
| Sufficient / full-range | 0 | 2 | 5 |
| Retained (after min gate) | 0 | 0 | 0 |
| Minimum required | 10 | 50 | 100 |
| Decision | skipped | skipped | skipped |

- **Required date range**: 2021-01-01 through 2026-06-18
- **Local US series**: generally start 2021-04-05 and extend through 2026-06-24
- **Coverage gap**: early 2021 (Jan–Mar) absent; no symbol satisfies the full-history gate.
- **n_evaluated**: 0
- **n_skipped**: 3
- **decision_status**: `no_universe_evaluated`
- **trade_ready**: `false`

Historical context only — #86 default baseline (0.255122 mean ICIR / −0.112241 worst drawdown /
0.25 ready ratio) is not revalidated by this run.

## Decision

**Result: no universe evaluated.** Coverage insufficiency across all three nested tiers
prevents validating any stronger-research status. Trade-readiness gates cannot be assessed.

## Warning

**This research is not trade-ready by default.** Universe robustness validation is one of several
required validation dimensions. The `trade_ready` field is ``true`` **only** when all three gates
pass for the best-evaluated universe. Stronger research status does not authorize live trading,
automated execution, or position sizing. All research evidence must pass trade-guidance gates
before any operational use.

## Recommended next steps

This run produced no walk-forward evidence. The single required next step before any
blend-tuning or factor-quality work is:

1. **Extend/align historical Qlib data coverage** to cover the full 2021-01-01 through
   2026-06-18 evaluation range (missing early 2021). Rerun universe robustness once
   coverage gates pass.

No factor-quality conclusion can be drawn from this run.
