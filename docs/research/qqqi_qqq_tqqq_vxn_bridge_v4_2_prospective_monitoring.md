# v4.1 versus v4.2 bridge prospective monitoring

## Purpose

Monitor the frozen v4.1 VXN leverage-veto baseline and the frozen v4.2 50% QQQI / 50% QQQ bridge challenger from the same prospective boundary: 2026-08-01.

This monitor is evidence collection only. It cannot tune, combine, promote or mark either candidate trade-ready.

## Frozen candidates

### v4.1 baseline

- state 0: 100% QQQI;
- state 1: 100% QQQ;
- state 2: 25% QQQ + 75% TQQQ.

### v4.2 bridge challenger

- state 0: 100% QQQI;
- state 1: 50% QQQI + 50% QQQ;
- state 2: 25% QQQ + 75% TQQQ.

The decision state must be identical every session. Only state-1 weights differ.

## Schedule

GitHub Actions runs every Saturday at 14:00 UTC after the Friday US session and may also be dispatched manually.

## Prospective outputs

Each run records:

- QQQ, v4.1 and bridge v4.2 prospective return metrics;
- latest available market date and economic return date;
- latest executed position and weights for both candidates;
- latest close-derived decision and reason;
- every prospective daily gross-return, turnover, cost and net-return difference;
- state-1-specific prospective rows;
- contract hashes, evidence hashes and a `StrategyExperimentJournal` record.

Full-history metrics are recomputed only as context. No return before 2026-08-01 is labelled prospective.

## Interpretation

The retrospective bridge improvement came mainly from lower 0-to-1 and 1-to-0 turnover rather than higher gross return. Prospective review must therefore separate:

1. gross-return difference;
2. turnover and transaction-cost difference;
3. net-return difference;
4. realized state-1 downside behavior.

A positive net result driven only by the assumed 10 bps cost should be stress-tested against realized implementation costs before any promotion decision.

## Review boundary

Do not evaluate the challenger after one or two sessions. Review only after either:

- at least five new state-1 episodes have completed; or
- six calendar months of prospective data have accumulated;

whichever occurs later.

Even then, the decision must consider episode concentration, gross versus cost attribution, slippage sensitivity and whether the exact state trace remained frozen.
