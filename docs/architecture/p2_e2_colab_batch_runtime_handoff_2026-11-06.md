# P2-E2 US87 Colab training batch — working handoff

**2026-11-07 current acceptance:** Owner completed corrected v6 at261ready/0blocked. Independent local restore and all261 input-hash comparisons PASS; researchPROVISIONAL/promotionBLOCKED. Source remains frozen0c8152496e with v6 SHA bindings. [Postrun acceptance](../evidence/us87_v6_colab_review_2026-11-07/README.md) and PR#1380 hold current review/cache status; older NOT_RUN paragraphs below record prior preparation stages. No new training or merge was performed by this review.

**Current corrected-source entry (PR #1377):** `G:/My Drive/AlphaEngine/运行模型探索.ipynb` now binds independent v6, new batch ID/checkpoint parent, runner `0c8152496ebeeed559ceab9b095594501fca516b`; training defaults OFF. Original v5 has KLAC/CRWD contamination; old261-task outputs are preserved engineering evidence and inadmissible for model selection. See [executed price-repair acceptance](us87_price_integrity_incident_2026-11-06.md#executed-canonical-rebuild-and-immutable-v6-delivery). Earlier deployment entries below are historical.

**Branch:** `feat/p2-e2-colab-batch-foundation-20261106` (stacked **Draft [PR #1374](https://github.com/liuh886/alpha_engine/pull/1374)** onto data [PR #1368](https://github.com/liuh886/alpha_engine/pull/1368)). **Issue:** [#1373](https://github.com/liuh886/alpha_engine/issues/1373). Architecture authority [PR #1367](https://github.com/liuh886/alpha_engine/pull/1367).

**Latest local execution (2026-11-06):** two actual full-US87 XGBoost trials are ready, a fresh-directory checkpoint restore continues without fitting the completed trial twice, and the notebook's local flow independently reproduces the CLI study hash. Fixed runner `79e1045bf3ed99bab13ef092cbb07af6ebbf8d99` passed Backend/Policy/GitGuardian. Owner confirmed existing cloud-compute permission and explicitly instructed the Agent **not to access Colab**; Owner will operate it personally. A configured private notebook/spec/attestation bundle is saved to Drive Desktop. **Colab execution remains NOT_RUN**, GPU benefit unmeasured, and documentary license proof path not supplied. Keep `research_only=true / trade_ready=false / pit_certified=false`. Immutable v5 and original producer SHA are unchanged.

**Current Owner entry after Drive relocation (2026-11-06):** `G:/My Drive/AlphaEngine/运行模型探索.ipynb`. The project is now directly in Drive root, and the current owner job is `AlphaEngine/03_Data/Research_Exchange_P2/colab_jobs/us87-exploration-root`. The original SHA-named deployments below are retained historical records; use the root entry or new `-root` job. Data/runner/spec/rights pins remain unchanged.

## Implemented now

- `src/research/v5_isolated_staging.py`: verifies root v5 manifest and US market-history ZIP against two independently pinned SHA256s, invokes the established full archive member verifier and stages real `configs/` + `data/` source files in a **fresh directory outside Git**. It emits a source/sha receipt and rescans all staged files before training. **No silent original-source overwrite, current Git catalog fallback or provider fetch.**
- `src/research/colab_experiment_batch.py`: complete-US87 + QQQ **XGBoost validation search** using existing Study Workspace. Deterministically expands frozen time folds × explicit parameter combinations × fixed seeds, keeps `max_trials` capped and executes `run_study` with only the isolated data root. It writes immutable per-trial input, raw study receipt and unreviewed result SHA. `--max-new-trials` bounds each chunk and `--resume` checks batch/runner/config/inner study identity, skips exact completed trials and retains prior blocked counts. `checkpoint`/`restore` whitelist only verified study JSON and plans, cap snapshots at 20 MiB, require an independent index SHA and a fresh restore root, and reject injected files before copying. Atomic completed studies interrupted before wrapper retention are recovered without another fit. **Blocked model runs remain evidence; they are not bypassed.**
- `notebooks/colab_e2_us87_model_batch.ipynb`: owner-run private Drive notebook, **public template opt-ins OFF by default**, separate exact-SHA-bound per-provider cloud-compute rights check, Python 3.12.12 / uv 0.9.10 pins, sparse reviewed-code checkout, one-time data copy to scratch, staged US87 price-root and bounded training chunks. Optional checkpoints save immediately after each chunk through the same CLI used locally. The privately configured Owner copy enables these opt-ins based on Owner's explicit permission/intent and still runs only when Owner manually executes it. Colab results are never auto-published or trade promoted.
- `docs/product/examples/p2_e2_colab_us87_xgb_validation_batch.example.json`: first 16-trial **validation-only** budget (2 chronological folds × 2 depths × 2 learning rates × 2 seeds). This is a *config example*, not a claim that every US87 constituent has sufficient training history.
- Targeted unit tests (plan, domain/split/budget refusal, source no-overwrite/tamper, interrupted checkpoint/resume) in existing CI.

## Verified US87 common-sample constraint (actual v5 source bytes)

Independent direct read of `us_market_history.zip` (106 archive entries + manifest) confirms that **all 87 selected candidates AND QQQ share only 292 fully observed trading sessions from 2025-06-05 through 2026-08-04**. The **EA** price series stops on **2026-08-04**, although other members and QQQ extend to the 2026-11-03 dataset cutoff. The sole CRCL row start 2025-06-05 is the common-window beginning. For the first *strict full-87* search, train/test must stay inside this common session intersection; the example second validation period is therefore capped at **2026-08-04** (not 2026-08-31). The XGBoost trainer uses 20-session lookback features and a 5-session *forward* ranking label, reducing effective training rows. Check the actual resulting training/validation counts and no-inference-on-nontrading stocks.

These facts do **not** mean the entire portfolio's historical 2021–2026 period is uniformly complete, do **not** guarantee every new study has sufficient data, and do **not** establish PIT or survivorship-free training. A later date-varying universe needs a different, explicitly authorized experiment protocol, not a silent exclusion of EA from the frozen US87 pool.

## Local Agent first real-data commands (Windows PowerShell)

Use **latest** stacked branch once PR #1368 is synced. Do not accidentally switch to `main`, which does not yet include the v5 staging/preflight code.

```powershell
git fetch origin
git switch --track origin/feat/p2-e2-colab-batch-foundation-20261106
uv sync --frozen

$v5 = 'G:/My Drive/AlphaEngine/03_Data/Research_Exchange_P2/input_packages/us87-cn130-20261103-local-v5'
$private = 'G:/My Drive/AlphaEngine/03_Data/Research_Exchange_P2/agent_e2_work'

# Avoid writing large/temporary training data into Git or a public folder.
# Prefer a non-synced local scratch directory for training; Drive is transport/checkpoints.
$scratch = Join-Path $env:TEMP 'alpha-p2-e2-us87'

uv run --frozen python -m src.research.v5_isolated_staging stage `
  --manifest "$v5/bundle-manifest.json" `
  --archive "$v5/us_market_history.zip" `
  --expected-manifest-sha256 d9f4fb2ef7aa2735cfb95436e7eabb744ffb8d6d387c4294626893fc262dab0c `
  --expected-archive-sha256 93b2d42cebf3ebfac7b80298f6822fdc4305f7550b73ac1b2bb8d272d3fb3de8 `
  --output-root "$scratch/us87_data"

# Copy (do not edit) the provided example into a private untracked path.
# Replace only runner_git_sha with your full, current, reviewed Git commit SHA,
# then adjust folds/params to the actual US87-common data history.
uv run --frozen python -m src.research.colab_experiment_batch plan `
  --batch-spec "$private/us87_xgb_batch.json"

# First: fit *one* actual XGBoost validation trial before starting a long sweep.
uv run --frozen python -m src.research.colab_experiment_batch run `
  --batch-spec "$private/us87_xgb_batch.json" `
  --data-root "$scratch/us87_data" `
  --output-root "$scratch/results" `
  --max-new-trials 1

# If the first receipt is plausible, continue without repeating it.
uv run --frozen python -m src.research.colab_experiment_batch run `
  --batch-spec "$private/us87_xgb_batch.json" `
  --data-root "$scratch/us87_data" `
  --output-root "$scratch/results" `
  --max-new-trials 2 --resume
```

For the code branch already checked out locally, `runner_git_sha` must equal `git rev-parse HEAD` exactly. If it changes during a later fix, start a new frozen batch ID, or explicitly document/revalidate the experiment input identity. Never edit retained receipt hashes.

If an actual run reports `BLOCKED` due to price basis, missing sessions, sample-count insufficiency, factor semantics or model calibration, **record the reason, fix the real input contract rather than weaken gates or invent rows**. The included example is a starting point, not guaranteed-valid test windows.

## First Colab acceptance, later

After the **owner independently checks source-provider rights** for the exact US price data in a private Colab runtime:
1. Copy an independently reviewed **full 40-character** CI-green code SHA into the notebook, the matching exact frozen private batch spec and private rights record. Initial notebook flags remain `False` until intentional owner opt-in.
2. Owner launches the trusted Colab notebook, runs v5 hash/source checks and one **two-trial chunk**, then (with separate opt-in) writes its hashed checkpoint to private `incoming_unreviewed`. Do not run an unattended 24×7 Colab scheduler.
3. Restart or open another session, explicitly select one checkpoint folder, verify its files and hashes, continue `--resume`. Checkpoint identity includes batch JSON bytes, runner Git SHA and history archive SHA. If restored contents differ, refuse instead of silently resuming.
4. Compare a *matched* local small batch and Colab same-code inputs/seed/costs/outputs, record run time, RAM/CPU/GPU and numerical tolerances. Hardware availability is not guaranteed.
5. Only after baseline and source-rights proof should more model candidates, Optuna/HPO, final untouched test and alternative features be added under #1373. The first runner currently supports bounded XGBoost parameter grids, **not Optuna or LightGBM**.

## Clear boundaries

**Data:** US87 candidate selection at present is a curated retrospective pool. Snapshot-source availability is not multi-vintage PIT. The 2026-11-03 price cutoff does not imply all tickers have data back to 2021. **Six profile gates remain 5 READY/1 US Alpha158 BLOCKED**. This foundation cannot train US Alpha158 or make new provider entitlements appear.

**Research:** This first batch is `validation_search_only`. Hyperparameter winners cannot be evaluated on the same folds as an untouched final test. Multiple comparisons, survivorship, overlapping labels and cost/model instability require later independent OOS review. No model is adopted automatically.

**Engineering:** no new hosted scheduler, duplicate model trainer, public raw data, broker connection, account positions, strategy promotion, frontend execution or automatic market source refresh. Backend CI on a stacked PR may need local target-run or a main-targeted check because GitHub Actions filters can exclude non-main PR bases; **do not claim green on Governance-only actions**.

## Local Agent must return

- Exact HEAD, environment, commands, true test outcome and batch spec SHA.
- Actual v5 staged files/roster and data field/date coverage.
- First real trial status/receipt, and whether resume reproduces/avoids duplicates.
- Whether an independent vendor cloud rights record exists (do not fake one).
- Model issues blocking the first real training, and the smallest concrete repair commit.
- Colab actual run status (**NOT_RUN** until owner executes) and next training workload estimate derived from measured local trial runtime.

**Stop** when one real local training receipt is retained and a rights-qualified, owner-run Colab batch is ready. Do not perform complex sweep automatically without owner approval.

## Executed acceptance and delivered Owner notebook

The frozen runner is `79e1045bf3ed99bab13ef092cbb07af6ebbf8d99`; the data
producer remains `32c30ef05258a35e4300b6a21ea7a96d0dab17cf`. Actual Drive v5
staging verified 106 files, all US87 candidates and QQQ. Direct source intersection
reconfirmed 292 common sessions, 2025-06-05–2026-08-04.

Two real first-fold trials each used **120 effective training sessions / 10,440
row-symbol observations**, **61 validation sessions**, all 87 candidates, the
existing 20-session feature lookback and 5-session forward label. Measured study
wall times were **5.14 and 5.21 seconds**; complete CLI calls took **7.96 and
7.04 seconds**, with sampled process-tree peak RSS about **223 MB** on the local
16-logical-CPU Windows machine. These are execution observations, not evidence
of predictive value or expected Colab throughput. A naive 16× first-fold timing
is about 83 seconds before larger-fold/setup/Drive/hardware differences; GPU
speedup remains NOT_MEASURED.

After the first actual trial, a four-file results checkpoint was sealed, restored
into a fresh output directory and continued with `--resume --max-new-trials 1`:
one prior trial skipped, one new fit, prior bytes unchanged. The final seven-file
checkpoint was exported through the same CLI to the Owner's Drive Desktop
`incoming_unreviewed/local-pilot-79e1045bf3-20261106`; index SHA256 is
`1def7c1513849d0577dbf109c5684786595199c0721058f79028f2e7121b0eb9`.
The independently executed local notebook flow used substituted local mount/code
bootstrap cells; it performed real local fitting/checkpoint export and returned
the **same study hash as the matching CLI trial**, differing only in wall-clock
timestamp. It was rendered to HTML and visually inspected. This is explicitly
local flow validation, not Colab execution or remote Drive validation.

The private Owner deployment is seven files / **30,201 bytes** at logical path
`AlphaEngine/03_Data/Research_Exchange_P2/colab_jobs/us87-validation-79e1045bf3`.
It includes `AlphaEngine_US87_Colab_READY.ipynb`, exact batch and Owner rights
record, pinned runtime SHA, local validation summary, Chinese operation guide
and a SHA-bound deployment manifest. All files passed Drive Desktop filesystem
readback. Manifest SHA256:
`276bcfd91ed6317a66221b00b40bfde6279700b1c339bb560d3a245d43dcad7f`.
The public template retains placeholders and disabled opt-ins; personal paths
and the actual Owner rights record are not committed.

Owner confirmed existing cloud-processing permission in this conversation.
The separate rights record binds exactly `yfinance`/Yahoo and the v5 hashes;
preflight verifies that each actual archived provider is covered. It records
**Owner attestation, not independent vendor certification**. Documentary proof
path is explicitly null, rather than invented. The frozen source flags are
unchanged. Owner must manually run the notebook and provide a real cloud receipt
before Colab/local parity, resource benefit or E2 full acceptance can be claimed.

Local regression suite: **52 passed** (staging, E1-A, batch and existing actual
Study Workspace cases), Ruff PASS, Mypy PASS. All applicable remote checks at the
frozen runner SHA passed. Evidence:
[local execution summary](../evidence/p2_e2_2026-11-06/local-training-acceptance.json),
[deployment manifest](../evidence/p2_e2_2026-11-06/owner-run-deployment-manifest.json).
No Colab access by the Agent, broad automatic sweep, model promotion, frontend
change or original v5 mutation occurred. PR remains Draft and #1373 stays open.


## Current multi-model preparation — Owner-directed expansion, PR #1376

This section supersedes the initial slice's XGBoost-only workload restriction;
its immutable data, rights and evidence boundaries still apply. Issue #1373
remains the roadmap authority. Owner will operate Colab personally; the Agent
has not accessed it. The prior #1374 deployment and all v5 bytes are unchanged.

Frozen runtime: `b3764bab1a4eb694e302053db16426de2e3573fb`. A specification
compiler adds XGBoost, existing LightGBM and a fixed 20-day momentum comparator
to the same Study Workspace, native adapters and causal simulator. Legacy
`cross_sectional_xgb_v1` XGBoost specs keep their original serialized form;
non-default model families are explicit in specs and every new receipt. No new
trainer, model registry or scheduler was introduced. The shared evaluator now
uses real embargo-period inference context and the last actual pre-validation
session as its anchor; training labels remain restricted to train_end. This
fix prevents a skipped-price gap from becoming a multi-day first test return.

The executable example is
[`p2_e2_colab_us87_model_search.example.json`](../product/examples/p2_e2_colab_us87_model_search.example.json).
It freezes **29 configurations / 261 fold-seed tasks** (252 model fits and 9
rule-baseline evaluations), including 12 pre-sampled XGBoost and 12 LightGBM
parameter configurations, controlled full/momentum/risk-liquidity feature
comparisons and higher-cost stress. The compiler deterministically samples
without replacement, not Optuna/Bayesian/pruning. Each configuration uses three
expanding chronological folds × seeds 17/42/123. At least five XNYS sessions
separate train_end from validation. July 1–August 4, 2026 is excluded from every
search cutoff; historical non-consumption is explicitly **NOT_CERTIFIED**.

[`colab_e2_model_exploration.ipynb`](../../notebooks/colab_e2_model_exploration.ipynb)
retains public opt-ins OFF and source/spec/rights/code/environment pins. Default
owner chunks start at most six new tasks and stop starting work after 300 seconds;
a running native fit may complete later. Three consecutive model exceptions
stop new attempts and preserve blocked receipts. Reports retain incomplete and
failed candidates; a search configuration enters validation ranking only after
all nine tasks are ready. Scores are descriptive, never final-test admission.

Single-ZIP checkpoint transport wraps the existing strict sealed inventory and
20 MiB uncompressed result budget, reducing Drive small-file writes. Both ZIP
and inner-index SHA256 must be independently provided on fresh-session restore;
unsafe members, changed identities, unexpected files and modified receipts are
rejected before final output copy. ZIPs contain specs/receipts, not source bars
or model weights. An interruption within a native fit restarts that unfinished
trial; completed atomic studies are recovered without refitting.

Actual final-code acceptance: **107 relevant tests PASS**, Ruff PASS, Mypy PASS;
Backend, Policy and GitGuardian PASS. A three-task real local pilot retained
one rule baseline, exported/restored one ZIP into fresh outputs, skipped the
retained task and fitted XGBoost/LightGBM. Each trained model used 114 effective
training sessions / 9,918 row-symbol observations and 39 validation sessions;
all three were ready. Prior bytes were unchanged. The 17-cell notebook local
flow then restored that exact pilot, fitted the two models and generated the
comparison table/figure and new ZIP; matching CLI/notebook study hashes passed.
Mount and clone/install were explicitly substituted with local equivalents;
actual model/evidence code was unchanged. HTML/table and figure were inspected.

Owner delivery: private Drive Desktop logical exchange
`colab_jobs/us87-exploration-b3764bab1a`, **8 files / 55,447 bytes**: configured
`AlphaEngine_US87_Model_Exploration_READY.ipynb`, campaign/plan summary, rights
record, runtime SHA, local validation, Chinese instructions and total manifest.
All file sizes and SHA256s matched on filesystem readback. Manifest SHA256:
`d73cf9ffb3d5491a626b58487055ba82a3b292e72c701a38a631e33cb65e11d7`.
See [actual local acceptance](../evidence/p2_e2_2026-11-06/model-exploration-local-acceptance.json),
[deployment hashes](../evidence/p2_e2_2026-11-06/model-exploration-deployment-manifest.json)
and [Drive filesystem readback](../evidence/p2_e2_2026-11-06/model-exploration-drive-readback.json).
Remote Drive sync/ACLs and real Colab training/parity/resources remain unverified.

Status: **LOCAL_ACCEPTED_OWNER_RUN_READY**, E2 cloud acceptance still **PARTIAL**.
No local 261-task sweep, Colab access, GPU speedup claim, final holdout evaluation
or automatic model promotion. Full US87+QQQ remains 292 sessions; snapshot PIT,
curated-universe bias and unavailable true US Alpha158 remain independent limits.
Current models use CPU and existing OHLCV features; deeper/neural/CN experiments
require a separate frozen source/applicability contract and measured need.
Owner's exact Yahoo/yfinance cloud-compute attestation is reused unchanged;
documentary proof path is still absent and no vendor certification is claimed.

Next concrete action belongs to Owner: run the configured notebook's first six
cloud tasks, retain its ZIP path plus archive/index SHA256, then continue chunks
or restore in a fresh session. Local Agent verifies returned raw study receipts
against the frozen spec/code/source before evidence admission. Compare matched
local/Colab task hashes/numerical tolerances and actual resource observations;
only these real cloud runs can close #1369/#1373 acceptance. Keep #1376 stacked
on #1374; remove temporary CI feature-base filters when retargeting the merged
stack to main. Do not close the roadmap on preparation alone.


## Owner-requested Drive root relocation, 2026-11-06

Moved the complete project from `03_PROJECTS｜个人项目/AlphaEngine` to Drive root
`AlphaEngine`, verified the old source is absent and retained the original
**442 files / 916,719,479 bytes**. SHA256 matched for **435 ordinary files**;
seven Google Docs/Sheets virtual pointers cannot be opened as normal file bytes
and were checked by relative path and filesystem length. Original data, results,
ZIP archives and previous deployed job bytes were not changed.

Current direct entry: `G:/My Drive/AlphaEngine/运行模型探索.ipynb`, identical to
the configured notebook in `colab_jobs/us87-exploration-root`. All paths use
`/content/drive/MyDrive/AlphaEngine`; model source remains frozen at
`b3764bab1a4eb694e302053db16426de2e3573fb`. A second relocated basic XGBoost
job is `colab_jobs/us87-validation-root`, still using its original runner.
Updated deployments are new versions; SHA-named originals retain every byte.
Both new notebooks compile, preserve the original source code except configured
paths, and bind unchanged datasets, study specs, runtime SHA and rights records.
The current source/manifest/spec/rights hashes and resolved paths were checked.
No new training or Colab access was needed for this relocation.

- Multi-model job: **8 files / 56,157 bytes**, Manifest SHA256
  `3d6cb1464306c15bf4915822c4bcd1a4914bcb59965c3b08b8be8e0a7311af4a`.
- Basic job: **7 files / 31,011 bytes**, Manifest SHA256
  `18ec98b2bf62dd8f660fbd86a1f41eabafa3daf3234904630ba390f2968b5f50`.
- Root notebook SHA256:
  `02af0a08a25c0fccb951e4ad253b1dd0d2df7dcda3234832147773ab0fdf569d`.

All new files passed Drive filesystem size/SHA readback. Remote Drive
synchronization/ACLs and Colab execution remain unverified; Owner's Drive
Desktop sync is responsible for upload. Existing historical transfer receipts
retain their original location statements. Use the
[relocation receipt](../evidence/p2_e2_2026-11-06/drive-root-relocation.json)
and new job deployment manifests for current locations.
