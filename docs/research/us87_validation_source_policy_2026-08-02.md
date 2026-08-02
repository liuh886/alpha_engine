# US87 validation-source policy — 2026-08-02

## Canonical source

Yahoo/yfinance remains the governed research-price source for US87 and QQQ.
Its bars, exact identities, cutoff and file hashes determine whether the selected-pool
price component is ready for research.

## Validation sources

Tiingo and Polygon/Massive are independent validation sources only.

- Their files are stored under validator-specific paths.
- They are used for return, opening-price and corporate-action comparison.
- They are never selected as canonical bars.
- Their credentials are not required for canonical research readiness.
- A missing credential, entitlement error or rate limit is recorded explicitly.
- A provider-wide rate limit opens the validator circuit for the remaining shard.
- A material disagreement creates `validation_conflict`; it never silently overwrites
  Yahoo data.

## Training boundary

Only the canonical Yahoo component may enter the current training bundle.
Validator rows and action observations are excluded by source role and provider prefix.
The data remains `research_only=true` and `trade_ready=false`.
