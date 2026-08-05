# CN130 holding-change event family — Phase 3 preregistration

Issue: #567  
Parent: #556  
Base data layers: Draft PRs #559 and #564.

## Objective

Build one independent primary-announcement event family for material shareholder and director/supervisor/executive holding changes:

- increase plan;
- increase execution/progress/completion;
- decrease plan;
- decrease execution/progress/completion.

This phase does not inspect returns or train a model.

## Frozen identity

- pool: `cn_selected_equities_v3`, exactly 130 names;
- provider artifact: `8850463785`, cutoff 2026-08-03;
- calibration R0 artifact: `8927662386`;
- later frozen R0 artifact: `8926572265`;
- R0 four-sector Top3 architecture unchanged;
- fixed rebalance every tenth provider session;
- recent-event age fixed at 20 provider sessions;
- calibration gates restricted to 2022H2, 2023H1 and 2023H2;
- later half-years are coverage reporting only.

## Source and PIT rules

- query CNINFO separately for `增持` and `减持` from 2022-01-01 through 2026-08-03;
- normalize CNINFO HTML keyword markup before classification;
- deduplicate exact document IDs across both keyword queries;
- use the first provider session strictly after the announcement date;
- never infer an earlier event from current shareholder balances;
- retain complete success, empty and failure receipts;
- no same-day trading assumption;
- no validation target or return field may be consumed.

## Stages

### Plans

- `increase_plan`: explicit increase plan, proposal, commitment, extension or adjustment;
- `decrease_plan`: explicit decrease plan, pre-disclosure or adjustment.

### Executions

- `increase_execution`: first increase, progress, accumulated increase, completion, result or expiry;
- `decrease_execution`: first decrease, progress, halfway milestone, completion, result, expiry or termination.

Plan and execution announcements on the same date remain distinct events.

## Exclusions

Exclude company buybacks, equity incentives, employee stock ownership plans, passive dilution, judicial transfer, inheritance/property division, pledges, securities lending, legal/broker opinions and generic holder snapshots.

## Phase 0 gates

The unchanged #556 gates apply:

### Fixed-rebalance

- recent-event coverage >= 15% in every calibration half-year;
- at least 30 distinct matched events in every calibration half-year;
- maximum sector share <= 45%;
- source and first-session completeness >= 95%.

### Event-driven

- at least 60 first-post-announcement R0 Top3 observations per calibration half-year;
- at least 20 symbols and six sectors;
- timestamp and first-session completeness >= 95%;
- no single stage exceeds 70%.

A pass authorizes a separate preregistered model experiment. It does not automatically create CN x1.1.
