# Provider architecture v1 — 2026-08-01

Status: research only  
Trade ready: false  
Parent issues: #293, #295  
Consumer: PR #289 only after promotion gates pass

## Decision

Alpha Engine keeps its narrow `MarketDataAdapter -> canonical bars -> Qlib provider`
contract. It does not add OpenBB as a runtime dependency. OpenBB's useful design
principles are adopted locally: removable provider modules, standard output
semantics, explicit capabilities and source-family metadata.

A provider adapter is not treated as an independent source merely because it is
a different Python package. AKShare and EFinance currently access the Eastmoney
family and therefore count as one upstream group.

## Canonical daily-bar semantics

| Field | CN equity contract | US equity contract |
|---|---|---|
| date | exchange session date | exchange session date |
| open/high/low/close | internally coherent, one adjustment mode | internally coherent, one adjustment mode |
| volume | shares | shares |
| amount | reported CNY turnover when available | reported turnover when available; otherwise explicitly synthetic |
| factor | frozen-cutoff adjustment multiplier or explicit 1.0 for raw/index data | provider/source-specific and recorded |

Provider-native lot and amount-thousand units must be converted before validation
and hashing. A synthetic `close * volume` amount is not reported turnover and may
not be used as equivalent evidence.

## CN provider policy

1. Tushare Pro, when `TUSHARE_TOKEN` is configured. Daily raw bars are joined to
   explicit adjustment factors and anchored at the declared evidence cutoff.
2. AKShare Eastmoney transport.
3. BaoStock independent historical fallback.
4. EFinance alternate Eastmoney transport; it does not add independent evidence.
5. Yahoo research fallback. A CN symbol selected from Yahoo alone is quarantined
   and blocks provider promotion.

## US provider policy

The present phase retains Yahoo for broad US coverage and explicit symbol identity
checks such as TIGO versus TYGO. Phase 2 of #295 must add a credentialed professional
EOD provider and independent-source reconciliation before the data plane can be
considered robust beyond the frozen research retest.

## Promotion rules

A selected-pool build is promotion eligible only when:

- every exact candidate and benchmark is present and schema-valid;
- every source is bounded by the evidence cutoff;
- no source identity is substituted;
- provider, upstream family, adjustment mode, units and hashes are recorded;
- a full refresh was used, rather than copying legacy sources with unknown provider
  semantics;
- no CN candidate relies on Yahoo-only evidence;
- the generated Qlib provider manifest verifies successfully.

Completion of a network fetch is not evidence of data fitness. Failure remains
atomic and publishes diagnostics only.

## Phase 2

- add Tiingo or Massive/Polygon as a credentialed US EOD source;
- add exchange-calendar session coverage;
- add independent-provider consensus checks for returns, corporate-action dates,
  volume units and symbol identity;
- add provider health, rate-limit and circuit-breaker evidence;
- bind price snapshots to corporate-action and fundamental-event store hashes.
