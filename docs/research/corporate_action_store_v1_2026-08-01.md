# Corporate Action Store v1

## Purpose

This store separates continuous research prices from executable market prices.
It covers the fixed US 87 and CN 130 selected pools and applicable reference
ETFs without treating indices as companies.

## Two price roles

- **Adjusted OHLCV** is used for features and return labels.
- **Raw OHLCV** is used for execution simulation and event accounting.

Source files remain immutable. Rebuilt adjusted series are written as derived
artifacts and bind to a declared adjustment cutoff.

## Event semantics

Each event records entity identity, event type, effective dates, cash or ratio
terms, source lineage, retrieval identity, revision chain, confidence and
reconciliation status. Deterministic event IDs prevent duplicate ingestion.

The initial event set includes dividends, stock dividends, splits, rights
issues, issuance, ticker/exchange changes, mergers, spin-offs, delisting,
suspension/resumption and ETF distributions/splits.

## Cutoff-anchored adjustment

`rebuild_adjusted_ohlcv()` requires a positive daily adjustment factor for every
raw bar. Prices are scaled by the date factor relative to the declared cutoff
factor; volume is scaled inversely. A later corporate action cannot silently
change an evidence build whose cutoff and factor table are already manifest
bound.

The function rejects:

- duplicate raw or factor dates;
- missing factors;
- non-positive factors;
- a cutoff without exactly one factor;
- invalid rebuilt OHLC relationships.

## Coverage audit

`scripts/data/audit_corporate_action_coverage.py` enumerates every selected
candidate. A symbol with no observed event receives `no_event_observed`; it is
not silently omitted. Conflicting events are reported as blockers.

## Next implementation slices

1. Yahoo dividend/split and SEC identity-change adapters for US 87;
2. Tushare adjustment-factor, dividend, suspension, share and name-change
   adapters for CN 130;
3. BaoStock raw/qfq reconciliation at frozen cutoffs;
4. live per-market coverage and discontinuity reports;
5. training/backtest APIs that require the caller to choose raw or adjusted
   fields explicitly.

This foundation does not claim live source completeness or trade readiness.
