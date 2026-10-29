# Overview: pending reads are not access decisions

Implements the Overview portion of audit [#1315](https://github.com/liuh886/alpha_engine/pull/1315)
P0-7, following the strategy-detail work in #1317.
`research_only=true`, `trade_ready=false`.

Previously, the context bar rendered an unread catalog as a zero-strategy fleet.
The brief could also classify a snapshot as access-denied while membership or
policy verification was still pending. Changing only the badge to “Checking”
left a contradictory sign-in instruction in the row's body.

The context bar now receives the existing bootstrap loading/error state. An
unread catalog says it is being read; a failed catalog says it is unavailable.
Existing verified identities remain visible during a refresh. The page's existing
skeleton has a visible reading message and an accessible status label.

The brief treats pending membership/policy checks and unread operation records
as verification in progress. During that state it shows no sign-in decision,
private reason/date or access/retry action. A verified accessible retained read
continues to show its original date and previous-read explanation while other
records refresh. After verification, real access restrictions and read failures
continue to use the existing access and retry paths. The existing reader timeout,
account-identity invalidation and server authorization are unchanged.

## Verification

Browser plugin not available; used repository Playwright. Flow: delay the formal
catalog → observe loading context without a false zero count → release catalog
while delaying operations → observe pending verification without an access
denial → release operations → show the verified fleet and final read state.

- 13 focused tests passed, including membership/policy/operation pending → real
  restriction transitions, private reason/date redaction and a retained read.
- TypeScript, changed-file ESLint and diff checks passed. The production build
  and full frontend unit suite passed; final counts/checks are in the PR receipt.
- The controlled-delay flow passed on desktop, tablet and mobile. Gates are
  explicitly released, including on failure; no sleeps or provider refresh are
  used. Existing tests continue to cover actual restrictions, timeouts/retry and
  account downgrade behavior.

No new runtime, state store, dependency, route or workflow was added. This closes
the Overview loading-state slice, not Status loading/density or the other audit
items. Original operator workspace WIP remains untouched.
