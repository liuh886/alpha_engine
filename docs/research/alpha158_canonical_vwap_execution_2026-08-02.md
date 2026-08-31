# Alpha158 canonical VWAP execution

## Decision

The Alpha158 panel engine is already merged. The remaining field blocker is daily VWAP on the same adjusted-price basis as OHLC.

The US and CN providers cannot be treated identically:

- **US87:** Alpaca historical market-data daily bars are the approved canonical
  candidate. Listed candidates use SIP; the two explicitly identified OTC ADRs,
  `ABBNY` and `SBGSY`, use Alpaca's OTC feed. The
  bar contains provider-reported OHLC, volume and VWAP from the same aggregation;
  the request is fixed to the governed feed mapping, `timeframe=1Day` and
  `adjustment=all`. Missing
  credentials, pagination ambiguity, identity mismatch, incomplete pool coverage or a
  VWAP outside the same-record OHLC envelope blocks materialization. Yahoo amount
  remains synthetic, Tiingo remains validation-only, and Polygon daily VWAP remains
  rejected after the retained MSFT session-boundary mismatch evidence from run
  `32806097341`.
- **CN130:** AKShare transports Sina equity data with reported share volume and CNY turnover. The same endpoint supports raw and qfq OHLC. This permits a canonical adjusted VWAP without using a validation source.

## US source decision

Alpaca is selected because its listed-equity historical stock bars are derived from the CTA/UTP
Securities Information Processor feeds covering all US exchanges. Alpaca documents the
trade-condition rules used to update OHLC, volume and VWAP, including the rule that the
VWAP numerator and denominator use trades eligible for both price-range and volume
updates. Historical SIP data older than 15 minutes is available with API credentials,
which is compatible with this end-of-day research contract.

Primary references:

- Alpaca historical stock-data feeds and SIP coverage:
  <https://docs.alpaca.markets/docs/historical-stock-data-1>
- Alpaca daily-bar aggregation and VWAP trade-condition rules:
  <https://docs.alpaca.markets/docs/market-data-faq>
- Alpaca historical bars request, adjustment and feed parameters:
  <https://docs.alpaca.markets/reference/stockbarsingle-1>
- ABB issuer listing record for the `ABBNY` OTC ADR:
  <https://global.abb/group/en/investors/investor-and-shareholder-resources/share-listing>
- Citi depositary-receipt record for the `SBGSY` OTC ADR:
  <https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=80687P106&pageId=15&subpageid=106&typeDisplay=T>

This decision approves only the frozen historical daily-bar request and explicit
SIP/OTC symbol mapping above. It does
not approve IEX, snapshots, latest bars, overnight feeds, Polygon substitution, mixed
provider rows, or browser-side reconstruction. The first source-bound US87 live run must
still pass before `us_selected_alpha158_v1` may become ready.

## CN derivation

For each symbol and date:

```text
raw_vwap = reported_turnover_CNY / reported_volume_shares
qfq_ratio = qfq_close / raw_close
adjusted_vwap = raw_vwap * qfq_ratio
```

The build is accepted only when:

- raw and qfq calendars match exactly;
- reported raw and qfq share volumes match exactly;
- turnover and volume are positive and explicitly reported;
- adjustment ratios are finite and positive;
- adjusted VWAP remains inside the adjusted daily low/high envelope;
- all 130 selected symbols pass;
- source CSVs, raw/qfq caches, provider manifest and source-role manifest are retained.

The provider declares:

- `role=canonical`;
- `canonical_training_eligible=true`;
- `validation_only=false`;
- `vwap=reported_turnover_divided_by_reported_volume`;
- source provider `akshare_sina`.

## Execution

```bash
uv run python scripts/data/build_canonical_vwap_provider.py \
  --market cn \
  --start 2021-01-01 \
  --cutoff 2026-07-31 \
  --output-root artifacts/data/canonical_vwap/cn
```

The command:

1. retains raw and qfq source responses separately;
2. writes canonical CSVs containing adjusted OHLC/VWAP and reported volume;
3. builds a Qlib provider with `open/high/low/close/vwap/volume`;
4. runs the existing exact 158-factor panel builder;
5. writes factor/symbol quality evidence;
6. registers price and factor-panel components in `model_data_bundle_v1`;
7. exports the same readiness indexes for the frontend.

## US execution

```bash
uv run python scripts/data/build_canonical_vwap_provider.py \
  --market us \
  --cutoff 2026-07-31 \
  --output-root artifacts/data/canonical_vwap/us
```

If credentials or any exact-pool source row are unavailable, the command writes the
machine-readable VWAP audit and stops before constructing a canonical component. It
does not copy Tiingo/Polygon data into canonical training tables and does not use
`close` as VWAP.

The live path additionally requires repository secrets `APCA_API_KEY_ID` and
`APCA_API_SECRET_KEY`. Credentials are sent only as provider headers and are never
written to manifests, errors or artifacts. Without both secrets the build fails closed
and retains its blocked status.

## Closure boundary

The CN profile is ready on reviewed main-branch evidence. The US source decision is now
made, but Issue #325 may close only after an exact US87 live Alpaca artifact passes
the existing provider, panel, model-data and frontend readiness gates. Until that run is
reviewed, `us_selected_alpha158_v1` remains blocked.

All artifacts are research-only and `trade_ready=false`.
