# Minimal Fundamental Validation Contract

The candidate is the existing equal-weight combination of revenue-growth acceleration and gross-margin year-over-year improvement, evaluated every 20 benchmark sessions.

The canonical candidate keeps the predeclared SMA100 eligibility filter. A no-SMA version is produced only for attribution and cannot replace the candidate after results are observed.

The comparison set is deliberately small:

- canonical fundamental candidate;
- the same factor without SMA100 eligibility;
- equal-weight frozen stock pool;
- QQQ.

The candidate advances only when both development and falsification windows beat QQQ and the equal-weight pool after costs, maximum drawdown is no worse than -35%, annual turnover is no greater than 4.0x, average holding duration is at least 40 sessions, and maximum single-symbol weight is no greater than 40%.

The output is exactly one of:

- `simple_fundamental_factor_not_supported`;
- `simple_fundamental_factor_independent_validation_required`.

No formula, threshold, holding period, stock-pool membership, cost, or SMA window may be changed after the first observed run on the declared evidence.
