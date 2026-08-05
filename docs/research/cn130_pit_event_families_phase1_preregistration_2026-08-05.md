# CN130 PIT event families — Phase 1 preregistration

Issue: #556  
Status: research-only; no model training; no return inspection.

## Objective

Build the first governed independent company-information event population for the fixed CN130 universe. This phase covers only:

1. earnings forecasts / profit warnings (`业绩预告`);
2. preliminary earnings releases (`业绩快报`).

It does not tune the previously consumed periodic-report reaction signal and does not inspect 2024–2025 portfolio returns.

## Immutable research identity

- pool: `cn_selected_equities_v3`, exactly 130 names;
- price/trading calendar artifact: `8850463785`, cutoff 2026-08-03;
- calibration R0 ledger artifact: `8927662386`;
- frozen R0/PIT artifact: `8926572265`;
- R0 architecture: four sectors selected by mean global score percentile of each sector's top three scores; Top3 retained inside each selected sector;
- fixed-rebalance audit: every tenth provider session within each frozen half-year ledger;
- recent-event age: no more than 20 provider trading sessions;
- calibration data gates: 2022H2, 2023H1, 2023H2;
- later half-years are coverage reporting only in this issue.

## PIT and source contract

The structured payload is collected from the corresponding Eastmoney dataset through AKShare. Each event must be reconciled to an exact-date CNINFO announcement and retain the primary announcement link before it can be marked `usable`.

- date-only announcements become available on the first provider trading session strictly after the announcement date;
- the announcement date and any effective/execution date are separate fields;
- multiple announcements for the same symbol, event family and fiscal period form an explicit revision chain;
- source-only Eastmoney observations remain in the event store as `partial` evidence but cannot pass a model-eligibility gate;
- provider errors are cached and reported rather than silently dropped.

## Phase 0 gates

A family is fixed-rebalance eligible only when all calibration half-years satisfy:

- recent-event coverage among R0 selected-sector Top3 rows >= 15%;
- at least 30 distinct matched events;
- maximum sector share <= 45%;
- primary reconciliation and first-session mapping >= 95%.

A family is event-driven eligible only when all calibration half-years satisfy:

- at least 60 events whose first eligible session aligns with a daily R0 Top3 name;
- at least 20 symbols and six sectors;
- announcement timestamp, first-session mapping and primary reconciliation >= 95%;
- no single event stage exceeds 70% of aligned observations.

Passing only authorizes a separately preregistered model experiment. It does not create or promote CN x1.1.

## Outputs

- immutable `events.jsonl`;
- exact source-cache receipts and hashes;
- family/half-year coverage and concentration tables;
- overlap matrix;
- provider failure table;
- deterministic decision, manifest and report;
- two complete executions with byte-for-byte comparison.
