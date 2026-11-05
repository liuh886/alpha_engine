# P2-E2 US87 Colab training batch — working handoff

**Branch:** `feat/p2-e2-colab-batch-foundation-20261106` (stacked **Draft [PR #1374](https://github.com/liuh886/alpha_engine/pull/1374)** onto data [PR #1368](https://github.com/liuh886/alpha_engine/pull/1368)). **Issue:** [#1373](https://github.com/liuh886/alpha_engine/issues/1373). Architecture authority [PR #1367](https://github.com/liuh886/alpha_engine/pull/1367).

This is **executable preparation**, not an accepted real-data model run, proven GPU gain, permission to process vendor data in Colab, or released model. Keep `research_only=true / trade_ready=false / pit_certified=false`. The immutable v5 and original producer SHA stay unchanged.

## Implemented now

- `src/research/v5_isolated_staging.py`: verifies root v5 manifest and US market-history ZIP against two independently pinned SHA256s, invokes the established full archive member verifier and stages real `configs/` + `data/` source files in a **fresh directory outside Git**. It emits a source/sha receipt and rescans all staged files before training. **No silent original-source overwrite, current Git catalog fallback or provider fetch.**
- `src/research/colab_experiment_batch.py`: complete-US87 + QQQ **XGBoost validation search** using existing Study Workspace. Deterministically expands frozen time folds × explicit parameter combinations × fixed seeds, keeps `max_trials` capped and executes `run_study` with only the isolated data root. It writes immutable per-trial input, raw study receipt and unreviewed result SHA. `--max-new-trials` bounds each chunk and `--resume` skips exact completed trials. **Blocked model runs remain evidence; they are not bypassed.**
- `notebooks/colab_e2_us87_model_batch.ipynb`: owner-run private Drive notebook, **all opt-ins OFF by default**, separate exact-SHA-bound per-provider cloud-compute rights check, pinned Git+uv environment, one-time approved data copy to scratch, staged US87 price-root, bounded training chunk, and optional Drive checkpoint with file hashes under `incoming_unreviewed`. Colab results are never auto-published or trade promoted.
- `docs/product/examples/p2_e2_colab_us87_xgb_validation_batch.example.json`: first 16-trial **validation-only** budget (2 chronological folds × 2 depths × 2 learning rates × 2 seeds). This is a *config example*, not a claim that every US87 constituent has sufficient training history.
- Targeted unit tests (plan, domain/split/budget refusal, source no-overwrite/tamper, interrupted checkpoint/resume) in existing CI.

## Local Agent first real-data commands (Windows PowerShell)

Use **latest** stacked branch once PR #1368 is synced. Do not accidentally switch to `main`, which does not yet include the v5 staging/preflight code.

```powershell
git fetch origin
git switch --track origin/feat/p2-e2-colab-batch-foundation-20261106
uv sync --frozen

$v5 = 'G:/My Drive/03_PROJECTS｜个人项目/AlphaEngine/03_Data/Research_Exchange_P2/input_packages/us87-cn130-20261103-local-v5'
$private = 'G:/My Drive/03_PROJECTS｜个人项目/AlphaEngine/03_Data/Research_Exchange_P2/agent_e2_work'

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
