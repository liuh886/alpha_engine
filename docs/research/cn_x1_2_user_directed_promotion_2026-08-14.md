# CN x1.2 user-directed research-baseline promotion

Date: 2026-08-14

Status: accepted by explicit governance exception; formal bundle transition pending

Boundary: `research_only=true`, `trade_ready=false`

## Decision

The repository owner explicitly directed promotion of the breadth-scaled CN x1.2
candidate after reviewing its completed experiment. The authorization is recorded
in [Issue #954](https://github.com/liuh886/alpha_engine/issues/954#issuecomment-5293367579).

This is a governance exception, not a reinterpretation of the experiment. The
preregistered development result remains **rejected**: 21 of 22 gates passed, and
the sole failure remains `2026h1_drawdown_worsening_within_3pp`.

## Frozen model identity

- CN130 selected universe and CSI300 benchmark;
- 17 canonical factors: the CN x1.1 14-factor OHLCV set plus Alpha158 CNTD30,
  CORD5 and IMIN30;
- frozen XGBoost ranker parameters, 10-session holding/rebalance cadence and
  one-session execution delay;
- four-sector, one-name-per-sector active sleeve;
- active share `clamp(breadth / 0.50, 0, 1)`, with the remainder in CSI300;
- 20 bps base costs and 60 bps stress costs.

## Evidence retained without alteration

Across 2024H1–2026H1, the candidate produced 75.66% compounded relative excess
at 20 bps versus 59.29% for CN x1.1, and 51.56% at 60 bps versus 37.43% for the
incumbent. Aggregate maximum drawdown at 20 bps improved slightly from -14.97%
to -14.77%, four of five windows were positive, and mean Rank IC was 0.03463.
Score and portfolio reproduction were exact.

The exception is material: 2026H1 maximum drawdown worsened from -7.93% for the
incumbent to -12.73% for the candidate, a deterioration of 4.799 percentage
points against the preregistered 3-point limit.

No 2026H2 evidence was used. It remains outside this promotion decision.

## Publication boundary

The active registry declares the CN x1.1 → CN x1.2 transition through the
repository's supported successor mechanism. The existing CN x1.1 formal bundle
remains authoritative until a CN x1.2 bundle is materialized and identity-bound.
Current-target activation must fail closed until that bundle exists; CN x1.1
signals must never be relabeled as CN x1.2.

This release remains research-only and does not authorize live orders,
automated trading, or a `trade_ready` claim.
