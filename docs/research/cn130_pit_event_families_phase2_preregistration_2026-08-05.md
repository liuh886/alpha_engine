# CN130 primary event families — Phase 2 preregistration

Issue: #563  
Parent: #556  
Base data contract: Draft PR #559.

## Objective

Build and audit primary CNINFO announcement streams for:

1. share buybacks;
2. restricted-share unlock/listing events.

No portfolio return, validation target or model fit is permitted in this phase.

## Why snapshots are prohibited

The Eastmoney buyback dataset reports a latest announcement date and current implementation progress. The restricted-release dataset is indexed by the effective release date. Neither is sufficient to reconstruct historical market availability without overwrite or look-ahead risk.

This phase therefore uses the CNINFO announcement document itself as the source of truth. Structured snapshot data is excluded from the event builder.

## Frozen identity

- pool: `cn_selected_equities_v3`, exactly 130 names;
- provider artifact: `8850463785`, cutoff 2026-08-03;
- calibration R0 ledgers: `8927662386`;
- frozen later R0 ledgers: `8926572265`;
- R0 selected-sector Top3 architecture inherited unchanged from Phase 1;
- every tenth provider session is a fixed rebalance date;
- recent event age is fixed at 20 provider sessions;
- calibration gates: 2022H2, 2023H1, 2023H2;
- later half-years are coverage reporting only.

## Announcement semantics

- query each CN130 symbol from 2022-01-01 through 2026-08-03;
- `announced_at` is the CNINFO date at China Standard Time;
- the first eligible session is strictly later than the announcement date;
- effective and execution dates remain blank unless obtained from a separate reliable PIT source;
- document ID/link, title, source hash and exact receipt are mandatory;
- a known AKShare empty-result column-selection `KeyError` maps narrowly to an empty successful response; all other exceptions remain provider failures.

## Title classification

### Buyback

Ordered stages:

1. completion;
2. first execution;
3. progress;
4. shareholder-meeting approval;
5. plan/proposal.

Exclude equity-incentive cancellation, pledge-style repurchase, reverse-repo, bond-repo and compensation-related titles.

### Restricted unlock

Retain only announcements explicitly describing restricted shares being released and listed for trading. Normalize to `scheduled`. Incentive grants, condition-satisfaction notices without listing language, private-placement approvals and lock-up commitments are excluded.

## Deduplication

- exact document IDs are unique;
- summary and full documents with the same symbol/date/stage/title stem collapse to the full document;
- different stages on the same date remain separate events;
- stage progress is a new event, not a revision overwrite.

## Gates

The unchanged Phase 0 gates from #556 apply independently. Restricted unlock is not authorized for the event-driven path while it remains a single-stage family.

A passing family only authorizes a new preregistered model experiment. It does not modify CN x1.0 or create CN x1.1.
