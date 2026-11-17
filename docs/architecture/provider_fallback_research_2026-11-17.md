# Free market-data provider fallback research (2026-11-17)

Status: **research only**. This document does not implement adapters, add
dependencies, change data, authorize a provider switch, or relax any readiness
gate. The P2 data-first contract explicitly excluded "external provider
fallback" from its implementation scope; this note evaluates whether a later,
separately scoped change is worth proposing. `research_only=true`,
`trade_ready=false` remain in force.

## Why this exists

The QQQ v4.3 formal refresh on 2026-11-17 fetched QQQ, QQQI, TQQQ, SGOV, `^VIX`
and `^VXN` live from Yahoo and failed at the first request with
`YFRateLimitError`. The historical-prefix gate in
`scripts/refresh_qqq_v4_3_formal.py::_verify_historical_prefix` was never
reached because the refresh never produced a candidate package.

The repository already has the right primitives: a provider router, adapters, a
provider capability catalog, `FetchResult` provenance, frozen bundle manifests,
per-symbol provider identity, and fail-closed publication. What it lacks is a
verified, licensed second source per data class and an explicit rule for when a
fallback may supply data without changing the meaning of frozen history.

## Evidence standard

All provider facts below were read from the provider's own public pages on
2026-11-17. Items that could not be reached or verified are marked
**UNVERIFIED** and are not shortlisted. Local behaviour is marked **REPO** and
cites the checked-in file. No API keys, account identifiers or secrets are
recorded here.

Labels: **VERIFIED** = official page fetched; **UNVERIFIED** = blocked, 404,
JavaScript-only without accessible content, or no explicit terms found;
**REPO** = current repository behaviour.

## Comparison: US ETF/equity daily OHLCV

| Provider | Coverage / history | Free-tier limits | Auth | Adjusted prices / actions | Research-use terms | Batch | Python | Revision / reliability signal | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **Tiingo** [S10][S11] | US stocks/ETFs; 30+ years price history | 500 unique symbols/month, 50 requests/hour, 1,000/day, 1 GB/month | API token | `adjOpen/adjHigh/adjLow/adjClose`, plus `divCash`, `splitFactor`, raw prices | "Internal Use Only"; personal/internal, no redistribution | One symbol per request | Official client or plain HTTP; adapter exists [S27] | Adjusted history is restated on actions; commercial vendor with a free tier | **Best fit; already configured primary for the QQQ bundle** |
| **Twelve Data** [S12][S13][S14] | US/global equities, ETFs, indices; time series up to 5,000 bars per request | 8 API credits/minute, 800/day | API key | `adjust=all|splits|dividends|none`, default `splits` | Free tier is personal, non-commercial; redistribution prohibited | Multi-symbol supported | Official Python client | Free-tier depth per symbol not stated; verify before use | **Second independent vendor** |
| **Alpaca Market Data** [S20] | US equities/ETFs; history from 2016; IEX feed only | 200 historical API calls/minute | API key | Feed is IEX; no consolidated SIP; 15-minute historical restriction | Broker market-data terms; free Basic plan | Multi-symbol | Official SDK; adapter exists [S27] | Operational broker API; IEX volume is not consolidated | **Tail-only price fallback; volume caveat** |
| **EODHD** [S22] | EOD, dividends/splits; free history 1 year | 20 calls/day, 20/minute, 500 welcome calls | API key | Raw OHLC + `adjusted_close` only; no adjusted OHLC fields | Personal vs commercial plans; free-tier commercial terms not explicit | One symbol | HTTP/client | Low free quota; paid history 30+ years | Last-resort tail |
| **Marketstack** [S21] | EOD; free 1 year, paid up to 30 years | 100 requests/month | API key | `adj_open/adj_high/adj_low/adj_close/adj_volume` | "Non-Commercial Use" | One symbol | HTTP/client | Very low quota | Last-resort tail |
| **Alpha Vantage** [S15][S16][S17] | US/global daily | 25 requests/day | API key | `TIME_SERIES_DAILY_ADJUSTED` is labelled premium; free keys get raw `TIME_SERIES_DAILY` compact | Personal, non-commercial; broad commercial-use definition | One symbol | HTTP/client | Widely used but rate-limited | **Not viable free for adjusted OHLCV** |
| **Finnhub** [S18] | US/global | Free plan 60 API calls/minute, plus 30 calls/second plan cap | API token | `/stock/candle` is "Premium Access Required"; daily data split-adjusted only, not dividend-adjusted | Free plan "Personal Use" | One symbol | Official client | Free tier does not include candle history | **Not viable free for OHLCV** |
| **Polygon / Massive** [S19] | US; stocks since 2003, indices since 2023 | No free tier shown on the current pricing page | API key | Paid adjusted aggregates | "Individual use only" on paid plans | One symbol | Official client; adapter exists [S27] | Paid product; indices history too short for old index work | **Drop for free fallback** |
| **Stooq** [S23] | Purported US/indices CSV | No stated quota | None | Adjustment behaviour not verified | No terms found | Per symbol | `pandas.read_csv` | Site timed out from this environment; data provenance unknown | **UNVERIFIED; do not use** |
| **Financial Modeling Prep** [S25] | US/global | Pricing/terms blocked (HTTP 403) | API key | Unknown | Unknown | Unknown | Client | Cannot verify current free tier | **UNVERIFIED; do not use** |
| **Nasdaq Data Link** [S24] | Various datasets | Documentation pages returned 404 / JavaScript shell | API key | Unknown | Unknown | Unknown | Client | Cannot verify free VIX/equity access | **UNVERIFIED; do not use** |

## Comparison: volatility indices (`^VIX`, `^VXN`)

| Provider | Data | Free access | Adjustment | Terms / caveat | Verdict |
|---|---|---|---|---|---|
| **CBOE public history** [S7][S8][S9] | `VIX_History.csv`: `DATE,OPEN,HIGH,LOW,CLOSE` from 1990-01-02; `VXN_History.csv` same columns from 2009-09-14; also VVIX, VIX9D, OVX, GVZ, VXAPL, VXAZN, VXEEM | No key; direct CSV | Index levels, no corporate actions | Data "compiled for the convenience of site visitors", accuracy not guaranteed; no explicit redistribution licence on the page | **Primary volatility fallback** |
| **FRED** [S1][S2][S3][S4] | `VIXCLS` daily close from 1990-01-02; `VXNCLS` daily close from 2001-02-02; source CBOE | API key; numeric quota not published on the terms page (the Bank may impose limits) | Close only; **no OHLCV** | Personal/non-commercial; attribution required; no scraping/extraction; **must not be used to train software or ML/LLM systems** | **Close-only verification fallback, legal review required** |
| **Yahoo / yfinance** [S27] | Current source | Unofficial; rate-limited | Provider-adjusted | Research/personal fallback | Current primary, not a dependable fallback |

FRED's `VIXCLS` and `VXNCLS` are index closes, not OHLCV. They can support a
close-only signal calculation (the current VIX features use close only:
`src/research/vix_rotation_experiment.py::build_vix_features`), but they cannot
be turned into OHLCV by setting open=high=low=close or volume=0. That would
fabricate fields. Any use of FRED in model training also conflicts with the
FRED terms quoted above; that is a product/legal decision, not an adapter
detail.

## Comparison: broad indices (`^GSPC`, `^NDX`, `^DJI`)

| Provider | Coverage | Caveat | Verdict |
|---|---|---|---|
| Existing primary (Tiingo/Polygon contract) | Depends on entitlement | Must preserve exact index identity; never substitute SPY/QQQ for the index | Keep as first choice |
| CBOE CSVs [S7] | Volatility indices only | Not broad equity indices | Volatility only |
| FRED [S5][S6] | `SP500`: daily close, 10 years of daily history; `NASDAQCOM`: daily close, base 1971-02-05=100 | Close only; no OHLC; FRED terms/ML restriction | Verification or close-only fallback |
| Twelve Data [S14] | Indices advertised; exact symbol coverage not verified | Verify exact index symbol and history before use | Candidate, verify |
| Stooq [S23] | Purported index CSV | Unreachable; no terms | **UNVERIFIED** |

There is no verified free source in this survey that provides long-history,
adjusted, consolidated OHLCV for broad indices. Exact-identity substitution
(e.g. SPY for `^GSPC`) is forbidden by the existing adapter contract
(`src/data/adapters/yfinance_adapter.py::_get_yahoo_ticker`).

## Comparison: CN A-shares

No newly evaluated US/global free API improves on the CN providers already in
the repository. The existing catalog [S27] records the important semantic
differences:

| Provider | Role | Price mode | Corporate actions | Notes |
|---|---|---|---|---|
| Tushare | Credentialed managed CN source | raw + adjustment factor | Yes | Token permissions determine endpoint access |
| Baostock | Independent historical fallback | raw, unadjusted | No | Bounded socket behaviour |
| AKShare / Sina | Independent public Sina transport | qfq adjusted | No | Throttled; repeated requests can trigger IP blocking |
| AKShare / efinance (Eastmoney) | Public Eastmoney transports | qfq adjusted | No | Endpoint stability not guaranteed; not independent of each other |
| Tencent qfq history | Last-resort paginated history | qfq adjusted | No | Synthetic amount is not reported turnover |
| yfinance | Current multi-market fallback | provider adjusted | Yes | Rate-limited |

Recommendation: **do not add a new CN provider in the first fallback slice.**
First prove the existing CN chain is exercised, rate-limited and fail-closed.
Tushare remains the most governed CN source; the qfq transports must never be
mixed with raw Baostock rows in one series.

## Ranked shortlist

### US ETF/equity adjusted daily bars

1. **Tiingo** — already implemented and already configured as the QQQ bundle
   primary. Adjusted OHLC, raw audit fields, distributions and split factors,
   30+ years, 50/hour and 1,000/day free. Best contract fit.
2. **Twelve Data** — independent vendor, `adjust=all`, 800 credits/day. Free
   per-symbol depth is not stated; verify before relying on it for history.
3. **Alpaca (IEX)** — already implemented, 200 historical calls/minute, 2016+.
   Good for a recent tail only; IEX volume is not consolidated and must be
   labelled as such.
4. **EODHD / Marketstack** — tail-only last resorts. Both have adjusted fields,
   but 20/day or 100/month quotas and unclear/limited free terms.

Not viable for free adjusted OHLCV: Alpha Vantage (adjusted endpoint premium,
25/day), Finnhub (candles premium), Polygon/Massive (no free tier shown).
Unverified: Stooq, Financial Modeling Prep, Nasdaq Data Link.

### Volatility indices

1. **CBOE public CSV** — `VIX_History.csv` (1990+) and `VXN_History.csv`
   (2009+), OHLC, no key.
2. **FRED** — `VIXCLS` (1990+) and `VXNCLS` (2001+), close only, API key,
   non-commercial and no-ML-training restriction.
3. **Yahoo/yfinance** — current source, not a fallback.

### Broad indices

1. Existing entitled primary, with exact index identity.
2. CBOE for volatility indices, FRED close-only for `SP500`/`NASDAQCOM`.
3. Twelve Data indices only after symbol/history verification.

### CN

1. Tushare.
2. Baostock.
3. AKShare/Eastmoney and Sina/Tencent, in that order, with throttling.
4. yfinance.
5. Fail closed.

## Recommended fallback order for the QQQ formal refresh

Tradable ETFs (QQQ, QQQI, TQQQ, SGOV):

1. Tiingo (configured primary when `TIINGO_API_TOKEN` is present).
2. Twelve Data (`adjust=all`).
3. Alpaca IEX (tail-only; price fields; volume explicitly non-consolidated).
4. Fail closed. Yahoo remains the existing research fallback only where the
   bundle contract allows it; it is not a reliability layer.

Volatility references (`^VIX`, `^VXN`):

1. Yahoo (current primary).
2. CBOE CSV (`VIX_History.csv`, `VXN_History.csv`).
3. FRED close-only only if the signal contract explicitly permits close-only
   and the ML-training restriction is cleared for the intended use.
4. Fail closed.

Broad indices:

1. Existing entitled primary.
2. FRED close-only for verification, or Twelve Data after verification.
3. Fail closed. Never substitute a tracking ETF.

CN: keep the existing order recorded in `src/data/provider_catalog.py`; add no
new provider in the first slice.

## Two APIs worth applying for first

1. **Tiingo** — https://app.tiingo.com/register (redirect target of
   `https://www.tiingo.com/register`; the site returned 403 to a non-browser
   client, so verify in a browser). Value: the adapter, contract and primary
   configuration already exist; a token converts the existing configured
   primary into a usable one.
2. **Twelve Data** — https://twelvedata.com/register (verified HTTP 200).
   Value: an independent free vendor with explicit split/dividend adjustment,
   800 credits/day, and multi-symbol requests.

**No signup is required for the CBOE volatility CSVs**, so that is the cheapest
immediate redundancy to add for `^VIX`/`^VXN`. Alpaca
(https://app.alpaca.markets/signup) is a useful third option because its adapter
already exists, but its IEX-only volume means it cannot be treated as a
consolidated-SIP substitute.

## Minimal integration design

The design below is a proposal for a later, separately scoped implementation.
It does not change code in this PR.

### 1. Adapter and catalog identity

Each provider gets one `MarketDataAdapter` implementation that returns the
canonical `date, open, high, low, close, volume, amount, factor` columns, plus
`FetchResult(provider, symbol, market, start, end, df, provider_symbol)`.

Add catalog entries in `src/data/provider_catalog.py` for any new provider with
at least:

- `source_family`: the upstream source (e.g. `cboe_public`, `fred_api`,
  `twelvedata`, `alpaca_iex`).
- `independent_group`: the corroboration unit. Two transports over one upstream
  must not count as independent evidence.
- `markets`, `price_mode`, `volume_unit`, `amount_unit`, `corporate_actions`,
  `credential_env`, `usage_note`.
- A licence/usage classification (for example `internal_research_only`) so a
  manifest can refuse to label a free fallback as professionally ready.

Provider symbol mapping stays in the adapter (`provider_symbol(req)`), not in
the caller. `^VIX` maps to the CBOE VIX file or FRED `VIXCLS`, never to VIXY or
VXX. `^GSPC` never maps to SPY.

### 2. Retry and backoff before fallback

The current `MarketDataRouter.fetch_daily_bars`
(`src/data/router.py`) moves to the next provider on any exception. That is too
eager for rate limits and too permissive for data-identity failures.

Add typed failures:

- `ProviderRateLimitError` carrying `retry_after_seconds` and reset metadata.
- `ProviderUnavailableError` for timeouts, connection resets and 5xx.
- `ProviderContractError` for schema/identity/adjustment violations.

For a retryable failure, retry the **same** provider first:

- bounded attempts (for example 3);
- exponential backoff with jitter (for example 2 s, 8 s, 30 s, capped at 60 s);
- honour `Retry-After` when present;
- persist every attempt in `RouterAttempt` (error class, attempt number,
  retry-after, fallback reason).

Only after the retry budget is exhausted may the router move to the next
provider. A `ProviderContractError` must **not** trigger fallback; it must fail
closed, because substituting a provider would mask a data-identity defect.
`yfinance` should map `YFRateLimitError` to `ProviderRateLimitError` instead of
collapsing it into a generic `DataFetchError`.

### 3. Per-run provider consistency

Resolve one provider per `(market, symbol)` for the whole run. Record it in the
bundle/publication manifest, together with `source_family`,
`independent_group`, `provider_symbol`, `price_mode` and the request window.

Two allowed patterns:

- **Whole-series**: the fallback supplies the entire symbol series.
- **Append-only tail**: frozen history is preserved byte-for-byte and only
  sessions after the frozen cutoff come from the fallback, with
  `provider_by_segment` recording the split.

Row-level mixing (some dates from A, some from B inside the sealed window) is
forbidden. If a fallback is used for one symbol, that fact must be visible in
the manifest and in Operating Status; it must not silently look like the
primary provider.

### 4. Adjusted-price contract checks

Before a result enters the bundle:

- dates are unique, sorted and normalised to the market session;
- prices are positive and finite;
- `high >= max(open, close, low)` and `low <= min(open, close, high)` within the
  existing tick tolerance;
- `factor > 0`; when raw fields are present, `factor == adjusted_close /
  raw_close` within tolerance;
- `price_mode` is declared, and raw and adjusted rows are never mixed;
- `volume_unit` and feed are declared. For Alpaca, `source_feed=iex` and
  `volume_basis=iex`, which is not consolidated SIP volume;
- providers that expose only `adjusted_close` (EODHD) derive adjusted OHLC with
  one explicit uniform ratio and record `adjustment_method`; providers that
  expose adjusted OHLC (Tiingo, Twelve Data `adjust=all`) record their native
  method;
- distributions and split factors are retained when the contract claims
  professional readiness. A free fallback does not inherit that claim.

### 5. Historical-prefix gate: detecting a different adjusted history

The existing `_verify_historical_prefix` compares the recomputed v4.3 report's
decision fields, labels and weights. That is necessary but not sufficient: a
fallback provider can change adjusted prices without changing a decision, and
the current gate would pass.

Add a price-prefix guard **before** replay, using the patterns already present
in `src/data/provider_snapshot_comparison.py` and
`configs/data/provider_snapshot_policy_v1.yaml`:

1. The frozen strategy bundle manifest stores, per symbol, a
   `source_prefix_sha256` over canonical normalized rows through the frozen
   cutoff, plus `provider`, `provider_symbol`, `price_mode` and
   `adjustment_method`.
2. A candidate full-series fetch must reproduce the same prefix. The safest rule
   for sealed formal history is an exact digest match; any mismatch raises the
   refresh error before replay.
3. If exact reproduction is impossible, compare the overlap explicitly:
   at least 20 sessions, p99 adjusted-close return difference <= 0.001, maximum
   <= 0.01, p99 adjusted-open return difference <= 0.002, maximum <= 0.01, and
   annual/full-period compounded open drift <= 0.002 (the thresholds already in
   `configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml`).
4. Any breach is `quarantine`/`unexplained_provider_drift_blocking`, not a
   warning. Do not publish, do not restate history, and keep the previous
   manifest pointer.
5. Prefer the append-only path: if the frozen prefix already covers history,
   the fallback supplies only the missing tail. Then the prefix digest is
   unchanged by construction and only the new rows need validation.

This is the concrete answer to "how would a fallback's different adjusted
history be refused?": the candidate never reaches replay unless its historical
prefix is identical (or explicitly reconciled inside the frozen tolerance), and
a mismatch is a blocking classification rather than a silent provider swap.

### 6. Fail-closed publication

- No complete candidate means no publication; keep the last valid cutoff.
- Never forward-fill, zero-fill, interpolate, or synthesize OHLC from a
  close-only series.
- A free fallback never sets `professional_source_ready=true`. The QQQ contract
  already requires Tiingo for QQQ/QQQI/TQQQ; keep that gate.
- The selected-pool publication manifest records the provider per symbol, the
  independent group, the cutoff, hashes and fallback events. Missing provider
  identity is a publication refusal, consistent with
  `src/data/selected_pool_price_publication.py`.
- Preserve `research_only=true` and `trade_ready=false`.

### 7. Observability

Extend the existing `RouterAttempt` evidence with `error_class`,
`retry_count`, `retry_after_seconds`, `fallback_reason` and `usage_class`.
Expose provider health (open circuits, failures by source family) in the
existing Operating Status provider-health snapshot. Persist exact request
metadata where the adapter already supports it (the Tiingo and yfinance
adapters show the pattern). Do not persist secrets.

### 8. Dependencies and tests

- Prefer stdlib `urllib`/`csv`/`json` and pandas, matching the existing Tiingo
  and Alpaca adapters. No new runtime dependency is required for CBOE CSV,
  FRED or Twelve Data.
- Future tests should be fixture-based and offline: recorded CBOE/FRED/Twelve
  Data payloads, a rate-limit-then-fallback case, a retry-exhausted fail-closed
  case, a wrong-provider-symbol case, a changed adjusted-prefix case, and a
  close-only-into-OHLCV refusal.

## Legal and licensing caveats

- **Free is not open.** Tiingo, Twelve Data, Alpha Vantage and Marketstack
  restrict free data to personal/internal/non-commercial use and prohibit
  redistribution. A local research console is one thing; publishing derived
  series to Pages or sharing them with third parties is another. Keep provider
  data local unless the licence explicitly allows redistribution.
- **FRED is the sharpest restriction.** The terms prohibit using FRED content
  "in connection with the development or training of any software program or
  system or machine learning", including LLMs and deep learning, and prohibit
  scraping/extraction. FRED is acceptable for verification or a close-only
  research read only after a legal/product decision; it is not a drop-in model
  training input.
- **CBOE has no explicit redistribution grant** on the historical-data page.
  The page says the data is compiled for convenience and accuracy is not
  guaranteed. Treat it as an official reference source, retain attribution and
  do not redistribute it without permission.
- **Tiingo** requires a token, restricts the free tier to internal/personal use
  and prohibits redistribution. Its paid terms are separate.
- **Twelve Data** free tier is personal, non-commercial; commercial use needs a
  paid plan. Its terms define redistribution broadly.
- **Alpha Vantage** defines commercial use broadly (including use by a
  corporation or in a commercial activity that lets others access the data) and
  grants personal, non-commercial use only.
- **Alpaca** free market data is IEX-only, not consolidated SIP, and is subject
  to broker market-data terms. Do not describe IEX volume as consolidated.
- **Marketstack** free is non-commercial, 100 requests/month, 1 year.
- **EODHD** distinguishes personal, commercial/B2B and academic licences; the
  free-tier commercial position is not explicit on the pricing page.
- **CN transports** (Sina, Eastmoney, Tencent, AKShare, Baostock) are public
  endpoints or open-source clients; their upstream terms and stability are not
  guaranteed. The repository already treats them as research-only transports,
  not as licensed professional feeds.
- **SEC** allows scripted access at 10 requests/second with a declared
  User-Agent, but it is listing/reference data, not price data.

## What must not be assumed

- Do not assume FRED `VIXCLS`/`VXNCLS` are OHLCV. They are daily closes.
- Do not assume FRED `SP500` is long-history; the page states 10 years of daily
  history.
- Do not assume CBOE `VXN_History.csv` starts in 2001; the file observed starts
  2009-09-14, while FRED `VXNCLS` starts 2001-02-02.
- Do not assume Stooq is available, licensed or Yahoo-independent. It timed out
  from this environment and no terms were found.
- Do not assume Financial Modeling Prep or Nasdaq Data Link still offer a free
  VIX/equity tier. Their pricing/documentation pages were blocked or missing on
  2026-11-17.
- Do not assume a free vendor's adjusted history matches Yahoo, Tiingo or
  another vendor. Adjustment methodology, dividend timing and split rounding
  differ; the prefix gate exists to catch this.
- Do not assume a provider's volume is consolidated. IEX, adjusted volume and
  synthetic `adjusted_close * volume` are different quantities.
- Do not assume free tiers or their terms are stable. Re-verify before an
  implementation PR and record the terms URL/date in the adapter catalog.
- Do not assume a free fallback can satisfy a `professional_source_ready` gate.
  It cannot, absent an explicit contract change.

## Recommendation

Apply for **Tiingo** and **Twelve Data** first. Add the **CBOE VIX/VXN CSV**
immediately because it needs no account and directly covers the volatility
references that were part of the failed refresh. Keep Alpaca as a third,
tail-only price option because its adapter already exists, but label its IEX
volume and 2016 history boundary. Do not add Stooq, FMP, Nasdaq Data Link,
Alpha Vantage or Finnhub to the runtime until their free terms and candle
history are verified.

Implementation should be a separate, narrow PR series:

1. Documentation and provider catalog entries only (no behavior change).
2. A retry/backoff layer in the router with typed failures and evidence.
3. CBOE VIX/VXN adapter, because it is the smallest no-auth, high-value slice.
4. Tiingo token provisioning and an end-to-end QQQ refresh on the existing
   primary path.
5. Twelve Data adapter, then a prefix-gate negative test proving a changed
   adjusted history is refused.
6. Alpaca tail-only fallback, with the volume caveat encoded.

## Sources

Accessed 2026-11-17. Provider pages can change; re-verify before implementation.

- [S1] FRED legal / terms of use: https://fred.stlouisfed.org/legal/
- [S2] FRED API terms of use: https://fred.stlouisfed.org/docs/api/terms_of_use.html
- [S3] FRED `VIXCLS`: https://fred.stlouisfed.org/series/VIXCLS and https://fred.stlouisfed.org/data/VIXCLS.txt
- [S4] FRED `VXNCLS`: https://fred.stlouisfed.org/series/VXNCLS and https://fred.stlouisfed.org/data/VXNCLS.txt
- [S5] FRED `SP500`: https://fred.stlouisfed.org/series/SP500
- [S6] FRED `NASDAQCOM`: https://fred.stlouisfed.org/series/NASDAQCOM
- [S7] CBOE VIX historical data: https://www.cboe.com/tradable_products/vix/vix_historical_data/
- [S8] CBOE VIX CSV: https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
- [S9] CBOE VXN CSV: https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv
- [S10] Tiingo pricing: https://www.tiingo.com/pricing
- [S11] Tiingo EOD documentation: https://www.tiingo.com/documentation/end-of-day
- [S12] Twelve Data pricing: https://twelvedata.com/pricing
- [S13] Twelve Data terms: https://twelvedata.com/terms
- [S14] Twelve Data time series documentation: https://twelvedata.com/docs/market-data/time-series
- [S15] Alpha Vantage pricing: https://www.alphavantage.co/premium/
- [S16] Alpha Vantage documentation: https://www.alphavantage.co/documentation/
- [S17] Alpha Vantage terms of service: https://www.alphavantage.co/terms_of_service/
- [S18] Finnhub candles documentation: https://finnhub.io/docs/api/stock-candles; rate limits: https://finnhub.io/docs/api/rate-limit; pricing: https://finnhub.io/pricing
- [S19] Polygon/Massive pricing: https://massive.com/pricing; coverage: https://massive.com/
- [S20] Alpaca market data: https://docs.alpaca.markets/docs/about-market-data-api
- [S21] Marketstack pricing: https://marketstack.com/pricing; endpoint docs: https://docs.apilayer.com/marketstack/docs/api-endpoints-v1/
- [S22] EODHD pricing: https://eodhd.com/pricing; EOD docs: https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
- [S23] Stooq: https://stooq.com/ (unreachable from this environment)
- [S24] Nasdaq Data Link: https://data.nasdaq.com/ (documentation pages 404 / JavaScript shell)
- [S25] Financial Modeling Prep: https://site.financialmodelingprep.com/pricing (HTTP 403)
- [S26] SEC developer access: https://www.sec.gov/os/webmaster-faq#developers; ticker identities: https://www.sec.gov/files/company_tickers.json
- [S27] Repository evidence: `src/data/adapters/base.py`, `src/data/router.py`, `src/data/provider_catalog.py`, `src/data/strategy_data_bundle.py`, `src/data/provider_snapshot_comparison.py`, `src/research/etf_strategy_data.py`, `scripts/refresh_qqq_v4_3_formal.py`, `configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml`, `configs/data/provider_snapshot_policy_v1.yaml`, `src/data/selected_pool_price_publication.py`
- [S28] P2 scope boundary: `docs/architecture/p2_data_first_complete_dataset_2026-11-04.md` (line 73 excludes external provider fallback)
