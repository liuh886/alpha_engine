# W1b–W2 / #1279 — four-strategy UAT and privacy audit

**A3 partial / BLOCKED; A4 FAIL (observed static boundary defect #1288).** Published build
`58a56c14c18197f700ab00b526513a571aff35be`, deployment run
[40170378446](https://github.com/liuh886/alpha_engine/actions/runs/40170378446),
formal cutoff 2026-10-23. No runtime, RLS or policy changes.

The flow tested is Overview → actual strategy link → risk/trade evidence →
linked historical instrument → 1M range control → Operating Status. All four
accepted strategies passed on 1440×1000 desktop and 390×844 mobile: **8/8**
real anonymous published journeys, zero page exceptions, overlays or horizontal
overflow. Prices and markers stayed tied to formal identities; historical events
did not claim actual fills. Missing retained excess metrics remained unavailable.
The [matrix/receipt](w2_uat_privacy_2026-10-25.json) records expected stage,
observed URL, identity, outcome and screenshot/trace hashes. Representative
[desktop risk](w2-desktop-qqq_rotation-risk.png) and
[mobile instrument](w2-mobile-cn_27-instrument.png) captures were visually reviewed.

Existing live acceptance passed on desktop/mobile over all four formal models.
Existing fixture acceptance passed **60** tests across desktop/tablet/mobile,
covering shared changed observations, stale/retry, wrong formal identity,
undeclared policy, account downgrade/late responses and read recovery. Those
are deterministic mechanisms, not real entitled-user or 20-session evidence.
Production build and 216 frontend unit tests passed.

## Actual privacy boundary observed

The existing release verifier passed all **36** formal sections and the live
static public-operation shell, but that is insufficient privacy coverage.
An additional anonymous section scan confirmed the published CN_27 lineage
contains `source_evidence.operating_state` dated 2026-10-23 with 13 current-weight
entries, target weights and factor evidence. The exact path and response hash,
without weight values, are recorded in the receipt and
[#1288](https://github.com/liuh886/alpha_engine/issues/1288). This contradicts
the promised public-history/current-operations separation. **A4 FAIL.**
The copy pipeline publishes complete immutable bundles, whereas its public-shell
checker only protects the operations snapshot. Fix requires owner-reviewed
publication/integrity design; do not patch sealed lineages or remove RLS.

Direct read of the real Supabase resource
`strategy_operation_snapshots` returned HTTP 200 to the publishable-key anonymous
client. Its five rows correspond to policies currently declaring **public**
access, including a retained `cn_x` row; the browser fleet remains exactly four.
This is policy-authorized access, not proof of unauthorized Pro disclosure.
It also cannot certify the proposed protected-current-data acceptance criterion:
there was no Pro-protected active strategy resource to test anonymously.
An invalid bearer token returned HTTP 401. Public policy rows and response hashes
are recorded; allocations, targets, bearer tokens and private payloads are omitted.

Owner must confirm intended current-operation access before A4 can pass. Real
member/Pro/owner sessions, JWT expiry, entitlement revocation and their negative
reads remain **NOT_TESTED**. No policy write or test-account mutation was made.
No speculative UI redesign or policy write was made. The confirmed static
defect is tracked separately; implementation awaits the required owner review.

## Reproduction and limits

```powershell
$env:PAGE_URL = 'https://liuh886.github.io/alpha_engine/'
cd qlib-dashboard
npx playwright test --config=playwright.live.config.ts --trace on
npx playwright test --config=playwright.static.config.ts e2e/strategy-operations.spec.ts e2e/security-history.spec.ts --trace on
```

Browser plugin not available; regular Playwright used. Full local screenshots,
journey script and traces remain at the raw-artifact location in the receipt;
only representative historical screenshots are committed. A durable shared
artifact for every required account/scenario is not claimed. Initial custom
locator and invalid-column setup errors were corrected before results were
classified. They were not product defects or evidence of data leakage.

Remaining work: capture actual changed/not-due/blocked samples per strategy and
device, review intended live policies with the owner, test supplied authorized
accounts including expiry/revocation, retain reviewed traces through the existing
evidence path. Reverting this audit removes only derived review artifacts.
