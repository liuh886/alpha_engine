# US x1.1 data reproducibility experiments — 2026-08-02

This record extends the durable US x1.1 growth ledger. It covers the provider
reproducibility work completed after the native XGBoost grid and pre-registers
the raw-plus-adjustment implementation experiment. All evidence remains
`research_only=true` and `trade_ready=false`.

## Experiment 004 — full US87 provider A/B audit

**Issue / PR:** #358 / #384  
**Workflow / artifact:** `30741031977` / `8831306221`  
**Artifact digest:** `sha256:ffaf90e12703a917553970bf0f1d9876afeac7e5143b822b487cec13079eaa64`  
**Decision:** `unexplained_provider_drift_blocking`, narrowed to adjusted-price
floating recomputation.  
**Version consequence:** no US x1.2 candidate; US x1.1 unchanged.

### Hypothesis

Identical US87 full refreshes should produce the same source CSVs and Qlib
provider when code, environment, universe, dates and provider configuration are
fixed.

### Frozen boundary

- exact `us_selected_equities_v2` plus QQQ;
- 2021-01-01 through 2026-07-31;
- Yahoo through yfinance;
- `auto_adjust=True`, `repair=True`;
- identical code, runner image and provider build path;
- no model training.

### Evidence

Two complete, promotion-eligible refreshes produced different identities:

- refresh A: `cfd029a153a747d4d630f7111e267887080acaec1f4234559100882d28e9a719`;
- refresh B: `a1c4b2188dddf87d5b5bc79c123277433a890cc27853205b0eb339063d9c4ba8`.

Both full source trees and Qlib providers were retained.

### Result

- 41/88 instruments were byte-identical.
- 47/88 instruments changed.
- Every changed instrument retained identical dates, row count, ordering,
  volume and factor.
- Open, high, low and close changed by the same proportional amount within each
  date.
- Changes affected 241–927 historical rows per symbol; median 837.
- Maximum relative OHLC differences were approximately
  `2.19e-7` to `7.69e-7`.
- The proportional ratio varied almost daily, rather than forming the
  piecewise-constant pattern expected from ordinary split/dividend events.

### Quantization falsification

Rounding was not accepted as a fix:

- 4–8 decimal places left all 47 symbols different;
- 3 decimals left 45 different;
- 2 decimals left 40 different and introduced maximum 10-session return error
  around 0.73%;
- four significant digits still left 30 different and introduced return error
  around 0.11%.

### Accepted learning

- Provider generation is deterministic from fixed source CSVs.
- The unstable layer is upstream adjusted source retrieval, not Qlib dumping.
- Sub-ppm input changes can alter tree paths and candidate economics.
- Exact provider identity and complete source retention are necessary.
- Destructive price rounding is not an acceptable reproducibility policy.

### Rejected learning

- The differences are not metadata-only.
- They are not row/calendar changes.
- They cannot be silently treated as economically irrelevant.
- They do not justify replacing the canonical US x1.1 provider.

## Experiment 005 — Yahoo adjustment-mode isolation

**Issue / PR:** #386 / #388  
**Workflow / artifact:** `30741674075` / `8831499091`  
**Artifact digest:** `sha256:7e46de8dd9943e805cc4a4ac7fb99d096ecdc9a38f10624f64201925240c83e1`  
**Decision:** `bounded_subset_reproducible`  
**Version consequence:** no model or production-adapter change.

### Hypothesis

The prior full-pool drift may be caused by `repair=True`, yfinance local
auto-adjust computation, Yahoo Adj Close, or raw Yahoo OHLCV.

### Pre-registered subset

AAPL, ASML, AVGO, GOOGL, META, MSFT, NVDA, QQQ, TSM and VRT.

### Modes

Every symbol was downloaded twice under:

1. `auto_adjust=True`, `repair=True`;
2. `auto_adjust=True`, `repair=False`;
3. `auto_adjust=False`, `repair=False`, retaining raw OHLCV and Adj Close.

### Result

| Mode | Exact A/B matches | Material matches at 1e-8 |
|---|---:|---:|
| adjusted plus repair | 10/10 | 10/10 |
| adjusted without repair | 10/10 | 10/10 |
| raw OHLCV plus Adj Close | 10/10 | 10/10 |

Repair-on and repair-off frames were exactly equal for all ten symbols in both
passes. Adjusted OHLC derived independently from raw OHLC and
`Adj Close / raw Close` matched yfinance auto-adjust materially for every
symbol. Only TSM showed machine-order differences around `1.19e-16`; no
comparison exceeded the `1e-8` economic tolerance.

### Accepted learning

- `repair=True` is not supported as the necessary cause of the prior drift.
- Local auto-adjust arithmetic is deterministic when raw OHLC and Adj Close are
  fixed.
- Raw OHLCV and Adj Close can be exact within a bounded immediate A/B run.
- The remaining likely layer is upstream historical adjustment snapshot timing,
  caching or revision between separately timed retrieval batches.

### Rejected learning

- This bounded null result does not invalidate the full US87 drift evidence.
- It does not prove that future Yahoo historical responses will remain stable.
- It does not close #358 or support US x1.2.

## Experiment 006 — deterministic raw-plus-adjustment contract

**Issue / branch:** #389 / `data/us-raw-adjustment-contract-v1`  
**Status:** pre-registered and running.  
**Parent model:** US x1.1 remains unchanged.

### Hypothesis

A source contract that retains raw OHLCV and Adj Close separately, then derives
adjusted model inputs through one explicit formula, will reproduce identical
model-input and Qlib-provider identities when the frozen raw snapshot is held
constant.

### Allowed changes

- data representation and provider-contract revision;
- explicit adjustment-ratio evidence;
- canonical deterministic serialization;
- append-only historical-prefix gate;
- complete snapshot retention.

### Forbidden changes

- US87 membership or QQQ role;
- US x1.1 features, label, model parameters or portfolio;
- canonical US x1.1 provider or historical evidence;
- model-version promotion;
- use of 2026H1 for candidate selection.

### Formula contract

- `adjustment_ratio = adj_close / raw_close`;
- adjusted close equals Adj Close exactly;
- adjusted open/high/low equal raw values multiplied by the ratio;
- volume remains raw volume;
- amount is a declared synthetic field, adjusted close multiplied by volume;
- provider compatibility factor remains 1.0;
- formula version and SHA-256 are persisted.

### Required gates

1. exact US87 plus QQQ source identity;
2. raw source snapshot stored with exact file hashes;
3. two materializations from the same raw snapshot produce identical
   model-input identities;
4. both materializations produce identical Qlib provider identities;
5. adjusted close ties exactly to Adj Close;
6. historical-prefix revisions fail closed;
7. complete raw and provider evidence is retained;
8. decision is one of:
   - `deterministic_raw_adjustment_contract_ready`;
   - `model_input_identity_not_reproducible`;
   - `upstream_source_revision_still_blocking`.

### Version consequence

Passing this experiment creates a data-contract revision only. It does not
change US x1.1. A separate follow-up must reproduce US x1.1 scores and economics
on the new deterministic provider before #358 can close.

## Updated research order

1. complete Experiment 006 and freeze its raw/provider artifact;
2. rerun US x1.1 twice on the same deterministic provider and compare scores,
   Top-15 selections, returns and drawdown;
3. close or retain #358 according to model-input reproducibility;
4. run #381 drawdown attribution on one frozen provider;
5. execute #362 portfolio controls after #366 sector-map readiness;
6. reserve a genuinely untouched future challenge before any operational claim.
