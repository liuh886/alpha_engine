# Fundamental Event Store v1

## Purpose

This foundation supports reusable point-in-time fundamental collection for the
fixed US 87 and CN 130 selected pools. It replaces one-off factor-specific CSVs
with an append-only, source-bound event model.

## Event semantics

Each normalized fact records:

- canonical market, symbol, exchange and entity identity;
- fiscal period identity;
- public report time and model availability time;
- filing/source document and endpoint identity;
- normalized field, value, unit and currency;
- quarterly and derived/source status;
- revision sequence and superseded event identity;
- retrieval time, source SHA-256 and deterministic event ID.

`available_at` cannot precede `reported_at`. Fiscal period end is not accepted as
an availability substitute. Source facts cannot carry hidden derivation rules,
and derived values must declare their calculation.

## Storage boundary

The contract separates:

1. raw provider responses;
2. normalized source events;
3. explicit derived fields;
4. immutable manifests;
5. per-market coverage reports.

No normalized event is allowed to overwrite an earlier revision.

## Coverage audit

`scripts/data/audit_fundamental_coverage.py` reads normalized JSONL events and
compares them with the active selected-pool registry. The output always contains
all 87 US or all 130 CN candidates, including symbols with `no_events` status.

It fails closed on:

- malformed or duplicate events;
- cross-market events;
- symbols outside the selected pool;
- invalid source hashes;
- inconsistent pool counts;
- non-deterministic event identities.

## Next implementation slices

1. generalize the existing SEC Company Facts pipeline from the narrow US pool to
   US 87;
2. add generic `us-gaap` and `ifrs-full` extraction plus reusable filing-instance
   XBRL fallback;
3. add Tushare income, balance-sheet, cash-flow, indicator, forecast and express
   adapters for CN 130;
4. add raw-response caching, checkpointing, deterministic retries and manifests;
5. produce live source-bound coverage artifacts and factor-readiness matrices.

The current PR establishes contracts and reusable validation only. It does not
claim source coverage, factor effectiveness or trade readiness.
