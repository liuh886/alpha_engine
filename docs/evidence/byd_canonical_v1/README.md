# BYD canonical adjusted OHLCV v1 evidence

## Decision

- Data-quality status: `canonical_v1_pass`
- Symbol: `002594.SZ`
- Frozen cutoff: `2026-08-03`
- Rows: `3,663`
- Range: `2011-06-30` to `2026-08-03`
- Cross-provider stitching: `false`
- Trade ready: `false`
- Model promotion allowed by this evidence alone: `false`

This evidence closes the market-data portion of Issue #506. It establishes a common data product for later BYD training and backtests; it does not promote BYD V1.0, V1.1, or a new trading model.

## Why the prior inputs were not comparable

The earlier experiments did use adjusted data, but not the same adjustment contract:

- AkShare/Eastmoney supplied a pre-adjusted `qfq` history;
- Yahoo supplied an `auto_adjusted` history;
- the two sources used different adjustment precision, split/session handling, and open-price histories.

The new contract no longer treats those finished adjusted series as interchangeable.

## Canonical price layers

1. **Primary reference/raw OHLCV** — Yahoo `002594.SZ`, fetched with `auto_adjust=false`, `repair=true`, and `actions=true`. These bars retain provider-reported reference prices; dividends are not embedded, while split basis follows the provider history.
2. **Corporate actions** — 11 cash-dividend records and one 3:1 split record, all retained explicitly.
3. **Daily adjustment factor** — same-response `Adj Close / Close`, anchored to `1.0` at the frozen cutoff.
4. **High-precision adjusted OHLCV** — reconstructed from the primary price history and same-provider factor, retaining at least eight decimal places.
5. **Independent raw audit** — AkShare/Eastmoney and AkShare/Sina unadjusted histories are normalized to the current-share split basis and used only for quality control.

A secondary provider can never fill, overwrite, or silently stitch a primary-provider row.

## Final identities

- Primary provider: `yfinance_unadjusted_plus_adj_close`
- Independent selected provider: `akshare_eastmoney_unadjusted`
- Raw SHA-256: `159d72d7770292f0c1a8975e596fc3b41a60e1a364e20c916490740465388510`
- Adjustment-factor SHA-256: `949209c67f361376b784937af87f35c9f86697d50e677132085d78878128d0dc`
- Adjusted OHLCV SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- Corporate-action SHA-256: `c87c85e020ddda4c8af73a268d67971b6a6bd8c3812d405def8a55cce2de00b5`
- Factor-event audit SHA-256: `3b98f7dc8e6205bddb8e19fdb97b635b2c6e84df3e9d20c911d8becf425fbbc7`
- Sealed manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`

## Corporate-action reconstruction

The factor audit detected exactly 12 economically material factor changes:

- cash distributions in 2014, 2016–2026;
- the 2025 3:1 split event;
- unexplained material factor jumps: `0`.

The final adjusted volume preserves the primary provider's volume. Cash-dividend price factors do not inversely rescale volume.

## Independent raw-source audit

| Check | Result |
| --- | ---: |
| Independent rows | 3,654 |
| Common rows | 3,651 |
| Coverage | 99.6724% |
| Open-return correlation | 0.997339 |
| Close-return correlation | 0.999791 |
| Median open-level difference | 0.0000025% |
| 99th-percentile open-return difference | 0.034741% |
| Mean absolute open-return difference | 0.015458% |
| Quality gate | Passed |

Both AkShare/Eastmoney and AkShare/Sina independently passed the same audit. BaoStock was unavailable during the sealed run and is retained as a failed provider attempt rather than silently ignored.

## Quarantined sessions

Eleven sessions were excluded from open-to-open research labels because the open level was disputed by more than 1% or the primary row had zero volume. They were **not** replaced from the secondary source.

- 2015-02-25
- 2015-12-25
- 2017-11-20
- 2018-02-26
- 2018-05-21
- 2018-12-12
- 2018-12-14
- 2021-10-26
- 2021-10-27
- 2025-05-23
- 2026-03-13

Final research-eligible open rows: `3,640`.

The label policy is:

`entry_and_exit_open_must_be_independently_confirmed_and_not_quarantined`

Any ten-session label whose entry or exit uses a quarantined open is set to missing rather than repaired.

## Workflow evidence

- Workflow run: `30884533786`
- Artifact ID: `8882573557`
- Artifact ZIP SHA-256: `c8a67f30c0fc98edeafa7d9bbfe22fedf5dc648dbd331117ce31b97efd08bc7e`
- Contract tests, canonical evidence, Alpha Engine CI, CI Governance, Decision Evidence Contract CI, and Fundamental Event Store CI all passed.

## Required use

Future BYD work must:

- use `adjusted_ohlcv.csv` for features, labels, and return research;
- use the canonical reference/raw layer for execution and corporate-action accounting;
- preserve the sealed data identity in every experiment manifest;
- fail closed when the exact cutoff or independent audit is unavailable;
- never reuse a different provider-adjusted series without opening a new data-version contract.
