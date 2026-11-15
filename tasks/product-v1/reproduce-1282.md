# #1282 — reproduce the accepted QQQ and CN_27 references on current main

Receipt: `docs/evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json`
Final main: `c6530f019de010de887cda52863d63763f943227` (PR #1446)
Audit started at: `2b262fd2571c9316481080dbf1b72fe7ee92681a`
Branch: `docs/reproduce-local-reference-1282-20261115`

## Purpose

A fresh bounded current-lock/source/evaluator re-audit of one accepted US
reference (`qqq_v4_3`, model `qqqi_qqq_tqqq_v4_3`) and one accepted CN reference
(`cn_27_v1_3`) using the maintained `formal_model_replay` runner and pinned local
evidence. This is an evidence/acceptance task, not training, promotion or
prospective validation.

## Environment

- Pinned interpreter: `D:/Documents/GitHub/alpha_engine/.venv/Scripts/python.exe`,
  Python 3.12.12, yfinance 1.2.0 (matches `uv.lock`), uv 0.9.10, Windows 11.
- `uv.lock` sha256 `fbb69c23…11cc3`; `pyproject.toml` sha256 `bfe1d244…61ea6`.
  No lockfile was modified.
- Worktree root is also the governed data root. The worktree is a `blob:none`
  partial clone, so the gitignored CN source CSV was copied byte-identically
  (same sha256) from the main checkout into the worktree path the replay
  resolves. This is staging, not substitution.
- The first US attempt was accidentally run with the conda interpreter
  `D:/miniforge3/python.exe` (yfinance 1.0, not the locked 1.2.0). Every later
  attempt and all final repetitions used the project venv.

## Commands (3 repetitions each for the final runs)

```
D:/Documents/GitHub/alpha_engine/.venv/Scripts/python.exe -m src.cli.main --root . research replay cn_27_v1_3
D:/Documents/GitHub/alpha_engine/.venv/Scripts/python.exe -m src.cli.main --root . research replay qqq_v4_3
```

## Full honest sequence

1. **Initial US attempt** — 2026-11-15T19:32:45+08:00, conda yfinance 1.0.
   `data_blocked`; verbatim `strategy data bundle is blocked: missing=['^VIX', '^VXN']`.
   Three identical receipts `f110274c…8452db`, exit 2.
2. **Provider recovery** — project venv yfinance 1.2.0 returned `^VIX` 717 rows
   and `^VXN` 702 rows through 2026-11-13; the session filter then matched the
   accepted lineage exactly (`^VIX` 4258→4243, `^VXN` 4243).
3. **Retry before fix** — 2026-11-15T19:44:12+08:00. `invalid_evidence`; the
   accepted `portfolio.json` positions still held the pre-correction
   `executed_reason` on 2026-01-21 and 2026-03-03 while `performance.json` had
   the corrected labels. Three identical receipts `3df0906a…df647d`, exit 2.
4. **Fix #1446 landed** — commit `c6530f019d`. The correction tool now applies
   each `executed_reason` correction to the same-date positions, re-seals both
   roots and records `positions_corrections` in lineage. Re-sealed bundle
   `2ad7a25a…ef8f2`, manifest `a6435828…cea33`; report and positions are
   consistent; derived excess unchanged.
5. **Final replays** — CN at 2026-11-15T22:23:20+08:00 and US at
   2026-11-15T22:23:44+08:00, both **`exact_replay`**, three identical receipts
   each.

## Final results

### CN_27 V1.3 — exact replay

- Bundle `4e01ca1f…08528`, manifest `5e5b0598…5f737`,
  run `cn_27_v1_3-through-2026_11_13`, record cutoff `2026-11-13`.
- Frozen source/trace boundary `2026-09-04` (source CSV sha256 `1e7713e8…6e35`,
  23,524 rows). The append-only lineage refresh advanced the record cutoff
  without extending the frozen trace; the replay reproduces the frozen trace.
- Predeclared tolerance: numeric rows `abs_tol=1e-6`; non-numeric exact; row
  counts exact; bars must end at the trace boundary. All sections match (max
  observed drift `7.353e-10`); not byte-equal at `1e-12` (expected BLAS noise).
- Repetition hash: `ed63040d…a5f43f` (3×, exit 0).

### US QQQ v4.3 — exact replay (after #1446)

- Bundle `2ad7a25a…ef8f2`, manifest `a6435828…cea33`,
  run `qqqi_qqq_tqqq_v4_3-through-2026_11_13`, cutoff `2026-11-13`, accepted
  trace boundary `2026-11-12`.
- Predeclared tolerance: numeric rows `abs_tol=1e-12`; text exact;
  `portfolio_contract` exact. Frozen economic prefix, current-source decision
  path and the zero-row appended/continuity stages are all exact with maximum
  absolute difference `0.0`.
  - frozen prefix: report 701, positions 1042, trades 134 — exact
  - decision path: report 701, positions 1042, trades 134 — exact
  - appended economics / cumulative continuity: 0 rows, not applicable
- Source identity: strategy product manifest `48cc3bb3…64acd`, strategy data
  manifest `8631ed20…0001`, ETF bundle `5647603e…ac07`, coverage
  `7dec8103…7673`, reconciliation `b91c7040…ef935`; session filter matches the
  accepted lineage. Historical economics remain the accepted prefix.
- Repetition hash: `5270d94c…25866` (3×, exit 0).

## Caveats

The US retry's source assembly depends on live yfinance availability; the initial
block was environment-sensitive (conda yfinance 1.0 vs the locked 1.2.0). The
frozen accepted bundle is now internally consistent and replays exactly, but the
provider vintage is not claimed to be reproducible or pinned.

## What this does not claim

Prospective validation; a new model or training run; owner A5 acceptance; A7
approval; promotion or trade readiness; a reproducible provider vintage;
byte-equal CN values at machine precision.

## Validation

- `tests/test_formal_model_replay.py` + `tests/test_cn27_v1_3_refresh.py`:
  29 passed.
- `tests/test_rules_formal_replay_gate.py` + `tests/test_cn27_v1_3_projected.py`:
  22 passed.
- Total: 51 passed. No Python files changed; Ruff is not applicable to the
  JSON/Markdown deliverable.

Owner A5 acceptance remains pending, so Issue #1282 stays open.
