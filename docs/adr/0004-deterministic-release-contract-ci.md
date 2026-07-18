# ADR-0004: Deterministic Release-Contract CI

## Status

Accepted

## Date

2026-07-16

## Context

Pull requests and pushes previously exercised different release checks. A pull
request could pass while `main` failed on a canonical 10D return fixture or a
date-sensitive model-registry fixture. One API contract test also executed the
real background research workflow under `TestClient`, which made the fast lane
slow and mutated a tracked workflow configuration.

This decision maps to Phase 3 governance and Phase 4 integration: release
evidence contracts must fail before merge without turning the pull-request lane
into a real-data research run.

## Decision

- The deterministic release-contract pytest suite MUST run for pull requests,
  pushes to `main`, and manual CI runs.
- Tests MUST satisfy canonical data contracts, including raw 10D return
  provenance and horizon metadata. Production gates MUST NOT be weakened to
  accommodate incomplete fixtures.
- API contract tests MUST inject workflow implementations at the workflow seam;
  they MUST NOT launch real training, mutate tracked configuration, or depend on
  market data.
- Time-sensitive frontend fixtures MUST express whether a model is intentionally
  current or stale. A current release model MUST use a run-relative timestamp.
- Full browser and real-data validation remain higher-level gates. Pull requests
  keep deterministic unit and contract coverage rather than duplicating every
  expensive post-merge check.
- Filesystem assertions MUST be portable across supported developer and CI
  platforms.

## Consequences

- The same backend release correctness is checked before and after merge.
- The pull-request lane remains independent of notebooks, live providers, and
  full backtests.
- Exact release identity and staleness behavior are covered by fast frontend
  tests, while the production release journey remains covered by Playwright.
- Fast tests are repeatable and leave the repository unchanged.
