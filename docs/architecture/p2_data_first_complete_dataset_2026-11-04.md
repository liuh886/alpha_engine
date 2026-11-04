# P2-D0 — Comprehensive research datasets before Colab

**Owner decision 2026-11-04: DATA FIRST.** This supersedes the earlier suggestion to start with a tiny Colab sample. Neither source data access nor Colab real execution may be called complete until a **comprehensive, hash-verified, rights-approved multi-domain package** has been physically built and placed in the private Drive research exchange. Status: **D0 market-history builder committed; full data package and Drive upload NOT performed; full multi-domain research data BLOCKED.**

## Acceptance definition

| Tier | Actual required contents | Verdict |
| --- | --- | --- |
| D0-A complete daily market history | All 87 US equity candidates, 130 CN equity candidates, every declared benchmark and auxiliary symbol, full retained history per eligible symbol, accompanying market factor series, factor diagnostics, source and pool/benchmark manifest bytes with SHA256 and rights labels | First packable dataset tier, but only after all local SHA checks and explicit private cloud copy approval |
| D0-B complete multi-domain dataset | D0-A plus original US/CN fundamental events and availability/revision fields, US/CN corporate actions and adjusted-price roles, original CN Qlib Alpha158 panel, source version and calendar, full reference ETF sources, lifecycle/identity maps, explicit per-symbol and per-time coverage; component family inventories must reference real, verified payload bytes | **Current BLOCKED**; no implied full coverage from summary readiness flags or Git manifests |
| D0-C verified private Drive copy | Versioned, immutable files and aggregate bundle index, local-vs-Drive exact SHA, Drive ACL review, no redistributions or private account data | NOT EXECUTED |
| E1 Colab execution | Verify exact packages and same code/version; execute existing study, compare results locally, record independent receipt | FORBIDDEN until D0-B/C accepted |

The proposed full dataset refers to the **frozen selected pools**, not all listed equities. Do not invent historical index membership or substitute missing symbols, and do not confuse an original source manifest with an actual dataset. No minute-level / intraday research is in scope.

## Current inspected source snapshot: main bed095eb (2026-11-04)

- Authority: data/research/model_data_bundle_v1/data-components.json and data/research/market_evidence/{us,cn}/catalog.json, governed-source-receipt.json; data cutoff 2026-11-03.
- US/CN daily price component statuses: **87/87 and 130/130 ready**, but common formal price windows start 2025-06-05 and 2026-04-16 respectively.
- Broader retained market evidence catalogs hold **all 87 US / 130 CN candidates** and corresponding benchmark/auxiliary files with catalog start 2021; each security's start varies (latest US candidate first observation 2025-06-05, CN 2026-04-16). Symbol-by-symbol SHA and source dates require real local verification before package acceptance.
- Fundamentals: **US 86/87** (missing SBGSY identity mapping); **CN 127/130** (missing 301309, 301666, 600276). Corporate-action summary coverage 87/87 and 130/130, but **the actual event/coverage payload bytes are not present beside the committed source manifests**.
- CN Qlib Alpha158 is **129/130 partial** (301666 not-yet-applicable); market-evidence factor series are NOT interchangeable with the canonical Alpha158 payload.
- Dedicated QQQ/QQQI/TQQQ reference bundle status 3/3, cutoff 2026-10-14, differs from the 2026-11-03 market-evidence reference series. Keep source identity and edition distinct.

### Recoverable source archives

- US events: liuh886/alpha-engine-data-archive, archives/us-events-36869443810.zip; SHA256 23d192b96e3bf4f38e1937c2c6896e112b7d8962f8a45bed06e56fe8fc5f686e.
- US reference bundle: same repo, archives/qqq-reference-research-38757752731.zip; SHA256 6da52ca8563264ec0fdaba50819bba828f9e1cd70e026bd85111297bb9bab9ad.
- CN events: exact source-receipt [GitHub Release](https://github.com/liuh886/alpha_engine/releases/tag/model-data-source-cn-events-36145411810), asset selected-pool-event-live-cn-36145411810.zip; provider-reported asset SHA256 546cebd6be53c4de4f514887b1ef0649d737ceb58c88395457c51dd7341dee32 (2,021,932 bytes).
- CN Alpha158: exact source-receipt [GitHub Release](https://github.com/liuh886/alpha_engine/releases/tag/model-data-source-cn-alpha158-36145403372), asset alpha158-canonical-vwap-cn-36145403372.zip; provider-reported asset SHA256 a65e7d54e81dfedec54ca8b6ebb4734f58897135c06ff63809ee494fe99fcd3c (124,842,414 bytes).
- These legacy releases match the source IDs in governed-source-receipt.json; **newer CN releases also exist and must not silently replace pinned sources. This PR has not downloaded/verified any binary source bytes.**

## Implemented data-first command

Run from exact local Alpha Engine Git checkout (prefer the branch of draft PR #1368):

    python -m src.research.comprehensive_dataset audit --repo-root . --market all --output /private/path/dataset-plan.json

The audit reads the existing pool registry, catalogues and all local symbol evidence files; verifies actual symbol hashes, exact 87+130 roster and references, canonical provider summaries and data products; returns market-history readiness and independent cross-domain missing source blockers. This does not upload or rewrite source data.

Once source-license review explicitly permits a private cloud mirror, for **each market separately**:

    python -m src.research.comprehensive_dataset pack-market-history --repo-root . --market us --approval /private/us-rights.json --output /private/us87-full-history.zip
    python -m src.research.comprehensive_dataset pack-market-history --repo-root . --market cn --approval /private/cn-rights.json --output /private/cn130-full-history.zip

Approval file structure: owner_approved_private_cloud_copy=true; rights_class=private_cloud_research_allowed; market must match, source_manifest_sha256 is exact hash from the verified plan. **Never auto-approve rights; an external provider's data source being public does not mean copying it into Drive is permitted.** Output must be outside the public Git repository. Both ZIP packages are still only D0-A, not the final complete D0-B.

The existing src/research/cloud_exchange.py handles archive contents and pinned files; no new authoritative database, backend, scheduler, frontend data endpoint or Colab work is added. Actual full-family assembly needs verified source bytes and a separate aggregate manifest before acceptance.

## Exact source recovery (local only; zero Colab calls)

The exact four legacy archive locators, commit/tag, version and expected SHA are already recorded in the canonical governed-source-receipt.json. The new recovery CLI uses them **without inventing a new source registry**.

    python -m src.research.source_archive_recovery list --repo-root .
    python -m src.research.source_archive_recovery fetch --repo-root . --source all --destination /private/outside-repo/source-archives
    python -m src.research.source_archive_recovery verify --repo-root . --source all --destination /private/outside-repo/source-archives

The tool records four independently pinned ZIPs (us_events.zip, cn_events.zip, cn_alpha158.zip, qqq_reference.zip), verifies original byte count and SHA256 from the authoritative receipt, and refuses overwrite or content substitution. Release GitHub metadata was checked against the CN artifact SHA; the archive bytes themselves have NOT been downloaded and checked in this conversation. Public HTTP URL access may fail for a protected GitHub asset: the local Agent should then download that **exact named archive** using authenticated GitHub CLI and run the same verification, not change the source revision. An original ZIP is not automatically safe or complete for a research study: inspect its actual member manifests and data rights before making any Drive copy.

These recovered archives are held **outside** the public repository. The D0-B aggregate bundle index and archive-member validation remain implementation work: they must bind both US/CN market-history ZIPs and the four verified source archives before Colab use. A successful local source download alone does NOT make the full research dataset accepted.

## Ordered implementation tasks

1. **D0-1 physical source recovery:** validate every candidate symbol and reference by exact SHA, retrieve/pin original US/CN fundamentals and corporate-action payload, original CN Alpha158 panel, existing reference source archive. Record source edition/UTC cutoff and archive SHA. Missing sources remain BLOCKED; do not silently replace with new provider data.
2. **D0-2 research quality and rights:** inspect per-security available dates and true trading sessions, corporate actions, release/available-at/revisions, benchmark eligibility, selected-pool membership and legal private transfer permission. Resolve or explicitly isolate fundamental and factor missing cases; retain honest negative evidence.
3. **D0-3 full-family bundle:** create complete US/CN market-history ZIPs; add separately pinned verified events, fundamentals, Alpha158 and reference payload; publish a consolidated private aggregate Manifest that lists every component, expected and observed coverage, code/source hashes, and rights. Do not label FULL_ACCEPTED until all mandatory components are real bytes.
4. **D0-4 Drive transfer:** place only approved full package into existing private AlphaEngine/03_Data/Research_Exchange_P2/input_packages, verify after remote copy and record Drive ACL, bundle SHA and count. Keep received work in incoming_unreviewed, never in public Pages.
5. **E1 after data acceptance:** execute Colab Notebook, compare against identical local research code and data, retain actual independent receipt. No Colab trial before D0-4.

## Review gates

- Every missing candidate/benchmark, hash mismatch, first-date discrepancy, original archived payload gap, unapproved data rights or historical PIT uncertainty is surfaced in structured audit as READY / PARTIAL / BLOCKED, never hidden.
- No source data in GitHub Pages, no account holdings/private signals, no new broad stock pool, no external provider fallback, no new streaming/broker or minute-level system.
- Tests cover complete roster, selected pool mismatch, tampering, missing data, forbidden paths and rights. No full-regression ritual before the first local dataset audit; targeted code tests should run in existing CI.
- **Exit decision:** D0-A built vs D0-B accepted must be reported separately. Full data bundle is a hard prerequisite for Colab experiments, not a blocker for the infrastructure PR remaining draft.
