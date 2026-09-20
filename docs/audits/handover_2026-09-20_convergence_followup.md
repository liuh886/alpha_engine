# Handover — Convergence Follow-up (2026-09-20)

Status: research evidence, `research_only=true`, `trade_ready=false`
Audience: the next agent/operator continuing the Alpha Engine convergence program.
Authority: this is a session handover. The backlog of record is
`docs/audits/convergence_gap_2026-09-19.md` (§8 session log, §9 G7 evidence).
Issues: #1074 (prioritization), #324/#325 (data closure), #826 (training plane),
#1113 (blocked daily refresh), #858 (cleanup), #1118 (weekly safety net).

## 1. Start here — confirm you are synced

```pwsh
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status -sb          # expect: clean, up to date with origin/main
```

Expected `HEAD` is at or after `7caea230` (docs: record second security-bump
batch and held mlflow compatibility item). Do not start from a stale tree; the
convergence work is sensitive to provider/registry state.

## 2. What the previous session changed (already on `main`)

Dependency security updates merged (all lockfile-only, CI green):
`#1121` gitpython, `#1122` anyio, `#1123` cryptography, `#1124` soupsieve,
`#1126` sqlparse, `#1127` tornado, `#1129` pyjwt.

Direct commits:

| Commit | Summary |
| --- | --- |
| `5e8f9610` | `chore(typing): ratchet five more canonical modules into strict mypy` |
| `1782fc40` | `docs: record 2026-09-20 convergence sync, dep merges and mypy ratchet` |
| `a88b2878` | `docs: add G7 dependency-risk evidence for the pyqlib-rooted Dependabot alerts` |
| `7caea230` | `docs: record second security-bump batch and held mlflow compatibility item` |

Ratchet detail: `src.research.ranker_current_target`, `src.research.drift_monitor`,
`src.research.stage_journal`, `src.governance.research_mandate`,
`src.artifacts.strategy_operations` are now in the strict mypy scope in
`pyproject.toml` and `.github/workflows/ci.yml` (25 entries / 24 files).

No committed evidence, registry, model artifact, or release candidate was
modified.

## 3. Verify the inherited state before you build on it

```pwsh
uv lock --check                                             # expect exit 0
uv run ruff check .                                         # expect clean
uv run mypy src/release src/models/metric_contract.py `
  src/research/economics.py src/research/replay_comparison.py `
  src/research/ranker_execution.py src/research/ranker_training.py `
  src/research/us_x1_3_current_target.py src/data/listing_lifecycle.py `
  src/data/symbol_identity.py src/data/snapshot_manifest.py `
  src/factors/ranker_snapshot.py src/governance/active_strategy_catalog.py `
  src/research/formal_baseline.py src/artifacts/system_health.py `
  src/data/model_data_bundle.py src/data/snapshot.py src/data/market_provider.py `
  src/artifacts/formal_bundle_reader.py src/governance/strategy_runtime_capabilities.py `
  src/research/factor_identity.py src/research/ranker_current_target.py `
  src/research/drift_monitor.py src/research/stage_journal.py `
  src/governance/research_mandate.py src/artifacts/strategy_operations.py
uv run pytest tests/test_ranker_current_target.py tests/test_ranker_current_target_runtime.py `
  tests/test_t47_drift_monitor.py tests/test_stage_journal.py tests/test_research_mandate.py `
  tests/test_strategy_operations.py tests/test_strategy_operations_runtime.py `
  tests/test_strategy_operations_release.py -q --strict-markers
uv run python scripts/check_ci_governance.py --output artifacts/ci-workflow-inventory.json --enforce
```

Expected: lock check exit 0; ruff clean; mypy "Success: no issues found in 28
source files"; 68 tests pass; governance "violations=0" with the `dead_modules`
advisory reporting 84 of 527.

## 4. Next work, in priority order

### P0 — G1: unblock the daily refresh (#1113)
The committed `2026-09-11` US x1.3 current target still contains terminal
listing `EA`, so the formal refresh correctly fails closed
(`USX13PreviewError: canonical US x1.3 target has no governed entry price`).

- The selection guard is already landed (`752d0e44`, `src/data/listing_lifecycle.py`).
- **What remains is operational, not code**: a governed regeneration of that
  current target on the corrected provider, then re-seal the ledger
  (`scripts/run_ranker_current_target.py` for the `2026-09-11` session).
- This is a data/evidence publication action. Do it through the governed
  refresh path, not by editing committed evidence. Needs the provider
  environment and owner-governed execution.
- Acceptance: the regenerated target excludes `EA` with an explicit
  `lifecycle_excluded_symbols` diagnostic, and the next eligible session's
  formal refresh completes with no unexplained blocker.

### P1 — G7: land the held mlflow security update (#1128)
`#1128` bumps mlflow `1.27.0 → 3.16.0` and would remove 73 of 183 open pip
Dependabot alerts (including 22 critical). It is **held on purpose**.

- The project uses qlib's MLflow-backed recorder:
  `src/common/qlib_init.py` (`qlib.workflow.expm`, sqlite MLflow backend),
  `src/research/backtest.py` (`from qlib.workflow import R`),
  `src/api/mcp_server.py` (`R.list_rec`).
- `pyqlib 0.9.7` targets the mlflow 1.x API. The upgrade resolves cleanly and
  `import mlflow` works, but the recorder surface is not proven by the suite.
- Required before merge: an isolated PR (or the Dependabot branch) with a
  qlib recorder smoke test that actually writes/reads a recorder run against
  the sqlite backend under mlflow 3.x, plus a full backend CI run.
- Then continue package-by-package (`mistune`, `pillow`, `tornado`, `jupyter*`)
  with the same evidence standard. Revisit the `setuptools==69.5.1` direct pin
  separately. See `convergence_gap_2026-09-19.md` §9.

### P1 — G2/G3: close the per-symbol data gaps (#324, #325)
Evidence: `data/research/model_data_bundle_v1/data-components.json` and
`model-data-readiness.json` (built 2026-09-18).

- `fundamentals.cn_selected_equities_v3` partial 129/130 — missing `301666`
  (`provider_missing`).
- `fundamentals.us_selected_equities_v2` partial 86/87 — missing `SBGSY`
  (`identity_missing`).
- `factors.qlib_alpha158.panel.cn.v1` partial 129/130 — `301666`
  (`not_yet_applicable`).
- `us_selected_alpha158_v1` is **blocked** (G3): materialize the US87 Alpha158
  panel with governed VWAP semantics.
- Acceptance: `fundamentals.*` components ready, 0 blocked components,
  `us_small_pool_price_plus_fundamentals_v1` and `us_selected_alpha158_v1`
  training profiles ready. Rebuild the readiness bundle and commit the refreshed
  manifests through the governed pipeline.

### P2 — G4: canonical training plane (#826)
Gated on G2/G3. One reproducible trainer must reproduce US x1.2 `r11_sampled`
from immutable inputs, with a deterministic trained artifact and score trace.
Do not start against legacy/latest-discovered artifacts.

### P2 — G5: obsolete-path removal (#858)
The `dead_modules` advisory is now 84 of 527 (`factor_identity` converged because
`src/release/quality.py` imports it). Each family in §5 of the gap report still
requires explicit owner approval before deletion. Delete, do not wrap.

### P3 — G6 (next unit): `cn_x1_2_current_target` protocol debt
2 remaining strict-mypy errors:
`CrossSectionalExperimentSpec` vs `RankerExperimentContract` — the protocol
declares settable members while the concrete class exposes read-only attributes.

Reproduce the ratchet workflow:

1. Add the module to the strict override list in `pyproject.toml`
   (`ignore_errors = false`) and to the mypy list in `.github/workflows/ci.yml`.
2. `uv run mypy src/research/cn_x1_2_current_target.py` and fix the errors
   (likely a protocol/attribute annotation change in the shared spec).
3. Re-run the mypy list, `ruff`, and the current-target tests.
4. Keep `pyproject.toml` and `ci.yml` lists in sync — `check_ci_governance`
   and CI both depend on it.

### P3 — G8: weekly full-suite cadence (#1118)
Weekly cron and auto-close-on-recovery are in place; PR CI still runs a curated
subset. The full-suite cadence for `main` is an owner decision.

## 5. Guardrails (do not violate)

- Everything stays `research_only=true`, `trade_ready=false`.
- Never silently drop/substitute a selected symbol, forward-fill statements, or
  mix raw and adjusted prices.
- A blocked or partial component fails closed; never patch it with
  validation-only providers or synthetic fields.
- Do not rewrite or patch committed evidence; regenerate through the governed
  path. Deletions preserve git history.
- Do not tune model parameters, factor definitions, costs, or pool membership
  after observing evaluation evidence.
- Do not merge `#1128` (mlflow) without the qlib recorder smoke evidence.

## 6. Useful pointers

- Backlog of record: `docs/audits/convergence_gap_2026-09-19.md` (§4 table,
  §5 module families, §6 execution order, §8 session log, §9 G7 evidence).
- Operating protocol and complexity limits: `AGENTS.md`.
- Readiness evidence: `data/research/model_data_bundle_v1/`.
- Listing lifecycle registry: `configs/data_quality/symbol_identity_and_lifecycle_v1.yaml`.
- Governance/CI rules: `docs/ci-governance.md`, `.github/ci-policy.json`.
