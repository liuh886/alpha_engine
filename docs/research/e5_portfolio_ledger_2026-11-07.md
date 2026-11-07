# E5 phase one — canonical execution ledger

Independent E5 feature PR stacked on #1380. Research only; no original E4/v6
archive, plan, checkpoint or receipt is modified. Only `xgb_p03`, `lgb_p05`,
`rule_momentum60`, `rule_momentum120` from the exact E4 plan are accepted.

## Verified first vertical slices

2026H1 momentum60 and XGB p03 complete-score reconstructions reproduce every
E4 daily gross/net/QQQ/turnover field within original 10-decimal rounding
(5.1e-11), and net return, excess, drawdown, turnover within original 8-decimal
rounding (5.1e-9). Actual XGB p03 net return: 2.3349798954722827; momentum60:
2.2661941800367806. No tolerances were widened to pass a discrepancy.

Original model binaries and full scores were not archived. Only these frozen
recipes are refit as necessary (at most 16 tree config/folds); rebuilt complete
scores are persisted. This is not proof of original fitted model binary
equivalence. All other E4 trials remain untouched and are not rerun.

## Running the maintained tools

Use `uv run --frozen python src/research/e5_score_reconstruction.py --help` to
prepare a source snapshot (`snapshot`) and reconstruct missing scores (`scores`).
Both require the exact pinned native checkout and private E4 driver; imports
are isolated in that subprocess. Required identities: native Git `0c8152496e`,
driver `ff44d808…`, plan `5146093d…`, source history `b4745e46…`.

Then run `uv run --frozen python -m src.research.e5_execution_review --help`.
Supply pinned `--checkpoint`, `--snapshot`, `--scores-root`, `--configuration`,
`--fold` and a new private `--output`. It verifies the entire E4 ZIP, validates
score provenance, records the existing engine, gates on daily/aggregate parity,
then evaluates the separate one-session-delayed close contract. No model fit
occurs in the evaluator. A mismatch returns BLOCKED before new hypothesis work.

Output: original/delayed daily and per-asset Parquet plus `result.json` with
source/code hashes, exact parity errors, contributions and mature 1d/5d IC.

## Accounting and timing contract

The optional ledger sink observes `_simulate_portfolio`; it does not select
positions or duplicate simulation logic. It preserves original `np.argsort`
tie handling, equal weights, drift, half-L1 interior turnover, full entry/exit
turnover and final liquidation. Daily net contribution sums to net return;
NAV-weighted per-asset contributions telescope to final NAV minus one.

Quantities are fractional adjusted-price units per unit pre-fill gross NAV,
not broker shares, lot sizes or actual fills. E4 deducts friction from returns
without simulating fee funding. Cash weights, cost debits, normalized quantities
and this accounting limitation are explicit, not silently corrected.

Original mode uses close-t information at close-t: idealized historical parity
only. Delayed mode uses information available after close-t, an assumed
instruction before the next session's close, that verified adjusted close as
a **price proxy**, and the subsequent close-to-close return interval. Session
and phase are recorded separately; no invented intraday/order/fill timestamps,
verified next-open data, actual spread, participation limit or executable fill
is claimed. Both modes liquidate at the same fold boundary and use 8bps.

Five-session Rank IC uses only signal dates AND fully matured labels within
each OOS fold; the final five signal dates are excluded. One-day IC uses the
same convention (excludes final signal date). These differ from E4's reported
one-day IC which also included the pre-fold anchor signal.

Historical US73 remains retrospective and survivor-biased, non-PIT, and not an
independently untouched holdout. A later-close sensitivity is not a promotion
gate or live-trading claim. Full 4×8 acceptance and interpretation follow only
after the first slices pass.
