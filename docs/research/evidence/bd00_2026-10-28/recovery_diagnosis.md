# BD-00 follow-up: lifecycle and event-store recovery

Diagnostic date: 2026-10-28. This corrects the interpretation of the original
inventory, without rewriting its observations or declaring experiment readiness.
`research_only=true`, `trade_ready=false`.

## EA: terminal listing, not an unexplained provider outage

The existing shared reader `src/data/listing_lifecycle.py::load_terminal_listings`
loads EA from `configs/data_quality/symbol_identity_and_lifecycle_v1.yaml`:
terminal trading date **2026-08-04**, suspension effective **2026-08-05**.
All 59 unobserved XNYS sessions in the original survey fall on or after that
suspension boundary. There are zero unexplained missing sessions between EA's
first observation and its terminal trading date in that survey.

This is supported by the [Nasdaq corporate-action notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-545)
and the issuer's [completion Form 8-K](https://www.sec.gov/Archives/edgar/data/712515/000114036126031157/ef20079099_8k.htm).
The original description of these sessions as an unresolved lifecycle gap was
too broad: the terminal listing is already governed. No new lifecycle registry,
provider substitution, candidate deletion or forward fill is needed.

This does **not** establish terminal proceeds, payment timing, historical
adjustment vintages or a correctly settled portfolio. Historical EA observations
remain available under the frozen pool; any new authoritative selection must
honour the existing suspension boundary. A mechanical last-known valuation or
monthly cash-slot rule is not evidence of an executable liquidation. Experiments
crossing the event still require their declared action and settlement evidence.

## Event bundle: exact bytes cannot be restored from manifests alone

Two existing verification paths expose different blockers without provider
requests. First check the sealed bundle's internal member closure:

```powershell
uv run --frozen python -c "from src.data.selected_pool_event_population import verify_selected_pool_event_bundle; verify_selected_pool_event_bundle('data/research/model_data_bundle_v1/sources/us_events')"
```

Result: **BLOCKED**, missing these four members, no extra members:

- `corporate_actions/events.jsonl`
- `corporate_actions/coverage.json`
- `fundamentals/events.jsonl`
- `fundamentals/coverage.json`

Then check against the current operating governance using the existing CLI:

```powershell
uv run --frozen python scripts/data/populate_selected_pool_events.py --market us --output-root data/research/model_data_bundle_v1/sources/us_events --cutoff 2026-09-30 --verify-only
```

Result: **BLOCKED**, `event population governance identity mismatch` before
member verification. The changed binding is the reference-instrument registry:
sealed SHA-256 `89caad51b98f08b2869cdae1bc226bb3d3686af9e0ea64cc64c42ae83792e3b2`,
current SHA-256 `0f98b3161edee2a9ed8f28a1a49a37fec961d1e0775c08d9f7ba6efea569cf40`.
The other four governance bindings match in this checkout. Both blockers matter;
restoring the four missing files alone cannot make current-governance verification
pass. Do not edit a sealed binding to bypass this distinction.

Their required hashes and sizes are sealed in `event_population_manifest.json`
and the component manifests. The same payloads are absent in the original
workspace, not merely this worktree. `source_reuse.fundamentals.transport` records
SEC transport metadata; it is not a cache location or a downloadable archive.

Recovery has two distinct paths:

1. **Restore the sealed bundle** from an existing trusted source artifact or
   backup into a separate staging directory. Keep its complete member closure
   and original manifests. The internal verifier checks identity, member bytes
   and component consistency. To verify the sealed governance as well, use an
   isolated historical checkout with all five exact bound governance files and
   run the existing CLI against staging. Do not replace active registries with
   old versions. A verified historical bundle still does not establish readiness
   under current governance. A matching name or count is insufficient. No trusted
   location for the missing bytes has been established.
2. **Build new evidence**, if restoration is unavailable, using the existing
   `scripts/data/populate_selected_pool_events.py` with a fresh output root and
   explicitly chosen evidence cutoff. US uses the existing SEC Company Facts
   and Yahoo action adapters. This contacts providers and creates a new vintage;
   it cannot reproduce or replace the sealed September hashes by assertion.
   Current downloads do not certify historical first-known availability. Retain
   SBGSY's missing-fundamental status unless source evidence resolves it.

Do not run a full refresh merely to read status. Do not synthesize event rows
from adjusted bars, copy fixture events into the source bundle, or overwrite the
old manifests to make verification pass. The restore/build decision, source
availability and the experiment's later cutoff remain open operational work.

## Independent work completed and remaining

- Completed: source inventory, shared lifecycle diagnosis and exact existing
  verifier/restore/build route mapping.
- Prepared: [BD-01 feature and transition boundary draft](../../bottom_detection_boundaries_draft.md),
  including synthetic expected cases. This is review material, not an approved
  experiment contract or implemented study.
- Blocked: byte-valid event closure, current-governance evidence and any dependent PIT/settlement evidence.
- Awaiting decisions: RFC A–D and clustering, baselines, OOS/shadow acceptance.
  These block the dependent evaluator, not unrelated product work.
