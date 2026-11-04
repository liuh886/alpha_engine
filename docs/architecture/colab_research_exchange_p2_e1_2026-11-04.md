# Alpha Engine P2-E1 — Local/Drive/Colab Research Exchange Pilot

> **Status: implementation pilot, not accepted real-data E2E**, 2026-11-04.
> Compatible with owner-approved [P2 local-only strategy validation PR #1367](https://github.com/liuh886/alpha_engine/pull/1367). This document is subordinate to `AGENTS.md`, `configs/pools/selected_pool_registry_v1.yaml`, the existing governed source manifests and the authoritative product execution plan. Do not treat this as a second canonical data source.

## Objective and negative boundaries

Use **one exact existing source version and one pinned Git revision** for the local workstation and an ephemeral Google Colab worker. Data remains governed in Alpha Engine. Google Drive is a **private, replaceable transport/archive mirror**, not a new authoritative OHLCV database. Colab is an opportunistic batch execution location, never a 24/7 backend or new experiment scheduler. GitHub Pages is a downstream **read-only projection**; no changes to the website, Supabase schema, four formal strategies, release pipeline, live decisions or browser study authoring.

- Daily or coarser only. No minute bars, intraday fills, micro-pullback or broker access.
- Only selected US87 / CN130 pool; all required files and hashes are declared and verified.
- No data is uploaded by this PR. Data license/redistribution review and **manual approval for private Drive copies** are required for each real exchange recipe.
- No private current operations, account info, strategy signal ledger, secrets or credentials may enter exchange packages. This pilot uses a conservative path allowlist AND requires source content review. An approved prefix does not mean its contents are automatically safe.
- Colab cannot authorize its own results as valid, safe, or publishable. Incoming receipts stay **unreviewed** until the local Agent executes the same governed evidence tests, source/cutoff/fee gates and privacy checks.
- Never let Colab output overwrite accepted research receipts or static public projections.
- Results remain `research_only=true`, `trade_ready=false`; SHA-256 detects byte differences but is **not a signature** and does not prove historical PIT availability.

## Existing authorities reused

| Existing component | Reuse | Explicit non-change |
| --- | --- | --- |
| `src/data/research_slice.py` | PIT-limited cutoff / source-slice semantics | Do not recompute missing bars or bypass source blockers |
| `data/research/model_data_bundle_v1/`, pool registry | Governed snapshot, pool/role identity and canonical manifest | Drive copy cannot become new market-data authority |
| `src/research/study_workspace.py`, existing `alpha research study` | Frozen local strategy spec, study receipt generation and evidence comparison | Colab executes the same checked-out Python code and spec |
| `src/research/study_review.py` | Local evaluation and review lifecycle | Do not mark positive result automatically promoted |
| Existing formal Bundle v2 / read-only Research Lab | Future reviewed summaries only | No new frontend data-fetch endpoint or user-triggered computation |

## P2-E1 pilot implementation

`src/research/cloud_exchange.py` is a **transport adapter only**.

- `pack --repo-root . --recipe <file> --output <archive.zip>` checks exact Git commit, US87/CN130 pool-file identity, declared source-manifest path and hash, and SHA256 of all explicit source files. Requires `owner_approved_private_cloud_copy=true` and `rights_class=private_cloud_research_allowed`. The archive is ZIP with immutable `manifest.json` and pinned files; it refuses to overwrite existing archives and prohibits writing packages into frontend directories.
- `verify --archive <archive.zip>` verifies all file hashes, sizes, members, safe paths, authority roles and research-only boundary without extracting. Unknown/tampered input fails closed.
- `stage --archive <archive.zip> --checkout <exact-git-repo>` verifies the complete archive and exact code commit, then adds missing inputs. Different existing files cannot be overwritten; no direct import into accepted formal or public assets. Use a fresh isolated checkout.
- No API keys, Google Drive SDK, Colab executor, new database, scheduler, bucket or frontend changes in this module.

### First use: owner/local Agent steps

1. Review the source data provider's rights, candidate-pool membership and manifest, and assert that a **private** cloud copy is permitted. Do not make assumptions about vendor licensing or sensitive fields. If rights are uncertain, stop at local-only analysis.
2. Copy `docs/product/examples/colab_exchange_recipe_example.json` to a **local untracked** JSON file (the example uses placeholders and is intentionally not runnable). Replace every pinned SHA and revision from verified source bytes and `git rev-parse HEAD`; list only required verified daily data, canonical source manifest and selected-pool file. Do **not** include account/operations paths.
3. Run on a clean, source-verified workstation:

```bash
python -m src.research.cloud_exchange pack --repo-root . --recipe /private/path/recipe.json --output /private/path/us87-study-input.zip
python -m src.research.cloud_exchange verify --archive /private/path/us87-study-input.zip
```

4. Only after reviewing the archive and legal/private storage boundary, manually copy it into a dedicated, non-public Google Drive study-exchange folder. Keep files out of public share links. Folder permission metadata must be reviewed again if moved; do not write Drive folder IDs or OAuth credentials in this public repository.
5. Open `notebooks/colab_research_exchange_pilot.ipynb` in Google Colab **from the trusted repository**. Configure the actual mounted Drive folder path; copy the archive **once** into Colab scratch disk, inspect its manifest, clone the pinned Git revision, run `verify` then `stage`. The notebook intentionally stops short of executing a heavy strategy automatically. Run a real `alpha research study ...` only after the study's dataset/requirements are actually present and governed.
6. Store the resulting research receipt in a Drive **incoming/unreviewed** directory as an immutable uniquely named artifact and re-hash after copy. The local Agent imports and validates it separately, then uses existing research review/publication gates. The website never reads Drive directly.

### Example transfer structure (illustrative, not a new database)

```text
private Google Drive / AlphaEngine / 03_Data / Research_Exchange_P2
  input_packages/          # manually reviewed, hash-verified versioned zip bundles
  incoming_unreviewed/     # returned receipts, not authoritative
  notes/                   # optional operator notes, no secrets
```

The exact folder path within a Colab mount may differ depending on where the Drive folder resides. Do **not** hardcode the user's private folder ID or account path into committed code; configure it interactively.

## Acceptance gates for P2-E1 (not PR merge auto-promotions)

| Gate | Evidence to collect |
| --- | --- |
| Unit/contract correctness | Pack/verify/stage success + deterministic SHA under frozen inputs; 10+ negative tests incl. tampering, revision mismatch, rights missing, traversal, conflicting checkout files |
| Local real-data readiness | Explicit source manifest, correct US87 or CN130 roster, complete daily coverage, confirmed source rights; otherwise `BLOCKED` with reason |
| Colab smoke-test | Manual observed Colab run on *private approved* file package; exact SHA parity against local, exact checkout revision; permissions and provider data considered separately |
| Experiment parity | Same frozen spec and data: same stable research evidence within documented numerical tolerance; compare after verifying dependency versions and random seeds |
| Interrupted transfer | Fail/retry after partial Drive I/O without accepting corrupted input; avoid large numbers of small Drive file reads |
| Evidence ingress | Local independent checks before accepting Colab result; failed or negative receipts retained; never auto-copy results to Pages |
| Privacy | Negative tests for operations/account paths, anonymous public URLs, source-data redistribution and unintended sharing |
| Frontend regression | **No frontend diff** or extra remote run endpoint in P2-E1. Public evidence/static and protected current-op boundaries preserved |

## Open technical work after this PR

- **E1-A**: Complete a manual local→private Drive→Colab→local **real-data** proof with owner-approved source rights; record artifact hashes, elapsed copy time, source availability and CPU/RAM. This PR does **not** claim Colab execution or real market tests.
- **E1-B**: If A passes, add a narrow result-ingress validator mapping into existing Study Workspace evidence. Refuse tampering, stale datasets, incompatible code commits and authority violations. No duplicate database or new strategy evaluator.
- **E1-C**: Benchmark actual P2-1 daily hypothesis under local CPU vs Colab CPU; compare results including OOS/statistical gates. GPU should not be presumed beneficial for small datasets.
- **E1-D**: Only if Drive I/O limits demonstrably become material, evaluate GCS as replaceable **object transport**, not a database migration or an additional source of truth.

## Risk register

- **Cloud entitlement**: Colab compute capacity and session duration are variable. Do not rely on fixed pricing, free GPU, or unattended continuity.
- **Dataset rights**: Public Yahoo endpoints and other providers do not imply unrestricted redistribution; private cloud replication may need specific entitlement.
- **Git identity vs dirty tree**: Git HEAD pins the recorded commit, but a dirty source worktree can alter local execution. Require an independent source cleanliness/evaluator fingerprint check before scientific equivalence is claimed.
- **Hash != signature**: Pin the expected archive SHA through an independent local receipt when the transfer threat model requires authenticity; an attacker with edit access could change both a file and its embedded hash.
- **Daily bar caveats**: Intraday execution and true order-fill slippage cannot be recovered from daily OHLCV. Do not introduce minutes to solve this P2 problem.
- **Research durability**: Write results locally in Colab first, copy to Drive after completion, verify returned bytes and preserve a separate local archived copy. Colab VM storage is ephemeral.
- **Divergent versions**: If the authoritative source advances, create a **new** snapshot and experiment receipt, never replace the old one.
