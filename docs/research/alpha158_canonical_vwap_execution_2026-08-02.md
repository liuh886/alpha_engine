# Alpha158 canonical VWAP execution

## Decision

The Alpha158 panel engine is already merged. The remaining field blocker is daily VWAP on the same adjusted-price basis as OHLC.

The current US and CN providers cannot be treated identically:

- **US87:** Yahoo amount is synthetic and no provider-reported daily VWAP/turnover exists in the canonical provider. Tiingo and Polygon remain validation-only. US Alpha158 therefore remains explicitly blocked.
- **CN130:** AKShare transports Sina equity data with reported share volume and CNY turnover. The same endpoint supports raw and qfq OHLC. This permits a canonical adjusted VWAP without using a validation source.

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

## US fail-closed output

```bash
uv run python scripts/data/build_canonical_vwap_provider.py \
  --market us \
  --cutoff 2026-07-31 \
  --output-root artifacts/data/canonical_vwap/us
```

This writes a machine-readable blocked component. It does not copy Tiingo/Polygon data into canonical training tables and does not use `close` as VWAP.

## Closure boundary

This implementation removes the CN engineering blocker and creates the actual panel workflow. Issue #325 may close only when the live CN130 artifact is reviewed and an approved canonical US VWAP source exists. Until then, `cn_selected_alpha158_v1` may become ready or partial while `us_selected_alpha158_v1` remains blocked.

All artifacts are research-only and `trade_ready=false`.
