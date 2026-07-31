# Factor Knowledge System Tasks

## Task 1 — Registry v2 migration

- extend factor identity and validation schemas;
- add evidence, economics, turnover, risk, applicability, failure, and learning fields;
- make missing required metrics fail closed;
- preserve all legacy rows;
- reclassify legacy Active records as `legacy_unverified` unless current evidence is attached;
- replace the current approximate active-factor correlation check with aligned factor-series evidence.

## Task 2 — Historical evidence backfill

- inventory maintained factor and model reports;
- create deterministic importers;
- generate one canonical card per factor version and market contract;
- report coverage gaps and conflicting historical claims;
- retain rejected hypotheses and lessons learned.

## Task 3 — Relationship map

- materialize aligned score and factor-portfolio series;
- calculate score/return correlations, overlap, churn, and redundancy clusters;
- report market, regime, and basket specificity;
- expose add-one and leave-one-out diagnostics.

## Task 4 — First low-turnover multi-factor contract

- select no more than four primary factors from at least three information families;
- use simple equal weights;
- monthly evaluation, buffers, 40-session minimum holding, and annual turnover <= 4x;
- compare against every standalone factor and the best standalone member;
- require each factor to improve return or reduce risk on a marginal basis;
- freeze before observed evaluation and run once.

## Task 5 — Cumulative market-learning report

- summarize robust findings, clues, failures, redundancies, interactions, and unresolved questions;
- link every statement to factor cards and evidence manifests;
- recommend the next experiment from knowledge gaps, not from ad hoc curiosity.
