# A-share open-source provider review — 2026-08-02

## Decision

The selected-pool data plane counts independent upstream sources, not Python packages.
A wrapper that reaches the same Eastmoney endpoint as another wrapper is not a second
independent source.

## Primary paths

### Periodic fundamentals

- **Facts:** Sina financial statements through AKShare
  (`stock_financial_report_sina`).
- **PIT timestamp and source document:** CNINFO periodic-report announcements through
  AKShare (`stock_zh_a_disclosure_report_cninfo`).
- A value is eligible for the canonical event store only when its fiscal period can be
  joined to a CNINFO announcement. A statement row without a disclosure timestamp
  remains partial and is not forward-filled.

This uses AKShare as a maintained transport, while preserving the distinct upstream
identities `sina_finance` and `cninfo`.

### Corporate actions

- Eastmoney structured dividend implementation data through
  `stock_fhps_detail_em`.
- CNINFO share-change and allotment interfaces through
  `stock_share_change_cninfo` and `stock_allotment_cninfo`.
- Explicit dates and ratios only. Price discontinuities are never converted into
  corporate actions.

## Validation-only paths

- **BaoStock:** independent quarterly financial/dividend comparison.
- **Mootdx/Tongdaxin:** optional XDXR and finance comparison. It is not installed as a
  required runtime dependency until a bounded transport/health contract is accepted.
- **Tushare Pro:** credentialed field/timing comparison only. `TUSHARE_TOKEN` is not a
  requirement for canonical population and Tushare observations may not feed training.
- **AKShare Eastmoney and efinance:** alternate transports over the same upstream;
  they count as one source family.

## Rejected shortcuts

- Counting AKShare and efinance as independent evidence when both use Eastmoney.
- Using report-period end as information availability.
- Treating a 1970-01-01 parsing artifact as an announcement date.
- Using adjusted-price gaps to infer dividends, splits or rights issues.
- Promoting validator values into the canonical event store when a primary value is
  absent.

## Operational requirements

- Provider attempts, source family, endpoint and raw-response hash are retained.
- A provider-wide block or rate limit opens a circuit for the current shard.
- Every CN130 symbol receives an explicit `ready`, `partial`, `provider_missing`,
  `identity_missing` or `conflict` state.
- Primary/validator disagreements are evidence; they are not resolved by silent source
  precedence.
- All outputs remain `research_only=true` and `trade_ready=false`.
