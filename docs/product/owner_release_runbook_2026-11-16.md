# Owner release runbook and rollback rehearsal plan

- **Issue:** [#1281](https://github.com/liuh886/alpha_engine/issues/1281) — owner-local release candidate, recovery runbook and verified rollback.
- **Prepared:** 2026-11-16 against `main` `f20f3e7a0301c1542ce93c91d7530c1e12b54fd5`.
- **Status:** Draft for Owner review. This document is **not** a release acceptance, **not** a frozen release candidate, and **not** an A6/A7 approval. A6 and A7 remain Owner-blocked.
- **Companion:** [`owner_local_workstation_runbook.md`](../operations/owner_local_workstation_runbook.md) keeps the 2026-11-02 local-workstation notes and A0–A7 snapshot. This document narrows the release path and supersedes it only for release/rollback procedure.
- **Boundary:** `research_only=true`, `trade_ready=false`. No order execution, no tenant support, no subscription billing, no new scheduler, backend or persistent store.

## 0. How to read this document

Evidence tags used below:

- **[VERIFIED]** — executed in this documentation task, or read directly from the cited repository file/line, workflow or GitHub API.
- **[PENDING]** — requires an Owner-named value or Owner action.
- **[NOT_VERIFIED]** — could not be confirmed here; do not treat as true.

Commands are written for the Owner's Windows workstation in PowerShell. POSIX equivalents are the same arguments. Every command shown exists in this repository; see [Appendix A](#appendix-a-command-verification-log).

## 1. Purpose and boundaries

This runbook gives one operator a repeatable path through:

1. clean-checkout setup from the lockfiles;
2. provider configuration and secret handling without secret values;
3. the daily read (`doctor`, published-release verification, Today/System);
4. controlled manual research replay;
5. review of a Reviewed Formal Backtest Refresh publication;
6. diagnosis of the failure classes actually observed in this repository;
7. restore and rollback without rewriting sealed evidence;
8. a rollback rehearsal plan marked **NOT_EXECUTED**;
9. a release candidate freeze whose SHA and cutoff fields stay **PENDING**.

Hard boundaries:

- The console reads evidence. It never executes research or orders ([`docs/product/strategy_console.md`](strategy_console.md)).
- The active strategy registry, selected-pool/reference registries, frozen contracts and evidence stores remain the only authorities. Do not add a parallel registry, evaluator, scheduler or state database (`AGENTS.md`).
- Sealed formal evidence is read-only during an incident. A rollback restores a previously verified product artifact or working-tree bytes; it does not re-seal, rewrite, delete or re-point formal history.
- A green CI run, a successful deployment or a positive historical return does not certify release acceptance. The 2026-10-25 W4 review remains `NO-GO` with `owner_decision: null` ([`w4_release_review_2026-10-25.json`](../evidence/product_v1/w4_release_review_2026-10-25.json)).
- A5 is separately accepted: the [#1282](https://github.com/liuh886/alpha_engine/issues/1282) receipt records `owner_A5_acceptance: "ACCEPTED"` on 2026-11-16 ([`reproduce_local_reference_1282_2026-11-15.json`](../evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json)). That acceptance does not advance A6 or A7.

## 2. Preconditions and access

### 2.1 Repository and authority

- Repository: `liuh886/alpha_engine`; default branch `main`.
- An Owner account with repository admin rights for: Actions dispatch, Actions secrets, environment settings, and reading the private `liuh886/alpha-engine-data-archive` archive with a scoped deploy key.
- Read first: `AGENTS.md`, `DESIGN.md`, ADR-0003, [`docs/product/strategy_console.md`](strategy_console.md), and [`docs/architecture/repository_data_convergence.md`](../architecture/repository_data_convergence.md).
- The active four strategies are defined by `configs/strategies/registry.json` and `data/research/formal_model_runs/catalog.json`. Do not add a fifth strategy, restore a retired route, or change pool/cost/factor identities to make a gate pass.

### 2.2 Toolchain versions from the lockfiles and CI

| Tool | Requirement | Authority |
| --- | --- | --- |
| Python | 3.12 (`.python-version`); `pyproject.toml` declares `>=3.10` | `.python-version`, `pyproject.toml:6` |
| uv | 0.12.7 in CI | `.github/actions/setup-python-uv/action.yml` |
| Node | `^20.19.0 || ^22.13.0 || >=24`; Pages uses 24, refresh uses 22 | `qlib-dashboard/package.json` `engines`, `deploy-pages.yml:110-115`, `formal-backtest-refresh.yml:1032-1037` |
| Dependencies | `uv.lock`, `qlib-dashboard/package-lock.json` | both files; do not regenerate to pass a gate |

**[VERIFIED]** A5 acceptance used Python 3.12.12 and uv 0.9.10 against the same lockfiles, with `locks_modified: false` ([`reproduce_local_reference_1282_2026-11-15.json`](../evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json)). CI pins uv 0.12.7. For release reproduction, use the CI pin; record the uv version in the freeze.

### 2.3 Provider configuration

Provider capabilities and their credential variable names are declared in `src/data/provider_catalog.py`; frozen source contracts live under `configs/providers/` and `configs/data_contracts/`.

| Purpose | Variable | Requirement |
| --- | --- | --- |
| CN vendor chain (Tushare) | `TUSHARE_TOKEN` | Required for CN formal refresh (`formal-backtest-refresh.yml:145`) |
| SEC EDGAR access | `SEC_USER_AGENT` | Required by SEC contracts (`configs/providers/sec_companyfacts_fundamentals_v1.yaml` `http.user_agent_env`) |
| US professional SIP prices | `POLYGON_API_KEY` | Credentialed US source (`src/data/provider_catalog.py:145-157`) |
| Tiingo professional EOD | `TIINGO_API_TOKEN` | **Deliberately unset**: no paid entitlement; active research uses the versioned Yahoo source (`formal-backtest-refresh.yml:691`) |
| SEC egress proxy | `SEC_EGRESS_PROXY_URL`, `SEC_EGRESS_PROXY_ID`, `SEC_EGRESS_MODE` | Optional egress mode; `MODE`/`ID` are repository variables in CI |

The maintained Python entry points do **not** auto-load `.env`; no `load_dotenv`/`dotenv` import exists under `src/` or `scripts/` **[VERIFIED by search]**. Set variables in the shell for the session. `.env` is gitignored (`.gitignore:63`).

### 2.4 Required secret and variable names (names only — never values)

GitHub Actions secret names referenced by the maintained workflows:

- `TUSHARE_TOKEN`
- `SEC_EGRESS_PROXY_URL`
- `POLYGON_API_KEY`
- `GOVERNED_SOURCE_ARCHIVE_SSH_KEY` (read-only private deploy key; raw key content)
- `GOVERNED_SOURCE_ARCHIVE_WRITE_SSH_KEY` (private retention/checkpoint writer)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (decision delivery)
- `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` (Alpaca data in Alpha158 CI)
- `FORMAL_REFRESH_TOKEN` (optional PAT so refresh PR checks run without human approval; falls back to `github.token`)

Repository variables: `SEC_EGRESS_MODE`, `SEC_EGRESS_PROXY_ID`.

Local variables used by this runbook:

- `GOVERNED_SOURCE_ARCHIVE_SSH_KEY` — raw private-key text, not a path.
- `SEC_USER_AGENT`, `TUSHARE_TOKEN`, `POLYGON_API_KEY` — as above.
- `ALPHA_RELEASE_CANDIDATE` — optional fallback candidate id for `release_gate.py`.

Handling rules:

- Never write a secret value into a PR, issue, log, screenshot, artifact, receipt or this document.
- The private ledger transport receipt must be written **outside** the repository; `alpha ops private-ledgers` rejects an in-repository receipt (`src/cli/main.py:711-713`).
- Keep local `operations.json` and `system-health.json` private: they describe current operations. Do not copy them into a public directory.

### 2.5 Protected account and session needs

- GitHub: Owner/admin for Actions dispatch and secrets; the `github-pages` environment currently permits deployment only from branch `main` (API: one `branch_policy`, name `main`) **[VERIFIED 2026-11-16]**. No required-reviewer rule was returned.
- Private archive: a repository-scoped read deploy key for `alpha-engine-data-archive`; a write key for checkpoint persistence.
- Current-operations entitlement is server-enforced and out of scope for a Pages rollback. Real Owner/Pro/denied/expired/revoked sessions remain **NOT_TESTED** (A4 FAIL in W4). Do not treat a Pages verification as an entitlement test.

## 3. Setup from a clean checkout

```powershell
git clone https://github.com/liuh886/alpha_engine.git
cd alpha_engine
git rev-parse HEAD

uv sync --frozen --extra dev
uv run --frozen alpha --help

cd qlib-dashboard
npm ci --no-audit --no-fund
npm run build
cd ..
```

Expected:

- `alpha --help` prints `{data,research,ops,personal,racetrack}` **[VERIFIED by execution]**.
- `npm run build` runs `check:i18n`, `check:account`, `sync:research-assets`, `check:formal-evidence`, the Vitest suite, then `vite build` (`qlib-dashboard/package.json`). The strategy-operations sync regenerates the gitignored read models with `uv run alpha ops build` when they are missing or stale (`qlib-dashboard/scripts/sync-strategy-operations.mjs:190-210`).
- The Pages workflow additionally asserts `dist/index.html`, `dist/sw.js`, `dist/icons/alpha-engine.svg`, `dist/data/formal-model-runs/catalog.json`, `dist/data/strategy-operations/snapshots.json`, and rejects `dist/data/strategy-operations/capabilities.json` and `dist/data/formal-backtests` (`deploy-pages.yml:116-129`).

Set the session variables (values redacted; read the key from its protected file):

```powershell
$env:GOVERNED_SOURCE_ARCHIVE_SSH_KEY = Get-Content -Raw "$HOME\.ssh\alpha-engine-archive-read"
$env:SEC_USER_AGENT = "AlphaEngine Research <owner-contact>"
$env:TUSHARE_TOKEN = "<cn-vendor-token>"
$env:POLYGON_API_KEY = "<us-sip-key>"
Remove-Item Env:TIINGO_API_TOKEN -ErrorAction SilentlyContinue
```

Do not echo these variables. `Get-Content -Raw` produces the raw key text that `_private_git_environment` expects (`src/data/governed_actions_artifact.py:397-416`).

## 4. Daily operating read

### 4.1 Verify local governed evidence

```powershell
uv run --frozen alpha ops private-ledgers restore --receipt "$env:TEMP\alpha-private-ledgers.json"
uv run --frozen python scripts/doctor.py
```

- `doctor` verifies the formal catalog, every manifest and every available section, then prints operating state, per-strategy provider/formal/factor/decision cutoffs, affected stages and the decision evidence (`scripts/doctor.py:49-94`).
- Exit `0` means `current`; exit `1` means blocked or unverifiable. A failure to import dependencies prints the locked-install remedy.
- Restoring private ledgers hydrates the gitignored ledger root `data/research/strategy_signal_ledgers/` (`.gitignore:69`) and does not dirty Git.
- **[VERIFIED]** A clean checkout at `f20f3e7a03` without active private ledgers reported core state `blocked`, all four strategies `factor=blocked`, and decision evidence “The decision publisher exists, but no cutoff-bound evaluation has been committed yet.” Treat that as an unhydrated local state, not release health. Re-run after ledger restore. The exact post-restore stage attribution is **[NOT_VERIFIED]** here.

Optional read-only source check:

```powershell
uv run --frozen python scripts/data/fetch_governed_model_data.py --inspect
```

`--inspect` reads pinned source retention with no token, network or refresh visit (`--help` text).

### 4.2 Verify the published release

```powershell
$deployed = (Invoke-RestMethod "https://liuh886.github.io/alpha_engine/deployment.json").commit_sha
uv run --frozen python -m scripts.verify_pages_release `
  --base-url "https://liuh886.github.io/alpha_engine/" `
  --expected-commit $deployed
```

Expected receipt keys: `status: "verified"`, four `formal_models`, `formal_sections_verified`, `public_operations_verified: true`, `research_only: true`, `trade_ready: false` (`src/artifacts/pages_release_verification.py:487-497`).

**[VERIFIED]** Run against the live origin on 2026-11-16 with expected commit `c6530f019de010de887cda52863d63763f943227`: `status=verified`, 4 models, 36 formal sections, public operations verified, exit 0. The section count is evidence, not a constant.

### 4.3 Read Today and System

- Today: `https://liuh886.github.io/alpha_engine/#/app` (root redirects to `/app`).
- System: `https://liuh886.github.io/alpha_engine/#/system`.
- The router is a `HashRouter` (`qlib-dashboard/src/App.tsx:82-84`), so share `#/app` and `#/system`, not bare `/app`.
- Today shows the daily research brief, top three priorities and formal strategy fleet. Read current observation, target/change, reason, next evaluation, cutoff and blockers.
- System shows source publication, health diagnosis, recovery and workflow actions. It is an operations view, not a second evidence authority.

### 4.4 Understand “Pages behind main”

`deploy-pages.yml` first runs `scripts/detect_pages_impact.py`. A change with no publication dependency produces `deploy=false`, reason `no_publication_impact`; the live origin is intentionally unchanged (`detect_pages_impact.py:203-204`; `pages-release-receipt.yml:129-135`).

**[VERIFIED]** On 2026-11-16 the rolling receipt comment `5160974834` said “skipped — no publication impact” for main `bd57c67c5d5d949bebf273e3ad9aafef07d426a7`, while `deployment.json` still reported `c6530f019de010de887cda52863d63763f943227`. That is expected behavior, not a failed release. To publish a specific revision intentionally, use `workflow_dispatch` with `target_sha` (section 8.1), which forces `manual_dispatch` (`detect_pages_impact.py:268-273`).

Local operations read (keep output private):

```powershell
$observedUtc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
uv run --frozen alpha ops build --generated-at $observedUtc --output artifacts/local-review/operations.json
```

This writes `artifacts/local-review/operations.json` and `artifacts/local-review/system-health.json`; `/artifacts/` is gitignored except `artifacts/release_candidate/`.

## 5. Controlled manual research

### 5.1 Exact replay commands

```powershell
uv run --frozen alpha research replay cn_27_v1_3
uv run --frozen alpha research replay qqq_v4_3
uv run --frozen alpha research replay byd_v1_3
```

- Choices are `{qqq_v4_3, byd_v1_3, cn_27_v1_3, all}` (`src/cli/main.py:143-159`) **[VERIFIED by `--help`]**.
- Exit `0` requires `"decision": "exact_replay"`; any other decision exits `2` (`src/cli/main.py:569-570`).
- `--refresh-data` rebuilds the governed QQQ exact-cutoff recipe instead of reusing a verified cache. Do not pass it during an incident or to make a mismatch disappear.

### 5.2 Frozen history versus appended economics

- **CN_27 v1.3:** the frozen source and trace boundary is `2026-09-04`, while the record cutoff is `2026-11-13`. The replay reproduces the frozen trace; it does not extend it (`cutoffs.cn_27_v1_3` in the #1282 receipt). The A5 acceptance explicitly keeps “CN_27 reproduces the frozen trace boundary 2026-09-04; appended economics are not part of this audit.”
- **QQQ v4.3:** the accepted trace boundary is `2026-11-12`. The replay assembles the full six-symbol source at cutoff `2026-11-13` and must reproduce the accepted decision prefix exactly; there are no appended rows beyond the boundary (`cutoffs.qqq_v4_3`).
- The prefix gate compares only the accepted row count: `observed[:len(expected)]` for `report`, `positions`, `trades` (`src/research/rules_formal_replay_gate.py:45-71`). A prefix match does not re-seal appended economics.
- The US replay depends on live Yahoo availability; provider-vintage reproducibility is **not** claimed (`provider_caveat` in the #1282 receipt). The transient `^VIX`/`^VXN` block was environment-sensitive: conda `yfinance 1.0` versus the locked `1.2.0`.

### 5.3 Never during an incident

Do not:

- retrain, tune parameters, change costs, factors or pool membership to obtain an exact replay;
- forward-fill missing bars, substitute a provider or silently drop a selected symbol;
- promote a model, change a model identity, or reopen model selection (`model_selection_reopened: false` in refresh receipts);
- edit, delete or re-seal a formal manifest/section to match a recomputation;
- rerun training because a status page is blocked.

A failed replay or source block is retained as research memory; it is not a reason to alter the frozen contract.

## 6. Formal publication review

### 6.1 What opens the PR

`Reviewed Formal Backtest Refresh` runs on schedule `30 8,23 * * 1-5`, on relevant `main` pushes, and on `workflow_dispatch` (`formal-backtest-refresh.yml:3-120`). When the publication delta is non-empty it force-pushes `automation/formal-backtest-refresh`, opens or updates a **draft** PR, waits for `formal-backtest-refresh-ci.yml` on the exact candidate SHA, marks it ready, squash-merges with `--match-head-commit`, then dispatches Pages with the merge SHA and watches it (`formal-backtest-refresh.yml:1080-1276`).

PR title: `data: refresh governed evidence through US <us_cutoff> / CN <cn_cutoff>`.

The PR body asserts: exact US/CN cutoffs, Active Strategy Catalog membership, independent receipt-bound strategy execution, one atomic Bundle v2 preview fan-in with no flat formal state, immutable historical prefix, model selection not reopened, research only, not trade ready.

### 6.2 Artifact inventory to inspect

Download the bounded refresh evidence artifact to a private directory (not the repository):

```powershell
gh run download <RUN_ID> `
  --name "formal-backtest-refresh-<RUN_ID>-attempt-<ATTEMPT>" `
  --dir "$env:USERPROFILE\alpha-engine-private\refresh-<RUN_ID>"
```

The artifact contains (`formal-backtest-refresh.yml:1466-1488`):

| Artifact path | What it proves |
| --- | --- |
| `artifacts/formal-refresh/plan/plan.json` | immutable plan: active membership, target cutoffs, per-strategy tasks |
| `artifacts/formal-refresh/strategy-fan-in-receipt.json` | atomic preview fan-in; `status` complete/degraded; `retained_strategy_ids` |
| `artifacts/formal-refresh/formal-refresh-receipt.json` | `candidate_ready_for_review` or `candidate_ready_with_retained`; boundaries |
| `artifacts/formal-refresh/formal-v2-sync-receipt.json` | deterministic Bundle v2 projection |
| `artifacts/formal-refresh/publication-delta-receipt.json` | initial delta against the run’s base |
| `artifacts/formal-refresh/publication-delta-latest-main-receipt.json` | delta against current `main`; `publication_required`, `status` |
| `artifacts/formal-refresh/freshness-input/freshness.json` | market cutoffs and next deadlines |
| `provider-us/`, `provider-cn/` manifests | provider status and publication eligibility |
| `market-evidence/us/catalog.json`, `market-evidence/cn/catalog.json` | shared market evidence identity |

Also inspect the `formal-refresh-plan-<run_id>` artifact (contains `plan.json`) and the public PR diff for `data/research/derived_metrics/`.

The derived-excess receipt is
`data/research/derived_metrics/qqqi_qqq_tqqq_v4_3_excess_vs_qqq_v1.json` (default in `src/artifacts/derived_formal_excess.py:35`). It binds the derivation to the newly published QQQ `run_id`, `bundle_id`, manifest path and SHA-256, and retains `method`, `window`, `result`, `reconciliation`, `inputs` and `boundaries` (`derived_formal_excess.py:310-400`).

### 6.3 Review checklist

1. **Candidate identity.** `gh pr view <n> --json headRefOid,mergeStateStatus` matches the candidate SHA recorded in the run. The merge uses `--match-head-commit`.
2. **Plan.** `refresh_required: true`; target US/CN cutoffs are completed sessions, not vendor-stale dates.
3. **Fan-in.** `status: "complete"` and empty `retained_strategy_ids`. A `degraded` fan-in is not automatically wrong, but the retained strategy id and its cause must be explained before merging.
4. **Refresh receipt.** `status` is `candidate_ready_for_review`; `candidate_ready_with_retained` requires the same explanation. `model_selection_reopened` must be `false`.
5. **Latest-main delta.** `publication_required: true` and `status: "publication_required"`. `semantic_no_change` must not be merged as if it were a publication; the historical #1286 defect was an incorrect `jq -e` abort on that status.
6. **No semantic drift.** For sealed roots, `missing_path_count` and `extra_path_count` are zero; `semantic_changed_paths` contains only the expected cutoff advance; `raw_metadata_only_paths` contains only regenerated metadata such as `freshness.json`.
7. **Identity.** The formal catalog’s `model_version_id` set equals the Active Strategy Catalog set; model families, kinds and markets are unchanged; no fifth strategy.
8. **Derived excess.** `reconciliation.total_return_absolute_difference` and `benchmark_return_absolute_difference` are at or below `1e-12`; `reconciliation.sealed_summary_modified: false`; `boundaries.research_only: true`, `trade_ready: false`, `live_signal: false`. The artifact must bind the new QQQ run, not a predecessor.
9. **Privacy.** The derived artifact contains no `operating_state`, `current_weights`, `target_weights`, `trades`, `decision_reason`, `decision_state`, `positions`, `weight_*` or `*_weight` keys (`qlib-dashboard/scripts/public-derived-metrics.mjs:18-27,136-156`). Deployment repeats the zero-leakage check over the assembled site.
10. **CI.** `formal-backtest-refresh-ci.yml` succeeded for the exact candidate SHA. Do not merge on a different run.
11. **No evidence rewrite by review.** The review may reject the PR, but it must not edit sealed bundles in the branch.

### 6.4 Post-merge acceptance to attach

- Pages workflow run id/URL for the merge SHA, conclusion `success`.
- `deployment.json` from the live origin with `commit_sha` = merge SHA.
- Verifier receipt (`status`, four `formal_models`, section count, `public_operations_verified`).
- `pages-live-browser-evidence` artifact from the deploy run.
- The rolling Pages receipt comment `5160974834`.
- `operating-observation.json` from the refresh artifact. It records `manual_interventions: null` and `acceptance_status: awaiting_independent_intervention_and_decision_delivery_review`; it does **not** certify 20 sessions.

## 7. Error diagnosis

Each class below is fail-closed. Diagnose the owning stage; do not make a gate green by editing evidence.

### 7.1 Provider block: `^VIX` / `^VXN` empty

**Symptom.** `StrategyDataBundleError: Yahoo signal reference is empty: ^VIX` or `^VXN`; the strategy bundle is blocked with `missing=['^VIX', '^VXN']`; replay exits `2`.

**First checks.**
1. Confirm the project interpreter and locked `yfinance`:
   `uv run --frozen python -c "import yfinance, sys; print(sys.executable, yfinance.__version__)"`.
2. Re-run the replay under `uv run --frozen`; do not reuse a conda interpreter.
3. Confirm the cutoff is a completed market session and that the source is reachable.
4. Read the session-filter evidence in the bundle `details.signal_reference_session_filter`; a provider stub row outside the QQQ equity calendar is not a valid row.

**Expected fail-closed behavior.** `src/data/strategy_data_bundle.py:143-160` raises on an empty reference, missing `open`/`close`, or no rows through the cutoff; lines 203-205 reject references with no governed-session rows. No forward fill or substitution occurs. The #1282 receipt retains this exact block and its resolution.

**Pointers.** `src/data/strategy_data_bundle.py`; `src/data/provider_catalog.py`; #1282 receipt `historical_blockers_and_defects[0]`.

### 7.2 Historical-prefix gate failure

**Symptom.** `RulesFormalReplayError: <label> exact replay mismatch: {...}`; or a strategy task fails with `StrategyRefreshBlocked("invalid_evidence", "<field> changed before the reporting boundary")`.

**First checks.**
1. Read the comparison payload: section, `expected_rows`, `observed_rows`, first mismatch index/field, max absolute difference.
2. Check whether the implementation, price basis, adjustment or session filter changed since the accepted run.
3. For a refresh, read `frozen_prefix_rows` in the strategy receipt.
4. If the accepted evidence itself is internally inconsistent, stop. A correction needs an Owner-approved policy and a separately reviewed correction commit (for example the QQQ reason-label correction in PR #1446), not an incident edit.

**Expected fail-closed behavior.** No exact-replay claim, no preview seal, no PR publication. QQQ compares only the accepted decision prefix (`src/research/qqq_authoritative_replay.py:370-405`). The CN refresh verifier requires `len(after) >= len(before)` and prefix equality for `report`/`positions`/`trades` (`scripts/run_formal_strategy_refresh.py:68-84`). Strategy jobs run with `fail-fast: false`, so one failure does not silently drop other strategies.

**Pointers.** `src/research/rules_formal_replay_gate.py:34-90`; `scripts/run_formal_strategy_refresh.py:68-84`; `tests/test_rules_formal_replay_gate.py`.

### 7.3 `DerivedMetricPublicationError`

**Symptom.** The frontend sync fails with `Derived metric publication rejected: <reason>`; `npm run build` fails before `vite build`; the Pages deploy stops before upload.

**First checks.**
1. Regenerate the artifact from the newly published QQQ run:
   `uv run --frozen python -m scripts.derive_formal_benchmark_excess --repository-root .`
2. Confirm the artifact’s `strategy.run_id`/`bundle_id`/`manifest_sha256` match the public formal catalog.
3. Check the rejection reason. Common causes in `public-derived-metrics.mjs`: a private/operational key, wrong `evidence_type`/`schema_version`, invalid `derivation_id`, missing `boundaries`, `research_only` not `true`, `trade_ready` not `false`, non-finite numbers, a derivation matching zero or multiple catalog records, a model-family mismatch, an unsafe manifest path, or a manifest SHA mismatch.
4. Re-run `cd qlib-dashboard; npm run sync:formal-model-runs`.

**Expected fail-closed behavior.** The sync throws; the build fails; no stale derived metric is published. The deploy workflow’s later zero-leakage assertions never run because the build already failed.

**Pointers.** `qlib-dashboard/scripts/public-derived-metrics.mjs:31-39`; `src/artifacts/derived_formal_excess.py`; `qlib-dashboard/scripts/sync-formal-model-runs.mjs:280+`; `tests/test_public_source_boundary.py`.

### 7.4 Private Ledger CAS conflict

**Symptom.** `PrivateLedgerConflictError`; “private ledger conflict: restore latest state and rerun; never rebase a stale decision”; or a rejected fast-forward push (`non-fast-forward`, `fetch first`, `rejected`, `stale info`).

**First checks.**
1. Restore the latest authoritative private state:
   `uv run --frozen alpha ops private-ledgers restore --receipt "$env:TEMP\alpha-private-ledgers.json"`.
2. Compare the restore receipt’s `private_commit`, `archive_sha256` and byte size with the base used by the failed persist.
3. Confirm the intended write extends the current ledger. A same-date changed decision without a `correction` record is rejected.
4. Never rebase, force-push, or replay external side effects.

**Expected fail-closed behavior.** Persist refuses when the base archive SHA/size differs (`src/artifacts/private_signal_ledger.py:228-236`). The restore guard refuses to replace newer local sealed evidence with an obsolete private seed (`_assert_extends`, lines 185-199). The fast-forward-only push is the CAS; a concurrent writer wins and the local write is rejected (lines 255-267).

**Pointers.** `src/artifacts/private_signal_ledger.py:35-44,94-98,185-270`; `docs/operations/private_signal_ledger.md`.

### 7.5 Pages impact skip

**Symptom.** The deploy workflow concludes `success` but `deploy=false`; the rolling receipt says “skipped — no publication impact”; `deployment.json` is older than `main`.

**First checks.**
1. `gh run view <RUN_ID> --json conclusion,displayTitle`.
2. Read `pages-impact-decision` artifact; expect `reason: "no_publication_impact"`.
3. Compare `deployment.json.commit_sha` with the commit whose publication you expected. If the change does not touch the publication graph, the skip is correct.
4. If you intentionally need to publish an exact revision, use the manual dispatch in section 8.1. Do not edit the impact detector or add a publication path.

**Expected fail-closed behavior.** The live origin is unchanged; nothing unverified is published. A missing impact decision fails the observer closed as “failed governance observation” (`pages-release-receipt.yml:123-128`).

**Pointers.** `scripts/detect_pages_impact.py:166-204,249-289`; `deploy-pages.yml:24-73`; `pages-release-receipt.yml`.

## 8. Restore and rollback

Two independent recovery paths exist. Do neither without Owner approval. Never mutate sealed formal evidence.

### 8.1 Redeploy a previous Pages SHA

`deploy-pages.yml` accepts an exact `target_sha` on `workflow_dispatch` (`deploy-pages.yml:7-15`). The run’s `RELEASE_SHA` is `inputs.target_sha || github.sha`; checkout, deployment identity and `deployment.json` all use it. A manual dispatch forces `deploy=true` with reason `manual_dispatch`, even when no path changed.

```powershell
gh workflow run deploy-pages.yml --ref main -f target_sha=<TARGET_SHA>
gh run list --workflow deploy-pages.yml --limit 3 `
  --json databaseId,event,headSha,displayTitle,conclusion
gh run watch <RUN_ID> --exit-status
```

Equivalent API form used by the refresh workflow:

```powershell
$payload = @{
  ref    = "main"
  inputs = @{ target_sha = "<TARGET_SHA>" }
  return_run_details = $true
} | ConvertTo-Json -Depth 4
gh api --method POST `
  -H "Accept: application/vnd.github+json" `
  -H "X-GitHub-Api-Version: 2026-03-10" `
  repos/liuh886/alpha_engine/actions/workflows/deploy-pages.yml/dispatches `
  --input <payload.json>
```

Preconditions:

- `<TARGET_SHA>` is an ancestor of `origin/main` and contains the privacy fix for the #1288/#1289 exposure class. Do not roll back to a pre-fix public tree merely because it verifies.
- No refresh or another Pages deployment is in flight; the workflow uses `concurrency: pages-deployment` with `cancel-in-progress: false`.
- The dispatch ref is `main`. The `github-pages` environment currently allows only `main` (verified branch policy). A feature-branch dispatch is rejected.

Expected result: `deploy-pages.yml` rebuilds `_site` from the target tree, validates the formal catalog/manifests/operations, deploys, then runs the verifier and the live Playwright suite.

**Known observer caveat [NOT_VERIFIED at runtime].** `pages-release-receipt.yml` verifies expecting `github.event.workflow_run.head_sha` (`pages-release-receipt.yml:69-87`). For a `workflow_dispatch` on `main`, that is the current `main` HEAD, not `inputs.target_sha`. If the target is older than `main`, the rolling comment may report “failed live-origin verification” even when the rollback deployed correctly. Record the Owner-run verifier receipt from section 8.4 as the authoritative acceptance, and do not infer rollback failure from the comment alone.

### 8.2 Restore the formal root from Git without mutating sealed evidence

The formal roots are committed, sealed bytes. Restoring a working tree to its committed `HEAD` is not a mutation; reverting a publication commit is.

```powershell
git status --short --branch
git fetch origin
git restore --source=HEAD -- `
  data/research/formal_model_runs `
  data/research/model_runs `
  data/research/model_decisions `
  data/research/market_evidence `
  data/research/model_data_bundle_v1 `
  data/research/derived_metrics
git status --short
```

These are the roots the refresh publication commits (`formal-backtest-refresh.yml:1134-1140`).

Rules:

- Restore **from `HEAD`**. Do not `git revert`, `git reset --hard`, force-push `main`, or delete a bundle directory.
- Never edit `manifest.json`, `report`, `positions`, `trades`, `lineage`, `portfolio` or a section declared in a manifest. Deploy validation re-computes each manifest SHA-256 and rejects drift (`deploy-pages.yml:159-179`; `src/artifacts/pages_release_verification.py`).
- For read-only inspection of an older revision, use `git show <SHA>:data/research/formal_model_runs/catalog.json`. Do not check it out over `main`.
- If a published bundle is genuinely wrong, a forward correction must use an Owner-approved correction policy and a separately reviewed commit. The #1446 QQQ reason-label correction is the precedent (`scripts/correct_formal_baseline_prefix.py`), not an incident rollback.
- A rollback does not change strategy identity. Do not re-point a `model_version_id` or re-register a model.

### 8.3 Private ledger and checkpoint restore

```powershell
uv run --frozen alpha ops private-ledgers restore `
  --revision <EXACT_PRIVATE_SHA> `
  --ledger-root "$env:USERPROFILE\alpha-engine-private\ledger-restore" `
  --receipt "$env:TEMP\alpha-private-ledgers-restore.json"

uv run --frozen alpha ops checkpoint-ledgers `
  --restore "<CHECKPOINT_ZIP>" `
  --output "$env:TEMP\alpha-ledger-checkpoint-restore" `
  --expected-sha256 "<ARCHIVE_SHA256>" `
  --expected-byte-size <ARCHIVE_BYTES>
```

- `--revision` must be an exact 40-hex private Git SHA (`private_signal_ledger.py:103-110`).
- Checkpoint restore requires the exact archive SHA-256 and byte size; otherwise it refuses (`src/cli/main.py:745-749`).
- Both outputs must be outside the repository; the CLI rejects in-repository paths.
- Do not move private `main` backwards or force-push it. Forward corrections use the canonical correction contract with retained originals.

### 8.4 Verify after rollback

```powershell
uv run --frozen python -m scripts.verify_pages_release `
  --base-url "https://liuh886.github.io/alpha_engine/" `
  --expected-commit <TARGET_SHA>

$live = Invoke-RestMethod "https://liuh886.github.io/alpha_engine/deployment.json"
$live.commit_sha
$live.workflow_run_id

uv run --frozen python scripts/doctor.py
git status --short
```

Expected: verifier `status: "verified"` with the four models and `public_operations_verified: true`; `deployment.json.commit_sha` equals `<TARGET_SHA>`; the formal catalog SHA-256 equals its pre-rollback value; `git status` is clean; no formal file diff.

If `doctor` is blocked because private ledgers are not hydrated, that is not evidence that rollback failed. Hydrate and re-run, or report the stage honestly.

### 8.5 Evidence to capture

Write evidence outside the repository, or under the gitignored `artifacts/` tree. Never include a secret value.

- Owner approval note: target SHA, reason, timestamp, approver.
- Dispatch payload (`ref`, `target_sha`) with no token.
- Rollback run id and URL; conclusion; job-level statuses.
- Pre- and post-rollback `deployment.json`.
- Verifier JSON receipt, exit code and stderr.
- `git rev-parse HEAD`, `git status --porcelain`, and SHA-256 of
  `data/research/formal_model_runs/catalog.json` before and after.
- If private state was touched: private revision, archive SHA-256, byte size,
  restore/persist receipt path, and confirmation that no sealed original changed.
- Explicit statement that A6 and A7 remain pending.

### 8.6 What a rollback must not do

- Must not re-write immutable formal research evidence or mutate strategy identity (issue #1281 acceptance).
- Must not republish raw canonical/current files as a compatibility path (`docs/architecture/current_operations_publication_repair_1288.md`).
- Must not restore an old public-only writer after private `main` advanced (`docs/operations/private_signal_ledger.md`).
- Must not delete failed records to make the state look clean.
- Must not treat a structurally valid but privacy-incomplete old Pages artifact as a safe target.

## 9. Rollback rehearsal plan

> **STATUS: NOT_EXECUTED.** No dispatch, deployment, rollback or live verification run was performed for this section. This is a plan for Owner execution, not a rehearsal receipt.

### 9.1 Scope and authorization

The rehearsal exercises both recovery paths in production:

1. redeploy a previously verified Pages SHA (`target_sha`);
2. restore the current release SHA and re-verify.

Because this changes the live origin, it requires explicit Owner authorization. A6 remains Owner-blocked; this plan does not claim A6 acceptance.

### 9.2 Preconditions

- Owner has named the rollback target and confirmed it is post-privacy-fix, an ancestor of `main`, and previously verified.
- The current release SHA and its verifier receipt are recorded.
- No refresh workflow is in progress; no other Pages deployment is queued.
- The private ledger read key is available; `doctor` is understood in its current state.
- A private evidence directory exists outside the repository.
- The Owner accepts that the `pages-release-receipt` comment may not reflect `target_sha` (section 8.1 caveat).

### 9.3 Ordered steps

| # | Action | Command | Expected result | Receipt |
| --- | --- | --- | --- | --- |
| 1 | Record current release | `$current = (Invoke-RestMethod "https://liuh886.github.io/alpha_engine/deployment.json").commit_sha` | a 40-hex SHA | `pre-deployment.json` |
| 2 | Record current local evidence hashes | `Get-FileHash -Algorithm SHA256 data/research/formal_model_runs/catalog.json` | hash H0 | `pre-catalog.sha256` |
| 3 | Verify current origin | `uv run --frozen python -m scripts.verify_pages_release --base-url https://liuh886.github.io/alpha_engine/ --expected-commit $current` | `status: verified` | `pre-verify.json` |
| 4 | Prove target is on main | `git merge-base --is-ancestor <TARGET_SHA> origin/main` | exit 0 | console log |
| 5 | Prove privacy fix is in target | `git merge-base --is-ancestor <PRIVACY_FIX_SHA> <TARGET_SHA>` | exit 0 | console log |
| 6 | Dispatch rollback | `gh workflow run deploy-pages.yml --ref main -f target_sha=<TARGET_SHA>` | run created | run id/URL |
| 7 | Watch deployment | `gh run watch <RUN_ID> --exit-status` | exit 0 | run conclusion |
| 8 | Verify rollback origin | verifier with `--expected-commit <TARGET_SHA>` | `status: verified` | `rollback-verify.json` |
| 9 | Confirm Pages identity | read `deployment.json` | `commit_sha == <TARGET_SHA>` | `rollback-deployment.json` |
| 10 | Confirm no evidence mutation | `git status --short`; re-hash catalog | clean; hash H0 | `post-catalog.sha256` |
| 11 | Restore current release | `gh workflow run deploy-pages.yml --ref main -f target_sha=$current` | run created | run id/URL |
| 12 | Watch restore | `gh run watch <RESTORE_RUN_ID> --exit-status` | exit 0 | run conclusion |
| 13 | Verify restored origin | verifier with `--expected-commit $current` | `status: verified` | `restore-verify.json` |
| 14 | Record final state | read `deployment.json`; `git status` | current SHA; clean | `post-deployment.json` |

### 9.4 Abort criteria

Abort before dispatch, or restore the known-good current release after a failed attempt, if any of the following occurs:

- `<TARGET_SHA>` is not an ancestor of `origin/main`, or does not contain the privacy fix.
- The target’s original deployment cannot be identified or its verifier receipt is missing.
- Any formal catalog, manifest or section SHA differs from the committed tree.
- The verifier fails for the target, or `deployment.json.commit_sha` does not equal the dispatch target.
- The private ledger key is unavailable when the rehearsal is meant to include current-state recovery.
- A refresh run starts and would publish concurrently.
- Completing the rehearsal would require editing, reverting or re-sealing evidence.
- Any Owner stop condition is invoked.

### 9.5 Expected receipts

- Two successful Pages workflow runs (rollback and restore), with ids/URLs.
- Two verifier JSON receipts (`status: verified`), exit code 0.
- Pre/post `deployment.json` for both SHAs.
- Catalog SHA-256 before and after, unchanged.
- Clean `git status`.
- A short rehearsal note listing manual interventions and the observer caveat.
- No A6/A7 acceptance statement.

### 9.6 Owner signoff slot

```
Rollback rehearsal performed by (Owner): ______________________
Date (UTC): ______________________
Rollback target SHA: ______________________  (named, not inferred)
Current release SHA restored: ______________________
A6 result:   [ ] PASS   [ ] FAIL   [ ] ABORTED   [ ] DEFERRED
A7 result:   [ ] GO     [ ] NO-GO  [ ] DEFERRED
Evidence directory (outside repo): ______________________
Notes / manual interventions: ____________________________________
```

A6 and A7 remain Owner-blocked until this slot is completed. An agent must not fill it.

## 10. Release candidate freeze

> **STATUS: PENDING.** No SHA, cutoff or release candidate is frozen by this document. The Owner names these after the next governed refresh and UAT. Times and SHAs below are placeholders.

### 10.1 Freeze fields

| Field | Value | How to obtain |
| --- | --- | --- |
| Release candidate id | **PENDING** | Owner-named |
| Source `main` SHA | **PENDING** | `gh api repos/liuh886/alpha_engine/git/ref/heads/main --jq .object.sha` |
| Deployed Pages SHA | **PENDING** | `deployment.json.commit_sha` |
| US cutoff | **PENDING** | `data/research/formal_model_runs/freshness.json` `markets.us` |
| CN cutoff | **PENDING** | same, `markets.cn` |
| Formal catalog SHA-256 | **PENDING** | `Get-FileHash -Algorithm SHA256 data/research/formal_model_runs/catalog.json` |
| Formal bundle ids (4) | **PENDING** | `catalog.json` records |
| `uv.lock` SHA-256 | **PENDING** | `Get-FileHash -Algorithm SHA256 uv.lock` |
| `package-lock.json` SHA-256 | **PENDING** | `Get-FileHash -Algorithm SHA256 qlib-dashboard/package-lock.json` |
| Python / uv / Node versions | **PENDING** | record the exact installed versions |
| Private archive commit | **PENDING** | private-ledger restore receipt |
| Private checkpoint SHA-256 / bytes | **PENDING** | checkpoint receipt |
| Quality gate verdict | **PENDING** | `uv run --frozen python scripts/release_gate.py --candidate <explicit-id> --run-quality-gates --evidence-dir artifacts/release_gates`; verdict at `artifacts/release_gates/release_gate_verdict.json` |
| Deployment acceptance | **PENDING** | deploy run id, `deployment.json`, live verifier receipt, Playwright artifact |
| Privacy/static check | **PENDING** | see 10.3 |
| Post-release evidence | **PENDING** | refresh `operating-observation.json`, operations receipt |
| Rollback target SHA | **PENDING** | Owner-reviewed, post-privacy-fix, ancestor of `main` |
| Owner A6/A7 decision | **PENDING** | section 9.6 |

`release_gate.py` requires an explicit candidate: a manifest path or `rc_*` id, resolved only as
`artifacts/release_candidate/<id>/release_manifest.json` (`src/release/candidate.py:110-122`). The only tracked candidate manifest at this revision is `artifacts/release_candidate/20260620/release_manifest.json` (`rc_20260620`); nothing verified in this task identifies it as the Direction A release candidate. Without an explicit candidate, `release_gate.py` exits `2` unless only quality gates are requested (`scripts/release_gate.py:59-109`).

### 10.2 Privacy/static check set

```powershell
uv run --frozen python scripts/check_legacy_web_boundary.py
uv run --frozen python -m pytest tests/test_public_source_boundary.py -q
cd qlib-dashboard
npm run check:formal-evidence
npm run check:account
npm run build
```

`check_legacy_web_boundary.py` is part of the deploy workflow (`deploy-pages.yml:95-96`) and prints a retirement confirmation. `check:formal-evidence` and `check:account` are build prerequisites (`qlib-dashboard/package.json`). The public-source test checks derived metrics and synced assets for operational fields. `verify_pages_release` additionally validates protected public operations and rejects operational leakage.

### 10.3 Gate status carried forward (no new acceptance)

These are the last recorded evidence statuses, not a re-acceptance. The Owner must re-evaluate at the freeze.

| Gate | Last recorded status | Source |
| --- | --- | --- |
| A0 identity | PASS | W4 review |
| A1 continuous operation | BLOCKED | W4; 20-session evidence not closed |
| A2 data integrity | BLOCKED / Ops PASS | W4; scoped training profiles remain blocked |
| A3 user journeys | BLOCKED / Baseline PASS | W4; real restricted sessions NOT_TESTED |
| A4 permissions and disclosure | FAIL | W4; real sessions NOT_TESTED, historical disclosure residual |
| A5 local research | ACCEPTED 2026-11-16 | #1282 receipt `owner_A5_acceptance: ACCEPTED` |
| A6 release/recovery | BLOCKED | W4; this plan is not a rehearsal receipt |
| A7 Owner decision | NOT_TESTED | W4; `owner_decision: null` |

### 10.4 Freeze rule

A release candidate is frozen only when every field in 10.1 is filled from an actual run, the verifier receipt binds the frozen deployed SHA, the privacy/static check passes, and the rollback target is named and privacy-qualified. A field that is unknown stays **PENDING**; it is never inferred from a nearby run.

## Appendix A. Command verification log

| Command or claim | How verified | Result |
| --- | --- | --- |
| `alpha` console entry | `pyproject.toml:35-36`; `python -m src.cli.main --help` | exit 0; groups `{data,research,ops,personal,racetrack}` |
| `alpha research replay` choices | `--help` execution; `src/cli/main.py:143-159` | `{qqq_v4_3,byd_v1_3,cn_27_v1_3,all}` |
| Replay success/failure exit | `src/cli/main.py:569-570` | exits 2 unless `decision == exact_replay` |
| `alpha ops private-ledgers` | `--help` execution; `src/cli/main.py:697-730` | `restore`/`persist`; receipt must be outside repo |
| `alpha ops checkpoint-ledgers` | `--help` execution; `src/cli/main.py:731-754` | restore requires exact SHA-256 and byte size |
| `alpha ops build` / `publish` / `acceptance` | `--help` execution | flags match section 4 |
| `alpha data list` | executed | four recipes: `cn130-prices`, `qqq-rotation`, `qqq-rotation-sgov`, `us87-prices` |
| `alpha data status` | `--help` execution | `recipe` + optional `--cutoff` |
| `alpha racetrack publish` | `--help` execution | market/as-of/runner flags |
| `python scripts/doctor.py` | `--help` executed; run as `python -m scripts.doctor` under the project venv | verifies catalog/manifests/sections; exits 1 while blocked |
| `python -m scripts.verify_pages_release` | `--help` executed; run against live Pages | `status=verified`, 4 models, 36 sections, exit 0 |
| `python scripts/detect_pages_impact.py` | `--help` executed; source read | `--manual` yields `manual_dispatch`; otherwise `publication_impact` or `no_publication_impact` |
| `python -m scripts.derive_formal_benchmark_excess` | `--help` executed; source read | CLI and default artifact path confirmed |
| `python scripts/release_gate.py` | `--help` executed; source read | explicit candidate required; quality-only allowed |
| `python scripts/generate_release_candidate.py` | `--help` executed | legacy LGBM candidate generator; not prescribed here |
| `python scripts/check_legacy_web_boundary.py` | executed | exit 0, retirement confirmation |
| `python scripts/data/fetch_governed_model_data.py --inspect` | `--help` executed | read-only retention inspection |
| Pages workflow inputs and steps | read `deploy-pages.yml` | `target_sha`, impact gate, validation, verifier, Playwright |
| Published receipt observer | read `pages-release-receipt.yml`; read comment `5160974834` | rolling comment; current status “skipped — no publication impact” |
| Refresh publication path | read `formal-backtest-refresh.yml:1080-1276` | draft PR, CI on candidate SHA, squash merge, Pages dispatch |
| Refresh artifact inventory | read `formal-backtest-refresh.yml:1466-1488` | names in section 6.2 |
| Bundle v2 projection | read `formal-bundle-v2-sync.yml` | deterministic double projection and read-model rebuild |
| Operations publication | read `strategy-operations-release.yml` | restore ledgers, build, OIDC publish, receipt |
| Provider/secret names | searched workflows, `src/data/provider_catalog.py` | names in section 2.4 (no values) |
| Python/Node/uv versions | `.python-version`, `pyproject.toml`, `package.json`, composite action | section 2.2 |
| Live deployment identity | `curl`/`Invoke-RestMethod` of `deployment.json` | `c6530f019d…`, run `43723971939` |
| Pages environment branch policy | `gh api .../environments` and `/deployment-branch-policies` | only `main`; no reviewer rule returned |
| A5 acceptance | `reproduce_local_reference_1282_2026-11-15.json` | `owner_A5_acceptance: "ACCEPTED"` |
| W4 NO-GO | `w4_release_review_2026-10-25.json` | `recommendation: NO-GO`, `owner_decision: null` |

`uv run --frozen` prefixes were not re-executed in this documentation task. Their argument forms are the ones used by the maintained workflows; the underlying scripts were exercised directly where noted.

## Appendix B. NOT_VERIFIED items

1. **Any actual rollback or rehearsal.** No deployment, dispatch, rollback or restore was executed. Section 9 is a plan.
2. **Observer behavior when `target_sha` differs from `main` HEAD.** The expectation in section 8.1 is derived from `pages-release-receipt.yml:69-87`; it was not run.
3. **Secret configuration.** Only secret names were verified from workflow references. Whether each secret currently holds a valid value, and whether the Owner holds the archive key, is not verified.
4. **Clean-machine dependency install.** `uv sync --frozen --extra dev` and `npm ci` were not run in this task; the version and lockfile claims are from configuration, not an install test.
5. **uv 0.12.7.** CI pins it; the local tool available here is 0.9.10. Release reproduction under 0.12.7 was not tested.
6. **A valid Direction A release candidate manifest.** Only `artifacts/release_candidate/20260620/release_manifest.json` is tracked; no current candidate was verified or generated.
7. **Provider refresh end to end.** Yahoo/Tushare/Polygon network refresh and professional entitlement were not exercised.
8. **Private ledger restore with a real key.** The command and guards were read; no authenticated restore was run.
9. **Playwright live evidence contents.** The deploy workflow uploads `pages-live-browser-evidence`; the artifact was not inspected.
10. **Entitlement and real account sessions.** Pages verification proves static publication and protected public operations, not Owner/Pro/denied/expired/revoked session behavior.
11. **Post-restore `doctor` stage attribution.** A clean checkout showed blocked stages; the exact state after private-ledger hydration was not observed here.
