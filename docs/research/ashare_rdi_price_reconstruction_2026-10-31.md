# RDI price-only versioned repair and renewal — 2026-10-31

This implements Step 1 from #1324 after #1337 exposed an incomplete old price
chain. It explicitly versions the historical repair rather than changing the
old append-only contract in place. The old Git blob, preflight failure receipt,
2026-10-24 descriptive receipts and Status briefing binding remain intact.

## Source and frozen scope

A fresh request through the existing `AkShareAdapter` / `stock_zh_index_daily`
returned Sina `sh000300` index history. The archived response is an independent
2026-10-31 retrieval, **not** the unavailable Actions artifact's source CSV.
The [source manifest](../../data/research/ashare_rdi/price_sources/sina_2026-10-31/manifest.json)
binds its compressed raw response, decoded adapter output, API/library and
adapter versions, retrieval time and unadjusted index-point basis. The adapter
has a dedicated index branch; generic equity-provider `qfq` / Eastmoney labels
must not substitute for its actual Sina index endpoint.

The compressed response is retained once (about 73 KB). Replays decode it
without network calls using the installed vendor decoder and existing index
normalizer, verify the captured CSV digest, then reconstruct a disposable
OHLC-only CSV. No second provider store, full-history consumer copy, model,
evaluator, registry, schedule or navigation is added.

The [repair contract](../../configs/research_experiments/ashare_rdi_csi300_price_repair_2026-10-31.json)
was committed before reconstruction / baseline recomputation. It permits only:

| Change | Old | New |
| --- | --- | --- |
| 2026-06-22 high | 5056.0595703125 | 5061.511 |
| 2026-06-22 close | 5048.81103515625 | 5059.658 |
| Missing trading session | 2026-06-23 absent | Insert source OHLC for that session |
| Forward renewal | After 2026-06-25 | Append 85 completed sessions through 2026-10-30 |

Every other retained OHLC **string** is copied exactly. The new five-column
price-only artifact excludes volume/amount/factor: old/provider volume units
are not admitted for RDI features. Original source bytes are never overwritten.
Unexpected historical gaps, OHLC differences, unnecessary repair declarations,
changed thresholds, hash mismatches and future cutoffs are rejected.

The new source has 5,238 distinct XSHG sessions from 2005-04-08 through
2026-10-30 with no gaps or non-session bars. Its 2021-start OHLC matches the
existing governed projection exactly. The reconstructed artifact also passes
that projection's full overlap audit, while preserving immaterial legacy
rounding elsewhere within the predeclared 0.01-index-point audit resolution.
This agreement uses the same source family, not an independent second provider.
Neither raw response archival nor calendar completeness proves historical
first availability, absence of revisions, historical PIT event coverage or
predictive usefulness.

## Offline replay and recomputation

Use a full checkout with the retained Git source blob available:

```powershell
uv run --frozen --extra dev python -m src.research.ashare_rdi.phase2_audit `
  --price-reconstruction-contract configs/research_experiments/ashare_rdi_csi300_price_repair_2026-10-31.json `
  --as-of 2026-10-30 `
  --write-reconstructed-prices artifacts/rdi/csi300_price_repair_2026-10-31.csv `
  --output artifacts/rdi/csi300_price_recomputation_2026-10-31.json
uv run --frozen --extra dev pytest tests/test_ashare_rdi_contracts.py tests/test_ashare_rdi_phase2.py -q
```

CSV output is optional and restricted to `artifacts/`; an existing different
artifact is not overwritten. The [dated recomputation receipt](../evidence/ashare_rdi_phase2/csi300_price_recomputation_2026-10-31.json)
contains the exact output hash, field-level repair ledger, source/contract/code
identities, full-history descriptive baseline, retrospective July–October
comparison and latest price-only B-state. The frozen definitions remain:
60-session closing-peak drawdown, drawdown threshold -10%, severe close-to-close
loss threshold -5%, and 7/14/28 distinct subsequent XSHG-session labels.
Window filtering applies to observation t, retaining its full earlier warmup.
Labels never end after the actual cutoff; overlapping observations are not
independent samples.

| Horizon | Latest mature start t | Latest label end | Immature tail count |
| --- | --- | --- | --- |
| 7 sessions | 2026-10-21 | 2026-10-30 | 7 |
| 14 sessions | 2026-10-12 | 2026-10-30 | 14 |
| 28 sessions | 2026-09-14 | 2026-10-30 | 28 |

B-state can be observed at October 30 while later-starting outcomes are still
`insufficient_future_bars`. The recorded trailing drawdown is an observed price
state, not a downside forecast, probability, alert or RDI score. July–October
is retrospective hypothesis-motivating evidence; no prospective clock starts
with this run. The baseline's original generic limitation text remains intact;
the enclosing receipt separately documents the additional source/calendar
checks, without claiming independent-provider certification.

## Next-cycle procedure and remaining gates

For each explicitly requested renewal, reuse the existing index adapter,
archive the exact original response and normalized-output identity, and freeze
a new dated source/repair contract before recomputation. Check all overlap and
exchange sessions; preserve failed source attempts and earlier receipts. Changes
to history require a separately reviewed versioned repair, never wider tolerance
or an in-place replacement. Invoke this under the existing manual operating
rhythm; no new scheduler is needed. Source acquisition is not run by Status,
readiness reads or this offline replay command.

This is **price-only Step 1 evidence**, subject to PR review and merge. The
historical PIT event table is still 0/10 qualified. First-family selection,
narrow scope freeze, prospective specification and independent evaluation
remain separate tasks. Status continues to show its older reviewed evidence
until a separately scoped rebinding with tests; do not infer UI freshness from
this price receipt. No composite score, sector ETF admission, strategy overlay
or live signal is authorized. `research_only=true`, `trade_ready=false`.
