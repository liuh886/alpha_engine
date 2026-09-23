# Model and signal refresh recovery — 2026-09-22

All outputs remain research-only and not trade-ready.

## Incident and evidence

Production run [35676542335](https://github.com/liuh886/alpha_engine/actions/runs/35676542335)
completed both governed providers and four strategy jobs. US x1.3 failed with
`canonical US x1.3 target has no governed entry price: EA/2026-09-11`.
Atomic publication correctly rejected the incomplete five-strategy transaction;
no updated formal frontend bundle was published. Repeating the schedule could
not repair the already-sealed invalid target.

The September 11 decision selected EA after its governed terminal listing date.
The selection guard was fixed previously, but did not retroactively correct the
ledger. Original record SHA256:
`4227084d7c301a56ac06733e599b76a9ed0dc59b08fff2f149bc51b5d620976a`.

Signals were not uniformly stopped. Delivery run
[35722512080](https://github.com/liuh886/alpha_engine/actions/runs/35722512080)
reported QQQ and BYD evaluations dated September 21 and CN x1.2 dated September
17 as `not_required`: no changed allocation required an alert. US x1.3 still
referenced its previously delivered September 11 decision. A green delivery
job proves outbox processing, not a fresh model run or a new trading action.

CN27 had a separate activation bug: its maintained contract was unconditionally
reported as blocked. Its workflow also ignored the computed due date and used
the wall-clock date. The contract cadence is **30 market sessions**, not a
calendar month. On September 22 the anchor is September 4 and no decision is due.

## Single operating route

1. Resolve completed exchange sessions and exact active strategy contracts.
2. Refresh and verify market-specific providers; do not fabricate missing prices.
3. Score due targets using the frozen model recipe and seal their decision ledger.
4. Refresh formal evidence, validate the complete transaction, merge the evidence
   revision and verify Pages. Existing atomic publication remains authoritative.
5. Publish operations from the ledger; deliver only eligible changed decisions.
   CN27 now runs after a successful main formal refresh and respects its due flag.

No extra workflow, scheduler, compatibility layer or alternate frontend data
source is introduced. There are still 45 workflows. Heavy refresh does not
watch generated ledgers, avoiding recursive publication runs.

## Correcting an invalid latest decision

`run_ranker_current_target.py correct-lifecycle` is an explicit recovery command,
not an automatic rewriting mechanism. It requires the exact original record
hash, a reason and source identity. It verifies that the original target violates
the governed lifecycle, reconstructs the previous portfolio, recomputes with the
existing scorer, and verifies that the new target excludes terminal listings.

The original `records/<date>.json` and delivery receipts remain byte-identical.
The correction is appended to `corrections/<date>.json`; only the materialized
`latest.json` and manifest advance. Readers validate the correction's binding to
the original bytes. Original receipts cannot mark the correction as delivered.
Normal sealing still rejects conflicting decisions. Repeating the exact
correction is idempotent; a different second correction fails closed.

The correction is explicitly retrospective, carries its actual creation time,
and has `should_alert=false`. It must not be counted as a signal generated on
September 11, nor as prospective performance. Subsequent scheduled decisions
continue from the corrected state at the original cadence.

Reproduction source: production US provider artifact `10673137084`, run
`35676542335`, ZIP SHA256
`3599875f06012aec416be06c2b23069a231300d7d5febb3b95f0f004f720af67`.
It ends on September 21. Scoring explicitly truncates features at September 11;
the existing half-year training cutoff and 10-session label purge are unchanged.
Historical vendor revisions remain a reason to classify this as a correction,
not authentic point-in-time evidence. GitHub artifact retention is finite;
archive the verified provider externally if longer-term byte reproduction is needed.

```bash
uv sync --frozen --extra dev
uv run python scripts/run_ranker_current_target.py correct-lifecycle \
  --market us --provider-dir "$PROVIDER_ROOT/data/providers/us" \
  --expected-record-sha256 4227084d7c301a56ac06733e599b76a9ed0dc59b08fff2f149bc51b5d620976a \
  --reason 'EA terminal listing selected before lifecycle guard; provider run 35676542335' \
  --workflow-run-id recovery-35676542335 --commit-sha "$SOURCE_SHA" \
  --created-at "$CREATED_AT" --output artifacts/recovery/us-corrected-signal.json
```

Use the exact reason and creation metadata in the committed correction when
checking idempotency. Recovery must run before the next decision advances the
ledger; it deliberately cannot rewrite an older decision after that point.

## Verification and remaining boundaries

The corrected target excludes EA with an explicit lifecycle diagnostic. The
previously failing real US preview build now completes through September 21
using the downloaded production provider. Regression coverage checks exact-byte
binding, original delivery retention, duplicate replay, conflicting revisions,
and refusal to issue an actionable retrospective alert.

CN27 activation now means its publisher is available, not that its source is
ready for every future due date. It still requires exact governed positions at
the requested session and fails closed if those are absent. US87/CN130 data-plane
and canonical trainer gaps in the September 20 handover are independent work;
this recovery does not promote their readiness or tune models on new outcomes.

Remote CI, publication and Pages acceptance results are recorded below after
execution; a successful local preview alone does not establish deployment.

### Local acceptance

- 72 targeted ledger, delivery, cadence, operations and forward-projection tests passed.
- Two independent frozen-recipe scoring runs produced identical corrected signals.
- Original decision and delivery files verified byte-for-byte against Git.
- Production provider archive digest verified before replay.
- Real US preview built through 2026-09-21, including retrospective provenance.
- Ruff, strict typing, CI policy and CI governance passed (45 workflows).

The corrective scorer implementation is commit
`54f1d43f246932a74b831ae04e3c08f86c2fb9e7`; the following evidence commit
records its actual run metadata.
