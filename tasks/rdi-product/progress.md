# Progress

- Cloud Phase 2 merge preview: Ruff passed, 20 RDI tests passed, governance zero violations.
- Synced main, clean and zero divergence before product development.
- Browser plugin/skill unavailable; use repository Playwright for rendered validation.
- Initial projection found raw CSV absent in sparse checkout. Resolve source identity
  from Git tree; inspect raw bytes only if present. No blob download needed. Source
  links now bind to an immutable repository commit instead of moving main.
- Backend RDI tests: 29 pass, Ruff pass. Initial frontend check caught ES2020
  replaceAll incompatibility and jsdom URL fixture resolution; replaced with
  compatible regex and filesystem path, respectively.
- Final review replaced generated-data UI fixtures with explicitly synthetic
  contract values. Unit tests now run independently of optional RDI asset
  generation; Python and browser tests verify the real source projection.
- Complete frontend build: 208 tests pass; TypeScript, ESLint and bundle budget
  pass (316.18 KB gzipped JS against 480 KB ceiling).
- Browser acceptance: 9 tests pass across desktop/tablet/mobile for RDI retry,
  history disclosure and independent operating observations. Screenshot framing
  improved and 3 RDI browser checks rerun successfully. Screenshots live in OS temp.
- Pages publication dependency tests: 14 pass. Existing frontend/Pages workflows
  recognize RDI inputs; no new workflow. Governance: zero violations, 39 workflows.
- Desktop and mobile screenshots inspected: readable card and table, no horizontal
  overflow or framework overlay. No uncaught browser errors. Expected first-read
  503 is injected solely to exercise recovery.

## Frontend design and delegation

- User explicitly requested PM design plus frontend-agent implementation.
- PM froze the inline workspace design in the existing architecture charter;
  delegated scoped components and related tests to `/root/rdi_frontend` using
  the agency Frontend Developer role. Backend/schema/workflow scope is unchanged.
- PM independently checked archived comparison values and two-decimal detail
  precision; one-decimal rounding would make the 14-session difference look
  inconsistent (17.2 - 12.0 vs raw +5.3pp).
- Frontend agent delivered three scoped components, 18 focused unit tests and
  adapted RDI browser acceptance. Full frontend build: 211 tests passed,
  TypeScript/full ESLint passed, JS 317.88 KB gzip against 480 KB ceiling.
- Nine desktop/tablet/mobile browser checks passed: entry focus, independent RDI
  retry, unchanged strategy reads, keyboard horizons, source filter, immutable
  links and parent refresh. PM independent 1440px/360px light/dark pass checked
  actual bar geometry against percentages, all horizon values, no overflow,
  one RDI read for all local interactions, no page/console errors.
- Screenshot review found desktop in-page jump also scrolled window by 100px,
  hiding the topbar despite correct focus. Reopened frontend agent task to
  constrain scrolling to the existing desktop/mobile content container and
  add an explicit header/window-position acceptance assertion.
- Frontend agent fixed container-owned jump scrolling; root reverified
  windowY=0/topbar.top=0 on desktop and mobile, plus all three device browser cases.
- Narrow-screen screenshot review also found wrapped group labels offset the two
  frequencies by 16px. Agent aligned label heights on narrow screens. Final DOM
  checks confirm frequency and sample-count baselines differ by <1px, bar lengths
  match values within 0.2 percentage points, no horizontal overflow, and zero
  page/console errors across desktop plus 360px light/dark. Three RDI browser
  checks rerun after the final fix passed. Full checks were not redundantly repeated.
