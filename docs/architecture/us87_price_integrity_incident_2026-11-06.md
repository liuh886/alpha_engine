# US87 E2 price-integrity incident and clean rerun

**2026-11-06 · PR #1377 (stacked on #1376) · decision: execution PASS / model-selection evidence BLOCKED**

The owner completed 261/261 Google Colab tasks with 0 runtime failures and a private immutable final checkpoint named `e2-us87-checkpoint-20261106T130711006241Z.zip`. That establishes successful execution/checkpointing, **not** economically valid returns or a promoted model.

## Current data-repair acceptance — 2026-11-06

**US87 price repair ACCEPTED LOCALLY; next Colab configuration PREPARED, training OFF.**
The original contaminated v5 and all14CheckpointZIPs are unchanged, including the
completed261-task artifact. The new full-price edition is independent and the
old engineering results remain inadmissible for model selection. No retraining,
Colab access or PR merge was performed. Detailed acceptance follows below.

## Reproducible source finding

Frozen original local v5 US archive SHA256:
`93b2d42cebf3ebfac7b80298f6822fdc4305f7550b73ac1b2bb8d272d3fb3de8`.

Independent read-only inspection of the unmodified archive over `2025-06-05` through `2026-08-04` found ten close-price jumps matching large split-scale factors:

| Symbol | Source date | Close ratio vs previous session | Candidate factor |
| --- | --- | ---: | ---: |
| KLAC | 2026-05-07 | 0.09708 | 10 |
| KLAC | 2026-05-08 | 10.60082 | 10 |
| KLAC | 2026-05-11 | 0.09872 | 10 |
| KLAC | 2026-05-21 | 10.06947 | 10 |
| KLAC | 2026-05-22 | 0.10251 | 10 |
| KLAC | 2026-05-26 | 10.65141 | 10 |
| KLAC | 2026-05-27 | 0.09731 | 10 |
| KLAC | 2026-05-28 | 9.84897 | 10 |
| KLAC | 2026-06-01 | 0.10095 | 10 |
| CRWD | 2026-06-18 | 0.25070 | 4 |

This is evidence of **source adjustment-scale discontinuity**, not proof of an exact exchange effective date or of an authorized split adjustment. The presence of reversal oscillations for KLAC makes the contaminated daily-return inference especially strong. Other symbols and events may still need deeper corporate-action review; this conservative screen is *not* comprehensive data certification.

### Upstream origin confirmed from retained source archive

The owner's private v5 `sources/market_source_us_41764999985.zip` contains `data/csv_source/KLAC.csv` and `CRWD.csv` with the same discontinuities. The frozen `selected_pool_price_refresh_manifest.json` identifies `yfinance` as the US provider and `fetched_incremental_update` as the latest action for both symbols. The problem therefore **precedes ZIP construction**; simply rebuilding the v5 wrapper from unchanged CSV bytes would preserve it.

The existing canonical price refresh now invokes the same semantic screen on prior US CSVs and newly returned price frames. An anomalous retained CSV is classified invalid even when its cutoff is current; the refresh requests a **full-history replacement**, not an incremental tail merge. A still-invalid returned series produces a blocked/quarantined symbol, not a fabricated repaired output. Successful source regeneration remains conditional on the actual provider returning consistently adjusted daily prices.

The recorded high returns in `fold_c` (several model configurations >1,000% excess within a short validation window) should not be used in model selection. Three seeds frequently produced identical return/drawdown/Rank-IC metrics, so repetitions are not independent confirmation.

### Authoritative event-date cross-check

- **KLA (KLAC)** announced a 10-for-1 forward split on 2026-05-07, but its **first split-adjusted trading date was 2026-06-12** according to its SEC exhibit. The mixed 10x price scales seen 2026-05-07 through 2026-06-01 are **before** the authorized effective trading date. [KLA 8-K exhibit](https://www.sec.gov/Archives/edgar/data/319201/000119312526212093/d116682dex991.htm).
- **CrowdStrike (CRWD)** announced a 4-for-1 stock split on 2026-06-03; the first split-adjusted trading date was **2026-07-02**, according to its official SEC 8-K. The 2026-06-18 quarter-scale break occurs before that date. [CrowdStrike SEC 8-K](https://www.sec.gov/Archives/edgar/data/1535527/000153552726000022/crwd-20260603.htm).

These official records establish split factors and expected effective trading dates. They do **not** certify which individual vendor OHLCV rows were raw vs adjusted or justify bulk price rewriting without upstream source and component-manifest reconciliation.

## Run the audit locally (no Colab or provider fetch)

From a checkout of the **PR code** with frozen dependencies installed:

```bash
uv run python -m src.research.us87_price_integrity \
  --archive "/path/to/immutable-v5/us_market_history.zip" \
  --start-date 2025-06-05 --end-date 2026-08-04 \
  --report-file "/path/to/new/audit-us87-v5.json"
```

Exit status `10` and `BLOCKED_PRICE_SCALE_INTEGRITY` are **expected** for the known bad v5. Exit 0 and `READY_PRICE_SCALE_SCREEN` mean *only that this specific scale check passed*, not full data certification. The report is created exclusively; never overwrite earlier evidence.

The same CLI accepts `--data-root /path/to/hash-verified-staged-root` instead of `--archive`. Campaign compilation with `data_root` calls the same per-bar screen automatically, before fitting or issuing any model ranking. Training now fails closed with `BLOCKED_PRICE_SCALE_INTEGRITY` on the known v5.

## Owner/local Agent — first repair command (local only)

The already-merged canonical US price-refresh CLI supports `--full-refresh`. With the **original source CSVs unpacked into a new read-only private directory**, run from this PR checkout:

```bash
uv run python -m scripts.data.refresh_selected_pool_prices \\
  --root . --market us \\
  --source-csv-dir "/PRIVATE/UNPACKED_ORIGINAL_SOURCE/data/csv_source" \\
  --output-root "/PRIVATE/NEW_EDITION/us_price_refresh" \\
  --start 2021-01-04 --cutoff 2026-11-03 \\
  --full-refresh
```

`/PRIVATE/UNPACKED_ORIGINAL_SOURCE` is the extracted original `market_source_us_41764999985.zip` parent; `/PRIVATE/NEW_EDITION` must be outside Git and have an unused output child. **Do not copy this placeholder verbatim.** Run only under the operator's existing vendor entitlements; a rate-limit, missing 87-symbol coverage, still-contaminated row or mismatched OHLCV must block the edition. **Do not pass `--allow-partial` for the full-US87 research rerun.** This command builds a new isolated producer price output; it does **not** by itself create a compliant new v6 bundle or approve its Colab rights.

When ready, use the existing P2 dataset builder/verification workflow to create a separately named immutable versioned bundle with updated manifests, producer and provider provenance, and all affected derived components. It is **not** valid to patch the original v5 ZIP in-place or to just change SHA strings in a Colab notebook.

## Repair at the source, not in the portfolio evaluator

1. **Local data agent / owner:** obtain independent provider evidence for both stocks across the affected dates, including raw and adjusted OHLCV, split declarations and **effective trading dates**. Check whether 2026 corporate actions were incorrectly back-adjusted for only part of the historical series; establish whether volume and factor series are on the same scale. Do not mechanically divide or multiply dates based solely on observed ratios. Preserve terms, licenses and provider request receipts.
2. **Producer:** rebuild the *entire governed US87 price edition* with consistent price/volume semantics and all retained source manifests, per-member hashes, upstream source identities, aggregated manifest and derived parquet/component lineage. Use a **new** source/edition directory, not the original v5; avoid changing the official 2026-11-03 cutoff or falsely claiming complete listing history.
3. **Verifier:** run original bundle verifier and the new audit against every US87 constituent plus QQQ (not only KLAC/CRWD). Inspect other corporate actions, duplicate/missing sessions, OHLC constraints, vendor adjustment flags, outlier-return distributions and 10 audited exception rows. Require zero unresolved scale events and real reference-snapshot rights. Any price exceptions require documented independent evidence, not a bypass flag.
4. **Research operator:** create a brand-new batch/campaign identity with new source manifest and archive SHA256, and current audited runner Git SHA. Update the private Colab notebook and private rights declaration for the exact source edition. **Never change the frozen old checkpoint or resume new-data training from it.**
5. **Owner manually executes:** run a small first chunk after confirming audit PASS, then the frozen 261-task research campaign. Save new checkpoint ZIP and both checkpoint SHA256 identities; no automatic cloud runs or credential/account transfers.
6. **Independent reviewer:** inspect per-fold results, seed distinctness, costs/slippage, strategy exposure, asset- and sector-level attribution, extreme daily return filtering, point-in-time/membership limits and benchmark parity. Re-run `comparison_report`; only eligible search configurations enter the ranking. The reserved 2026-07-01—2026-08-04 holdout remains `NOT_CERTIFIED` until historical non-consumption can be demonstrated, not merely because the script excluded it.

**PR stop condition:** code / tests may pass before the owner supplies corrected market data. Mark source repair and the real rerun **BLOCKED**, not `PASS`. No old vs new comparison should conflate different market-data identities. The old 261 task count remains valid engineering evidence but **invalid Alpha evidence**.

Research boundaries remain `research_only=true`, `trade_ready=false`, `pit_certified=false`. US Alpha158 true VWAP licensing/sourcing blockers remain unchanged.

## Acceptance ledger

| Evidence | Current |
| --- | --- |
| Actual Colab completed task receipts | PASS — 261/261, 0 blocked (old data) |
| Stage and archive hashes / original snapshot preserved | PASS |
| Detect KLAC/CRWD scale discontinuities | PASS — 10 source events independently scanned |
| Shared campaign fail-closed gate | Implemented in PR; CI pending |
| Regression tests and per-fold/seed diagnostics | Implemented in PR; CI pending |
| New externally verified adjusted OHLCV snapshot | BLOCKED — source acquisition/repair required |
| New immutable bundle and exact code/data pins | NOT_RUN |
| Owner cloud retrain on corrected data | NOT_RUN |
| Scientific ranking / final untouched holdout | BLOCKED / NOT_CERTIFIED |


## Exact canonical provider-response retention

For a new full refresh, pass `--provider-evidence-root /PRIVATE/NEW_EDITION/provider_responses`
to the same `scripts.data.refresh_selected_pool_prices` CLI. The default US
Yahoo adapter then requests action columns with `auto_adjust=False, repair=False`,
retains each exact returned frame as Parquet before normalization, and records
request options, retrieval UTC, client/code SHA256, raw SHA256 and the normalized
frame/hash with reconciliation metadata. No cookies or credentials are retained.
The directory must be outside the source checkout. Failed material OHLC frames
retain raw request evidence but have no successful normalization artifact.

This records the actual frame used by the canonical producer; a second Yahoo
request is a separate source vintage and can differ even in rounded historical
Adj Close. Do not patch canonical CSVs or loosen integrity thresholds to force
that separate response to agree. Verify the recorded raw frame through the
unchanged adapter normalization, then compare it with the exact canonical output.
Volume is passed through unchanged, factor=1 is an already-adjusted identity,
and amount is adjusted close times provider volume, not an exchange turnover.
Provider Close with auto_adjust disabled is not certified as as-traded raw price;
preserve actual split/action records and document vendor historical restatement.


## Executed canonical rebuild and immutable v6 delivery

Frozen producer/next-runner Git SHA:
`0c8152496ebeeed559ceab9b095594501fca516b` (Backend/Policy/GitGuardian PASS).
The requested original audit actually ran on retained v5 and reproduced nine
KLAC and one CRWD event. Original per-file/source/checkpoint hashes were sealed
before data acquisition and independently rechecked after packaging.

The canonical command was executed with `--full-refresh`, start2021-01-04,
cutoff2026-11-03, no `--allow-partial`, and then with explicit QQQI/TQQQ/SGOV/CGDV
references plus exact provider-response capture. The final build materialized
**87candidates + QQQ + 4references = 92securities**: **91fresh full-history Yahoo
responses**, plus EA's exact declared terminal history through2026-08-04
(`dbc6ea09520cfa073fa948b3a4cac3d5ef2f4bc65bd5fb5c5ed6feb4477b58fe`).
No contaminated incremental tail was merged. The terminal exception is disclosed,
not labelled a fresh provider fetch or dropped from US87.

Each of91exact recorded yfinance returned DataFrames reproduces normalized
Parquet byte values through the existing adapter. Canonical CSV values match
within the unchanged serialization tolerance; every volume value matches the
provider directly. All92 full histories have **zero scale anomalies and zero
unexplained interior trading-session gaps**. Official SEC split dates match the
recorded action columns: KLAC10:1 first adjusted trading2026-06-12, CRWD4:1
2026-07-02; announcement, record and distribution dates remain distinct.

Request semantics: yfinance1.2.0, `auto_adjust=False`, `repair=False`,
`actions=True`, inclusive requested cutoff handled by exclusive provider end
2026-11-04. [Maintainer adjustment documentation](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html)
states that auto_adjust=False OHLC is already split-adjusted and AdjClose also
includes dividends. The canonical adapter uniformly multiplies OHLC by
AdjClose/Close, keeps volume unchanged, sets factor=1 as already-adjusted
identity and recomputes synthetic amount=adjusted_close×volume. Exact original
client frames, events, adjustment ratios, request/client/code hashes and
reconciliation evidence are retained. These are not certified exchange
as-traded raw prices/volume or historical source vintages. Independent second
Yahoo requests showed tiny historical AdjClose-vintage differences; capturing
the actual canonical return resolves reproducibility without relaxing gates.

US market evidence and affected OHLCV factor series were rebuilt using existing
provider/market-evidence tooling and the canonical model-data builder, followed
by existing P2 `build_local`, `local_history_pack` and `verify_bundle`. Shared
market projection requires accepted formal metadata; it was read only for that
existing input identity/event interface. P2 data-only filtering removed all
formal events/model/account signals before transport. No model fitting or
strategy evaluation occurred. New US producer source archive contains the
canonical CSVs and exact raw/normalized response evidence. The four original
US/CN events, CNAlpha158 and professional-reference archives remain at their
prior byte-identical source versions.

Final edition: **`us87-cn130-20261103-local-v6-us87-fullrefresh`**, 207files /
**463,622,539bytes**.

- Total Manifest SHA256:
  `4f8225f3c68ee0886b9b707ca140e91dcb509b739b8548fdc10f258574d3da1a`.
- US market ZIP SHA256:
  `b4745e46fc26b0328e22de50e579ebbf1d400996258ea6ebb43c1ff739ed5a1a`
  (16,035,050bytes).
- All bound file hashes/sizes, original4domainarchives, allZIPCRCs and
  1,030,712Parquetrows passed offline reads. A second US ZIP build reproduced
  exactly the same bytes. A fresh106-file isolated root passed source and scale
  validation. Network-blocked preflight and campaign planning passed.
- US87 actual candidate rows120,401; all92US histories126,671rows over retained
  2021-01-04..2026-11-03. Full87+QQQ common history remains292sessions
  2025-06-05..2026-08-04; no claim of complete listing history.
- Whole cross-domain bundle remains **PARTIAL**, 5existingprofilesREADY /
  1USAlpha158BLOCKED, with source/PIT/volume/universe limitations retained.

Saved to Owner's Drive Desktop root project:
`G:/My Drive/AlphaEngine/03_Data/Research_Exchange_P2/input_packages/us87-cn130-20261103-local-v6-us87-fullrefresh`.
All207files passed strict size/SHA readback. Remote sync and ACL verification
remain unperformed, per Owner's directory-sync workflow.

Next job: `colab_jobs/us87-v6-price-repair-0c8152496e`, 8files/55,943bytes,
Manifest SHA256
`487e5085bddcaa2b193a8ca3ae43facda11ea5107c97dac6cbecf548a04353b9`.
Current direct root entry `AlphaEngine/运行模型探索.ipynb` selects this version;
the previous Owner-edited notebook was backed up privately before replacement.
All model/feature/parameter/seed/fold/cost/pool choices are unchanged. New
`batch_id=us87_colab_model_search_v6_20261103`, source hashes and run identity
are frozen; checkpoint parent is a new job-specific subdirectory under
`incoming_unreviewed`. All restore pins areNone and training defaultsOFF.
The legacy `v5_bundle_manifest_sha256` field/staging module name remains a
compatibility identifier; verified content is the separately bound v6 edition.
Owner's existing exact Yahoo cloud-compute attestation is rebound to new hashes;
documentary proof remains absent, not vendor-certified, and immutable source
approval flags were not switched on.

Originalv5's200files and all14existingCheckpointZIPs retain SHA256s. Completed
261-task checkpoint SHA256:
`a760372a8ef8e704ec428b77a66598451de9e3095bc2a1461acc9063129e8219`,
innerindexSHA256
`215e2599685f57b9d86b6bb62691436bdd879f3a9741ecb6c019ba47b4d727b5`.
It is preserved as engineering evidence only and cannot resume the new dataset.

Evidence and all new pins:
[repair acceptance](../evidence/us87_price_repair_2026-11-06/README.md),
[exact v6 Manifest](../evidence/us87_price_repair_2026-11-06/bundle-manifest-v6.json),
[per-symbol coverage](../evidence/us87_price_repair_2026-11-06/coverage.json),
[old/new anomaly ratios](../evidence/us87_price_repair_2026-11-06/v5-v6-anomaly-comparison.json),
[next configuration](../evidence/us87_price_repair_2026-11-06/next-colab-config.json),
[Drive readback](../evidence/us87_price_repair_2026-11-06/drive-delivery.json).

Current remaining acceptance is explicitly future work: Owner-initiated initial
cloud chunk, fresh-session restore and a new corrected-source campaign, then
independent results review. This task stops after data/config preparation; no
new research training, final holdout evaluation or PR merge is authorized here.
