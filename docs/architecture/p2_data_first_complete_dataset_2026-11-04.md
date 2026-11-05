# P2-D0 — Comprehensive research datasets before Colab

**Owner decision 2026-11-04: DATA FIRST**, reaffirmed by the 2026-11-05 local execution request: no Colab, new strategy or frontend work. Neither source data access nor Colab real execution may be called complete until a **comprehensive, hash-verified, rights-approved multi-domain package** has been physically built and placed in the private Drive research exchange. **2026-11-05 execution: a real data-only local multi-domain bundle is built and independently readable (198 files, 452,754,802 bytes); status PARTIAL. All four exact original archives are recovered. Drive upload, per-source cloud rights and remote ACL acceptance remain incomplete.** The dated evidence and retained gaps are recorded below; infrastructure/CI success does not mean FULL_DATASET_ACCEPTED.

## Acceptance definition

| Tier | Actual required contents | Verdict |
| --- | --- | --- |
| D0-A complete daily market history | All 87 US equity candidates, 130 CN equity candidates, every declared benchmark and auxiliary symbol, full retained history per eligible symbol, accompanying market factor series, factor diagnostics, source and pool/benchmark manifest bytes with SHA256 and rights labels | First packable dataset tier, but only after all local SHA checks and explicit private cloud copy approval |
| D0-B complete multi-domain dataset | D0-A plus original US/CN fundamental events and availability/revision fields, US/CN corporate actions and adjusted-price roles, original CN Qlib Alpha158 panel, source version and calendar, full reference ETF sources, lifecycle/identity maps, explicit per-symbol and per-time coverage; component family inventories must reference real, verified payload bytes | **PARTIAL** after 2026-11-05 physical recovery and independent local validation; missingness/semantics remain qualified, full acceptance remains blocked |
| D0-C verified private Drive copy | Versioned, immutable files and aggregate bundle index, local-vs-Drive exact SHA, Drive ACL review, no redistributions or private account data | NOT EXECUTED |
| E1 Colab execution | Verify exact packages and same code/version; execute existing study, compare results locally, record independent receipt | FORBIDDEN until D0-B/C accepted |

The proposed full dataset refers to the **frozen selected pools**, not all listed equities. Do not invent historical index membership or substitute missing symbols, and do not confuse an original source manifest with an actual dataset. No minute-level / intraday research is in scope.

## Historical pre-execution source snapshot: main bed095eb (2026-11-04)

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
- These legacy releases match the source IDs in governed-source-receipt.json; **newer CN releases also exist and must not silently replace pinned sources. At this pre-execution checkpoint no binary source bytes had been downloaded/verified; the 2026-11-05 checkpoint below records the actual recovery.**

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

The tool records four independently pinned ZIPs (us_events.zip, cn_events.zip, cn_alpha158.zip, qqq_reference.zip), verifies original byte count and SHA256 from the authoritative receipt, and refuses overwrite or content substitution. All four archive bytes were physically recovered and verified in the 2026-11-05 execution below. Public HTTP URL access can fail for a protected GitHub asset: use the explicit authenticated `--github-cli` path for the **exact named archive**, not another source revision. An original ZIP is not automatically complete or licensed for cloud copying: inspect its actual member manifests, missingness and rights first.

These recovered archives are held **outside** the public repository. The D0-B aggregate bundle index and archive-member validation are implemented and executed in the 2026-11-05 checkpoint. They bind both US/CN market-history ZIPs, four domain archives and the additional exact provider-source editions. A successful local source download alone does NOT make the full research dataset accepted.

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

## 2026-11-05 actual local execution checkpoint

Issue #1370 / draft PR #1368. Dataset code is frozen at
`3f0f54f8730d5af189fb24da98735a53f31c6af0`; subsequent acceptance documentation
does not move this dataset revision. No Colab, frontend or strategy execution.

The private `us87-cn130-20261103-local-v4/` bundle contains two immutable
data-only market-history ZIPs, four original domain-source ZIPs, two exact
provider-source ZIPs, Parquet prices and original provider columns,
fundamentals and corporate actions, 130 Alpha158 symbol panels, three reference
asset Parquets, separately acquired CN supplements, original supplemental source
caches, frozen configuration/dependency bytes, per-security coverage, gaps and
member/file hashes. Original ZIPs are hard-linked locally where supported, not
recompressed into another monolithic archive. This is 198 files / 452,754,802 bytes.

Bundle Manifest SHA256:
`ec753ad3af8a418e18e06ec39e0ee67f710d8bc3836a0ab00fa17f4c18ac2d61`.
Public-safe metadata: [package manifest](../evidence/p2_d0_2026-11-05/package-manifest.json),
[229-security inventory](../evidence/p2_d0_2026-11-05/symbol-coverage.csv),
[offline acceptance](../evidence/p2_d0_2026-11-05/offline-acceptance.json), and
[rights/Drive disposition](../evidence/p2_d0_2026-11-05/rights-and-drive-status.json).
Raw market/event/factor data is outside public Git.

| Domain | Physically observed coverage | Remaining qualification |
| --- | --- | --- |
| US daily prices | 87/87 selected; 116,433 candidate rows; overall 2021-01-04–2026-11-03; 5 references including CGDV, QQQ, QQQI, SGOV, TQQQ | Individual starts differ; EA ends at its governed terminal date. No interior calendar holes, but many source-edition prefixes are unreviewed |
| CN daily prices | 130/130 selected; 174,583 candidate rows; overall 2021-01-04–2026-11-03; 000300 plus 6 auxiliaries including 515180 | 11 candidate securities have interior missing exchange sessions; suspension versus source gaps is not certified |
| US fundamentals | Original 71,433 events / 86 names, cutoff 2026-09-30 | SBGSY is a reviewed no-SEC-Companyfacts identity exception, not a CIK to invent |
| CN fundamentals | Original 17,202 events / 127 names, cutoff 2026-09-04; independent supplements add 96 (301309), 18 (301666), 138 (600276) | 130 names have some payload after explicitly combining editions; this is not all-field/all-period/PIT certification or a canonical registry promotion |
| Corporate actions | Original US 3,579 events / 65 names + 22 no-event statuses; CN 2,792 events / 128 names + 2 no-event statuses | Ready coverage includes explicit no-event observations, not proof of every historical action or pristine announcement vintages |
| CN Alpha158 | 130 actual symbol files, 158 factors; original all-factor readiness 129/130 at 2026-09-04 | 301666 has 95 source sessions: 129 factor-quality rows ready, 29 blocked for insufficient post-warmup observations. Preserve pre-listing/undefined NaNs |
| QQQ source reference | Exact QQQ/QQQI/TQQQ source through 2026-10-14 | Yahoo-only, professional validation absent; corporate-action CSVs contain headers only; edition differs from market history |

The latest per-symbol market JSONs are genuine OHLCV/factor payloads. Their
referenced original CSVs are not the older/absent `data/csv_clean` files in this
checkout. Actual recovery from exact workflow run `41764999985` now supplies all
92 US and 137 CN source CSVs, each matching the market projection's existing
source CSV SHA. Artifact `13292915865` is 8,084,323 bytes / SHA256
`0f4e7bd8fde35f4ab90993bde914c31d4c2b0a4e554dd4003e2ec612680cd7d4`;
artifact `13292730698` is 11,205,068 bytes / SHA256
`0ce3ae6e76bf29e68f4877160e504e2ca0f3fa2a19fc983c701e00a4503ee794`.
No arbitrary newer provider edition replaces them. Extra Parquet components
preserve every original CSV column and null. All 229 current CSVs have `factor`
columns, but **every value is 1**: column presence is not raw-to-adjusted ratio
certification. No current CSV has VWAP; CN amount has 93 null observations.
The recovered CN Alpha158 archive separately retains its own raw,
qfq, volume, amount and adjustment-factor inputs through 2026-09-04. The factor
equals qfq-close/raw-close over 175,047 matched rows (maximum absolute error
`1.1102230246251565e-16`). These editions are not silently combined.
Tencent market-history volume remains
`provider_reported`; it is not relabelled as shares. QQQ overlapping close ratios
between editions range from 1.0 to about 1.002143, so no unconditional price splice
or common adjustment identity is claimed. US corporate-action announcement
dates all equal ex-dates, and US/CN pay dates are absent in these original event
sources; no announcement vintage or payment-date reconstruction is invented.

The known CN fundamental acquisition failure was reproduced: AKShare throws its
known empty-category KeyError for a new listing's nonexistent annual report,
preventing subsequent half-year/quarter reports. The existing narrow CNINFO
empty-result classifier is reused; unrelated schema/transport errors still fail.
The frozen original source ZIPs and active source registries remain unchanged.
301309 is 万得凯; 301666 is 大普微, listed 2026-04-16. Older descriptions naming
万达轴承/爱迪特 for those codes are incorrect; the exact symbol rosters are unchanged.
Primary listing evidence: [SZSE 301666 notice](https://investor.szse.cn/disclosure/notice/company/t20260415_619965.html),
[SZSE-hosted 301309 issuer notice](https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-03-16/6eee0870-b863-4133-b3ec-437be6898f58.PDF).

### Executable recovery, local build and independent offline acceptance

```powershell
uv run --frozen python -m src.research.comprehensive_dataset audit --repo-root . --market all --output <PRIVATE_ROOT>/reports/dataset-plan.json
uv run --frozen python -m src.research.source_archive_recovery fetch --repo-root . --source all --destination <PRIVATE_ROOT>/archives --github-cli
uv run --frozen python -m src.research.source_archive_recovery verify --repo-root . --source all --destination <PRIVATE_ROOT>/archives
uv run --frozen python -m src.research.source_archive_recovery fetch-market --repo-root . --destination <PRIVATE_ROOT>/archives --run-id 41764999985 --report <PRIVATE_ROOT>/reports/market-source-recovery.json
# New acquisition edition only; refuses to overwrite existing receipts.
uv run --frozen python -m src.research.comprehensive_bundle repair-cn-gaps --repo-root . --destination <PRIVATE_ROOT>/supplements
uv run --frozen python -m src.research.comprehensive_bundle build-local --repo-root . --archive-root <PRIVATE_ROOT>/archives --supplement-root <PRIVATE_ROOT>/supplements --market-source-report <PRIVATE_ROOT>/reports/market-source-recovery.json --output-dir <PRIVATE_ROOT>/input_packages/<NEW_IMMUTABLE_VERSION>
uv run --frozen python -m src.research.comprehensive_bundle verify --bundle <PRIVATE_BUNDLE>
# Requires a separate private checkout at the exact bundle code SHA.
uv run --frozen python scripts/verify_p2_dataset_offline.py --bundle <PRIVATE_BUNDLE> --checkout <FROZEN_PRIVATE_CHECKOUT> --report <PRIVATE_ROOT>/reports/offline.json
```

`pack-market-history --local-only` creates a distinct, explicit local format.
It does not set a cloud approval flag and is rejected by the approved
`cloud_exchange` verifier. The legacy approved market pack fails closed if its
source JSON still mixes model events. D0 local packages strip model-event and
weight fields by an explicit data whitelist, pin the original projection/catalog
SHA and preserve unchanged OHLCV/factor values. Earlier local v1/v2 numeric
parity passed but privacy did not; those intermediate versions are quarantined,
never delivered or uploaded. Data-only v3 was verified before the extra provider archives were recovered; v4 is the final local candidate.

Actual checks: 66 targeted tests passed; Ruff passed; Mypy passed on four research
modules. The independent fresh checkout pins code and `uv.lock`, denies socket
connects, checks all four original archive sizes/SHA/ZIP CRC/member/child-manifest
bindings, compares every event and Parquet value, compares all 130 Alpha158 panels
including NaNs, and reconstructs the 229-security audit. Privacy scan: 1,117 text
payloads, zero credential/account/model-weight signatures. Separate US and CN
market-history rebuilds produce identical ZIP SHA256. These checks do not certify
PIT, source license, missing sessions or product release.

### Cloud disposition and concrete next steps

The installed Drive for Desktop transport and existing logical target
`AlphaEngine/03_Data/Research_Exchange_P2/input_packages` were found. No data was
copied: owner stated existing permission but no per-provider license proof was
identified; Tencent is a material additional source. Remote browser ACL
inspection was stopped by the UI tool because it could not reliably identify
the browser URL. Drive ACL / remote hashes are NOT_TESTED, and
`owner_approved_private_cloud_copy=false` remains explicit.

Next: bind the actual per-provider private-copy license/owner approval to this
exact component/source version (SEC public reuse is separately documented),
obtain a verifiable private Drive session, transfer approved files and compare
remote bytes/count/SHA/ACL; separately certify true raw-to-adjusted ratios in the
current provider edition, resolve the CN session holes and select a governed SBGSY fundamental
source. A later Alpha158 edition may address the short-history factors, but must
not replace the pinned legacy archive under the same identity. Final verdict is
**PARTIAL**, not FULL_DATASET_ACCEPTED; no Colab experiment is started.
