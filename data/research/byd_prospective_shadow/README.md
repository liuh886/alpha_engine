# BYD prospective shadow store

This directory is an append-only research evidence store beginning after the immutable canonical v1 cutoff of 2026-08-03.

## Status

- `research_only=true`
- `trade_ready=false`
- `shadow_only=true`
- canonical V1.0 remains the retained baseline
- rejected V1.3 conditions are observed only; they do not change portfolio instructions

## Files

- `observations/YYYY-MM-DD.json`: immutable signal and data-version record created after that session close;
- `outcomes/YYYY-MM-DD-h05|h10|h20.json`: immutable matured forward-outcome record;
- `ledger.csv`: derived index rebuilt from observation and outcome records;
- `manifest.json`: hashes and record counts.

## Data extension

The latest provider-adjusted history is chain-linked at the frozen 2026-08-03 canonical adjusted close. Existing canonical rows and existing prospective observations are never overwritten. Each new raw row must be independently confirmed; disputed or zero-volume opens are retained but not research eligible.

A provider may retrospectively change its history. That creates a new `extended_adjusted_sha256` for the new observation but cannot rewrite prior observation files. If a previously written outcome would change under a later provider response, the pipeline fails closed rather than replacing it.

## Minimum evidence before a new model contract

At least twelve months, ten completed recovery events, two market states, and the concentration gates in Issue #518 are required. Insufficient event frequency extends the observation period; it does not lower the gates.
