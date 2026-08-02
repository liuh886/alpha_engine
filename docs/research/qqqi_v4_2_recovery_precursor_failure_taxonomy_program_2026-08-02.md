# v4.2 recovery-precursor failure taxonomy program

**Issue:** #368  
**Status:** diagnostic, research-only, not trade-ready

## Question

Can the failed 2020–2023 recovery precursors be distinguished from successful
episodes using information already observable at the signal close or
next-session open?

## Frozen boundaries

The analysis reuses the exact QQQ proxy, v4.2 state trace, precursor dates,
25% and 50% allocations, state-2 allocation, next-open execution and 10 bps
cost from PR #364. It does not search a threshold, fit a classifier, or change
an alert.

## Event record

Each event records shock-memory age, distance to the existing 20/50/200-session
repair references, VIX and VXN level/change/margins, state-1 age, prior state,
next-open gap, 1/5/10/20/40-session QQQ and TQQQ outcomes, 40-session favourable
and adverse excursion, subsequent state transition and 50%-versus-25% return.

## Diagnostic standard

A feature is descriptively stable only when its successful-minus-failed median
direction survives at least 80% of leave-one-event-out folds in both the full
sample and the early segment, has the same direction in those two views, and
shows a pairwise separation at least 0.15 away from random ordering.

Even then, it may only be added to prospective evidence collection. A new rule
requires both successful and failed events in the late segment; the current
post-2024 sample contains only successes, so this analysis cannot promote a
trading rule by construction.
