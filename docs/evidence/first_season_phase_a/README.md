# First-season Phase A acceptance — 2026-10-28

Delivered slice: one explicit US87 pool-index racer, shared benchmark replay,
private retained Q evidence, v2 return-points/window ranks and local Dashboard
role/detail display. This is not six admitted racers, reviewed settlement,
selected-pool/model readiness, historical PIT certification or trading readiness.

## Verification

- 100 relevant Python tests passed, including all 15 new first-season cases and
  existing stack/scoring/pipeline/integrity/researcher-CLI/governance cases.
- 242 frontend unit tests passed; the projection reader has 26 cases.
- Six local HTTP boundary tests passed, including v2 private-Q integrity and
  refusing a JSONL route. Legacy vintages remain readable.
- Full static browser suite: 108 passed. After final label/grammar changes,
  all three first-season desktop/tablet/mobile cases passed again.
- TypeScript, ESLint, Ruff, `git diff --check`, legacy web boundary and CI
  governance passed. The workflow count remains 39, with zero violations.
- Production JS: 381.13 KB gzip against 480 KB budget. No new dependency,
  private Racetrack output directory or synthetic fixture is in public/dist.
- Independent review found and closed a mixed-schema/missing-Q Python reader
  defect. Six hash-valid negative cases now reject wrong versions/rules,
  missing Q, wrong Q identities and wrong tip hashes. Canonical LF output also
  fixes Windows immutable/current manifest hash disagreement.

## Real local source check

```powershell
uv run --frozen alpha racetrack publish --market us --as-of 2026-10-27 --start-date 2024-01-01 --with-pool-runner
uv run --frozen alpha racetrack show --market us --format table
# In qlib-dashboard:
npm run dev -- --host 127.0.0.1
```

The real publication contains one runner and 34 retained monthly Q events.
Matrix identity:
`9a0cf5cd4e2c183907dc1b62f10664bd86dc4f7b5de3dd8a128ba6a58de2fad4`.
Retained Q byte hash:
`0733716571c64ca19e58491458eb6c2e8eafaebb66e22393a1d632187eed3726`.
These are metadata fingerprints, not copied prices, weights or performance.
The complete local immutable manifest retains its code/vintage/source identities.

A rendered local browser smoke read the actual manifest, NAV and Runner detail
(HTTP 200) without mocking a Racetrack endpoint. Only the optional membership
widget was isolated. It verified one dual-role curve/row, 1M/1Y controls,
thesis/ledger explanation, return to the formal monitor and no runtime errors.
The page explicitly reported EA's 59 missing sessions through 2026-10-27.
No lifecycle cause was inferred and no candidate was dropped. Direct JSONL
requests returned 404; Vite `/@fs/` and `?raw` access returned 403.

The actual local projection and real-source screenshot remain local/ignored.
Review screenshots below are explicitly **synthetic fixtures, not investment
results**: [desktop](synthetic-desktop.png), [mobile detail](synthetic-mobile-detail.png).
Browser plugin not available; repository Playwright supplied rendered QA.

## Remaining program work

Formal-derived variants still require frozen holdings/exposure, input evidence
and reconciliation. CN admission remains separate. All months are provisional
and `not_reviewed`; complete calendar coverage alone never seals a season or
closes the source/PIT blockers. See the [v2 contract](../../architecture/racetrack_first_season_v2.md).
