# Governed indicator data plane

Maintained chart indicators are treated like governed data updates: they have a
versioned registry, explicit scope, provenance, a single deterministic formula
implementation, and tests that fail closed. This document defines that contract.
It does not add chart components, market data, RDI values or trading behaviour.

All outputs remain `research_only=true` and `trade_ready=false`. Indicators are
descriptive evidence over observed bars; they are never signals, forecasts or
order instructions.

## Decision: render-time computation, not a committed projection

Governed indicators are computed **at render time** from the already published,
hash-bound market bars (instrument scope) or a governed market series (market
scope) through the registry-bound formula module. No indicator series or latest
values are written into `data/`, `public/` or any other committed artifact.

Rationale:

- The chart layer needs a full series over the selected window, not only a latest
  value. Precomputing every instrument × indicator would duplicate the existing
  bars into roughly `(87 US + 130 CN) × 10` series (plus the market series), while
  every published bar is already available and identity-bound.
- A second copy can drift from the evidence it summarises. Recomputing from the
  exact published bars keeps the indicator's date range, cut-off and values
  provably derived from one source, and makes a stale projection impossible.
- The formulas are deterministic, linear in the number of observations, and
  operate on roughly 10<sup>3</sup> points per instrument. Render-time cost is
  negligible compared with chart rendering.
- Missing or insufficient inputs surface as explicit unavailable states at the
  point of use instead of an empty or partial projection that could be mistaken
  for evidence.

A future screener projection of latest values (for example Top-20 ranks in the
Today view) is a separate work package. If added, it must be generated at sync
time from published market evidence, remain disposable, and retain this registry
and formula module as its authority. This change introduces no such projection.

The registry itself is compiled into the browser bundle as a small generated
TypeScript snapshot; it is governance metadata, not market data.

## Registry

Authority: `configs/indicators/indicator_registry_v1.yaml`.

Generated view: `qlib-dashboard/src/lib/indicator-registry.generated.ts`. The
snapshot embeds the SHA-256 of the YAML bytes and is regenerated, never edited:

```bash
python -m src.governance.indicator_registry --write   # regenerate
python -m src.governance.indicator_registry           # verify (CI gate)
python -m pytest tests/test_indicator_registry.py     # validate and check drift
```

Top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version`, `registry_id`, `created_at`, `status` | Contract identity. |
| `research_only: true`, `trade_ready: false` | Structural research boundary; validation rejects drift. |
| `policy` | Enforced scope/truth flags, not prose: scope isolation, no cross-market use, own-bars-only instrument indicators, exact observed bars, no forward fill/interpolation, no value from insufficient data, render-time derivation, governed market-series publication. |
| `formula_catalog` | Versioned formula identifiers, required parameter names and ordered outputs. Must equal the implemented formula set. |
| `indicators` | Ordered entries described below. |

Each entry carries:

| Field | Meaning |
| --- | --- |
| `indicator_id` | Unique snake_case identity. |
| `scope` | `instrument` or `market`. |
| `kind` | `derived` (formula), `series` (raw governed reference), `reserved` (future family, no values). |
| `market` | Required for `market` scope (`us` or `cn`); forbidden for `instrument` scope. |
| `formula`, `formula_version` | Formula id and implementation version; null for `series`/`reserved`. |
| `inputs` | `instrument_bars` + `field` (`close`/`volume`), or `market_series` + `series_id` (e.g. `us:VIX`). |
| `params` | Exact parameter map; no extra or missing keys. |
| `version` | Indicator definition version. Changing scope, input, formula, params or meaning requires a new version. |
| `status` | `governed`, `research_only` or `blocked`. |
| `description` | Human-readable definition. |
| `provenance` | `authorized_by`, `authorized_on`, `rationale`, `source`. |

Only `kind: derived` or `series` with `status: governed` can emit values.
`research_only`, `blocked` and every `reserved` entry are refused by the formula
module. `series` entries return the exact supplied observations without
additional math; `derived` entries must match a versioned implementation.

### First governed set

Instrument scope, each computed from the instrument's own bars:

| Indicator | Formula | Parameters |
| --- | --- | --- |
| `instrument_sma_20` | `sma` | period 20 |
| `instrument_sma_50` | `sma` | period 50 |
| `instrument_sma_200` | `sma` | period 200 |
| `instrument_ema_12` | `ema` | period 12 |
| `instrument_ema_26` | `ema` | period 26 |
| `instrument_rsi_14` | `rsi` | period 14 |
| `instrument_macd_12_26_9` | `macd` | fast 12, slow 26, signal 9 |
| `instrument_bollinger_20_2` | `bollinger` | period 20, std_dev 2 |
| `instrument_volume_sma_20` | `volume_sma` | period 20 (observed volume) |

Market scope, US only in this set:

| Indicator | Kind | Input | Meaning |
| --- | --- | --- | --- |
| `market_us_vix` | `series` | `us:VIX` | Raw governed VIX close reference; no derived value claimed. |
| `market_us_vix_sma_20` | `derived` | `us:VIX` | 20-session SMA of the governed VIX close. |

`us:VIX` publication belongs to the separate VIX data plane work package. The
maintained source is the CBOE public `VIX_History.csv` fetched through the
governed `cboe_public` adapter: index levels only, explicit zero volume/amount,
strict parse and OHLC-envelope validation, and exact response-hash provenance.
The selected-pool publication treats VIX as an optional reference auxiliary, so
a missing or quarantined VIX is recorded as a scoped gap and never blocks the
candidate pool, benchmark or required formal holdings. Until that plane
publishes `symbols/VIX.json` in market evidence, the module returns
`market_series_unavailable`. No ETF, index proxy or CN substitute is permitted.

**2026-11-17 status:** the first VIX data-plane attempt (Yahoo `^VIX` as a
governed provider auxiliary) was withdrawn. Yahoo's VIX OHLC failed the governed
OHLC envelope check (max absolute drift 22.91), the symbol was quarantined, and
the partial US provider refresh blocked market-evidence publication. Re-enabling
VIX requires a close-only or CBOE `VIX_History.csv` source with explicit
provenance; until then these entries stay unavailable rather than publishing a
repaired or synthetic OHLC series.

**2026-11-19 status:** the governed CBOE close-only `us:VIX` series is now
published with exact observed dates and zero volume. US strategy charts read it
through the shared market-evidence cache and draw a **separate** VIX context pane
below the NAV chart (one VIX axis, never a dual axis). The pane's optional
`VIX SMA 20` line is computed by this registry's `market_us_vix_sma_20` entry.
CN strategy charts are offered nothing, and an absent or 404 unpublished VIX
series renders its reason without a substitute or a retry as another symbol.

The first set also registers one non-executable placeholder:
`market_cn_rdi_reserved` (scope `market`, market `cn`, kind `reserved`, status
`research_only`, input `cn:RDI`, no formula, no params). It claims no values and
exists so a future RDI admission cannot silently reuse a price or US identity.

## Scope model

### Instrument scope

- Reads only the instrument's own observed bars in the instrument's own market.
- May read `close` or `volume`; `volume_sma` must read `volume`, every other
  current formula must read `close`.
- Cannot declare a market, and cannot consume a market series.
- Two markets may run the same registry entry independently because each run
  consumes that instrument's own bars; no series is shared between markets.

### Market scope

- Declares exactly one `market` (`us` or `cn`) and one governed `series_id`
  whose prefix must equal that market.
- Can consume only the declared series. A mismatch of market or series identity
  is refused (`cross_market_mismatch`, `series_identity_mismatch`).
- Cross-market indicator use is prohibited by policy. A US instrument chart may
  overlay `us:VIX`; it may never overlay `cn:RDI` or a CN market series.
- Market entries cannot apply the instrument-only `volume_sma` formula.

### Future CN market indicator

Register a new entry with `scope: market`, `market: cn`, the governed
`series_id: cn:<id>`, and either `kind: series` for a raw reference or
`kind: derived` with an implemented formula. It will be computable only for CN
inputs and will not affect US entries. Do not create one entry spanning markets.

### Future instrument-level mined indicator

Register with `scope: instrument`, its own input contract, and `kind: derived`
only after the formula is implemented and versioned. If a mined family is not
yet a per-instrument observed field, register it as `kind: reserved` with
`status: research_only` and no formula so it cannot claim values. A mined
indicator never reads another market's series and never mixes market and
instrument scope in one entry.

## Formula module

Location: `qlib-dashboard/src/lib/indicators.ts`.

It owns the only indicator math used by the chart layer. Page components and
chart adapters call `computeIndicator(entry, input)` or the exported formula
functions; they must not re-implement formulas.

Implementations:

- `sma`, `ema` (SMA-seeded, `alpha = 2/(period+1)`), `rsi` (Wilder smoothing),
  `macd` (SMA-seeded signal EMA; line, signal and histogram start at their own
  first valid date), `bollinger` (population standard deviation), and
  `volume_sma` (SMA over observed volume).
- Inputs are exact observed points with strictly increasing ISO dates. Any
  non-finite value, duplicate/unordered date, non-positive close or negative
  volume rejects the whole input with `invalid_observations`. Nothing is
  forward-filled, interpolated or partially emitted.
- Insufficient history returns `insufficient_observations` with the observed and
  required counts. No numeric value is returned.
- Registry `status`, `kind`, `scope`, `formula`, `formula_version` and `params`
  are checked before computation. Unknown formulas, version mismatches, invalid
  params, scope mismatches, cross-market requests and missing series each return
  a distinct reason.

Unavailable reasons: `not_computable_status`, `scope_mismatch`,
`cross_market_mismatch`, `series_identity_mismatch`,
`market_series_unavailable`, `unsupported_formula`,
`unsupported_formula_version`, `invalid_params`, `unsupported_input_field`,
`invalid_observations`, `insufficient_observations`.

`validateIndicatorRegistry()` re-checks a registry snapshot against the
implemented formula contract and returns every problem found.

## Versioning and provenance

Three independent versions identify an indicator result:

1. **Registry schema** (`schema_version`) governs the YAML contract shape.
2. **Indicator definition** (`version` per entry) changes when scope, input,
   formula id, params or meaning changes. Reusing an id with different semantics
   is prohibited; add a new entry/version instead.
3. **Formula implementation** (`formula_version`, matched to the implementation
   in `FORMULAS`) changes when math or seeding changes. A formula change requires
   a new version plus reference-sequence tests.

The generated snapshot records the SHA-256 of the YAML bytes, so rendered
indicators can be traced to one registry revision. Every entry records Owner
authorization date, rationale and a citing source. Changing an indicator after
observing the same evaluation evidence is prohibited by the repository's
tuning rule and requires a new version with recorded provenance.

## Update path

1. Edit the YAML registry (add or version an entry; keep the policy block).
2. Implement or version the formula in `indicators.ts` and add reference tests.
3. Regenerate the TypeScript snapshot:
   `python -m src.governance.indicator_registry --write`.
4. Run the gates: `python -m pytest tests/test_indicator_registry.py`,
   `npm test`, `npx tsc --noEmit`, `npm run lint`, `npm run build`.
5. The chart work package consumes `INDICATOR_REGISTRY` and `computeIndicator`.
   It renders `available: false` states with their reason and never fabricates a
   series.

Validation is fail-closed: unknown formulas, scopes, kinds, statuses, parameter
keys/values, missing provenance, instrument/market scope mixing, a market series
outside its declared market, volume formulas on the wrong field or market, and
`reserved` entries marked `governed` are all rejected.

## Extending with RDI or another mined indicator

The RDI family is represented by `market_cn_rdi_reserved`. It is CN market scope,
has no formula and produces no values. Promotion would require, in order:

1. A governed `cn:RDI` publication contract and evidence (source, point-in-time
   readiness, cutoff, hash) under the owning research workstream.
2. A new registry version that changes the entry from `kind: reserved`/
   `status: research_only` to `kind: series` or `kind: derived` only after the
   required qualification is recorded in provenance.
3. For a derived family, a versioned formula implementation with reference
   sequences and explicit insufficient-data behaviour.
4. Tests proving the entry remains CN market scope, cannot be consumed by US
   inputs, and emits no value before qualification.

Until all four exist, the module returns `not_computable_status` even if a caller
supplies a `cn:RDI` series. The same pattern applies to any future mined family:
register identity and scope first, keep it non-executable, and admit values only
through a versioned registry and tested formula. RDI values, scores, forecasts or
trading claims are not introduced by this data plane.

## Boundaries

- No chart component changes; the chart package follows.
- No new dependency, no committed market data, no generated indicator series.
- No RDI values or claims; no cross-market indicator use; no CN VIX or proxy.
- `research_only=true`, `trade_ready=false` remain enforced by validation and
  tests.
