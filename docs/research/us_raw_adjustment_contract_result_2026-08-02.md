# US raw-plus-adjustment contract result — 2026-08-02

## Decision

**`deterministic_raw_adjustment_contract_ready`**

One complete US87 + QQQ raw snapshot was fetched and frozen. Two independent
model-input trees and Qlib providers were then materialized from exactly that
same source snapshot. Raw, formula, model-input and provider identities matched
exactly.

This is a data-contract result only. US x1.1 remains unchanged,
`research_only=true` and `trade_ready=false`.

## Evidence identity

- Issue / PR: #389 / #392;
- workflow run: `30742690159`;
- artifact: `8831837784`;
- artifact digest:
  `sha256:e4f4dc7d082b04fe8324333a8d1ecbffb5cbf0e9a319bf75561075e2e444a37d`;
- artifact file count: 1,598;
- instruments: 88 — exact US87 candidates plus QQQ benchmark;
- cutoff: 2026-07-31.

## Deterministic identities

| Layer | SHA-256 |
|---|---|
| Raw OHLCV + Adj Close snapshot | `3848fc1c474a408c67243b48d2c693bc7af531c3a6330069bd3e72bc609d19ad` |
| Adjustment formula | `004d92900c94f687c827bd1b17d8e7ac8e163ec57c4386a2bafe2482b6554c49` |
| Derived model-input CSV tree | `1653a3d5ee0efdbed486aa1ac998ff9ff42baab15b9f09659bf443c41072f939` |
| Qlib provider | `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95` |

Provider A and provider B matched on all four identities.

## Source contract

Every symbol/date retains:

- raw open, high, low and close;
- Adj Close;
- raw volume;
- explicit `adjustment_ratio = adj_close / raw_close`.

The retained source uses:

- Yahoo through yfinance;
- `auto_adjust=False`;
- `repair=False`;
- canonical 17-significant-digit CSV serialization;
- exact file-level SHA-256 inventory.

TIGO and TYGO remain distinct members of the exact selected-pool identity. QQQ
remains a benchmark and does not enter the candidate pool.

## Formula contract

Formula version: `us_raw_adjustment_v1`.

- adjusted close equals Adj Close exactly;
- adjusted open/high/low equal raw open/high/low multiplied by the adjustment
  ratio;
- volume remains raw volume;
- amount equals adjusted close multiplied by volume and is declared synthetic;
- compatibility factor remains 1.0;
- adjusted OHLC envelope and Adj Close tie-out fail closed.

## Frozen-history gate

The implementation includes an append-only historical policy:

- a current snapshot must retain the exact prior date prefix;
- raw OHLCV, Adj Close and adjustment ratio are compared exactly;
- new dates may append;
- any historical rewrite raises `HistoricalRevisionError`;
- historical upstream changes must be published as a separate evidence
  revision rather than silently replacing the frozen source.

Synthetic tests cover:

- deterministic raw and model serialization;
- formula tie-out;
- valid append-only updates;
- rejection of historical Adj Close revisions;
- deterministic directory identity.

## What this resolves

- Qlib/provider generation is demonstrably deterministic from one frozen raw
  snapshot.
- Model-input adjusted prices no longer depend solely on opaque
  `auto_adjust=True` output.
- Raw source identity and economic model-input identity are separated.
- Upstream historical revisions can be detected before model execution.
- Complete raw and provider evidence is retained in the workflow artifact.

## What this does not resolve

- The new provider does not restate canonical US x1.1.
- No score, selection or economic comparison with canonical US x1.1 has yet
  been completed.
- Issue #358 remains open until US x1.1 can be fitted twice on this provider and
  reproduce identical scores, Top-15 selections, returns and drawdown.
- This result does not support US x1.2 and does not open the consumed 2026H1
  window for selection.

## Next experiment

Use provider identity
`5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`
as one frozen evidence revision and run the effective US x1.1 contract twice.
Require:

1. identical effective model parameters and seeds;
2. identical per-window scores;
3. identical cross-sectional ranks and Top-15 selections;
4. identical 20/40/60 bps economics;
5. a canonical-versus-new-provider comparison covering score correlation,
   selection overlap, return and drawdown;
6. no version promotion from a data migration alone.
