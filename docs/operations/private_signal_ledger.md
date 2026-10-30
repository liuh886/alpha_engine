# Private signal ledger transport and staged cutover

This implements the #1322 follow-up comment of 2026-10-30. It reuses the existing
private repository `liuh886/alpha-engine-data-archive`, scoped read/write deploy
keys, active strategy registry and canonical ledger/checkpoint schemas. There is
no parallel evaluator, registry, database, scheduler or public fallback.

## Authority and ordering

`archives/strategy-signal-ledgers/latest.zip` in private main is a complete
checkpoint of the four active ledger subtrees. Git history preserves preceding
checkpoints. The immutable private Git commit, archive digest/size and registry
digest bind each restored view. A job-local metadata receipt lives outside the
public checkout (`$RUNNER_TEMP/private-ledgers.json`). Nonactive historical model
directories are not migrated or deleted.

1. Restore and validate the private checkpoint before due-date planning or any
   canonical read. Missing credentials, missing/corrupt checkpoint, registry
   mismatch or incomplete state stops the job. During migration, private state
   must also contain every local/public sealed record and receipt, with no date
   regression or conflicting same-date decision; otherwise installation stops.
2. Execute the existing governed operation. No new model execution or source
   refresh occurs just because state was restored.
3. Before publication, compare the expected checkpoint identity with private
   main. Sealed records, corrections and delivery receipts cannot be removed or
   replaced. Validate the actual captured publication bytes against that check.
4. Publish one Git commit with the checkpoint as its only changed member. A
   fast-forward-only push is the CAS. A stale source or concurrent push fails;
   there is no force push, rebase or automatic replay of external side effects.
   Unrelated archive retention can also reject a racing push; restore and rerun.
5. Only after confirmed private persistence may the existing dispatch chain
   continue. The subsequent public-boundary change removes the four producer
   and Outbox Git mirrors, ignores hydrated runtime paths and uploads only
   transport metadata. GitHub Issues remain generic attempt receipts; detailed
   signals remain in private output/ledger files and the authorized Telegram
   channel. Source-generation stdout uses an explicit metadata allowlist.

No-op persistence does not publish a new checkpoint. It authenticates a dry-run
receive-pack request to verify write-key scope without changing strategy state.
A push failure may mean an unconfirmed write; restore authoritative main before
retrying rather than assuming nothing was accepted.

## Consumers

- QQQ, US ranker, CN27 and BYD restore before existing due/build logic and persist
  before handoff. They do not commit hydrated ledger files to public Git. Only
  the last verified private transport identity is retained as a public artifact;
  after a failure that identity is not proof of successful new publication.
- Formal prepare captures one private commit; plan, strategy fan-out and publish
  restore that exact commit. The formal evidence release boundary is unchanged.
- Operations restores before cache lookup. The cache key and success receipt
  bind the private checkpoint digest as well as public code SHA/time window.
- Outbox persists an ambiguity fence before Issue creation or Telegram sending,
  then persists every final delivery outcome before further publication. The
  fence uses an append-only failed receipt with the existing
  `ambiguous_external_delivery_state` error, not a new ledger status. A distinct
  claim run ID preserves receipt immutability. UTC instant ordering (with the
  original run-ID tie break) prevents fractional-second timestamps from choosing
  an older rejection over a newer fence.

If final persistence fails after a message, recovery sees the durable fence and
does not resend. Resolve the external outcome using existing delivery evidence;
do not erase receipts or casually generate a new signal/fingerprint to bypass
the fence. Explicit Telegram API rejection keeps the existing retry rule;
ambiguous transport remains blocked. Public Issue content stays a generic
attempt receipt. Current weights never belong in PRs, logs or reports.

Outbox publication uses an `any_changed` flag accumulated across successful
private writes, so a later no-op cannot suppress an earlier changed/failure
receipt. It no longer depends on a public Git commit. Operations artifacts
contain only the publication receipt; review packet contents remain in the
existing private archive, with just their archive binding uploaded publicly.

MTM's private input still drives the unchanged economic calculation. Future
native lineage exports only a versioned reference and complete private-input
digest, not its raw weights or arbitrary private fields. Already sealed native
files and historical economic traces are not rewritten by this exporter change.

## Bootstrap and non-notifying verification

There is intentionally **no implicit bootstrap** in restore/persist. Initial
publication of this member must use a checkpoint captured from the latest
reviewed public ledger inventory, with exact code, registry and file hashes.
Read it back from an exact private commit, verify byte-for-byte and canonical
reader equivalence, check anonymous denial, and record metadata only. If an old
writer advances public state before cutover, the restore guard blocks; reconcile
that newer evidence into the private checkpoint before proceeding. Do not relax
the guard or silently resurrect public Git as a fallback.

The existing outbox workflow exposes `verify_private_state_only=true` for a
trusted manual branch verification. It restores all four models, verifies a
no-op CAS and scoped write access, then uploads only transport metadata. The
probe never receives Telegram secrets and skips drain, public mirror commits,
Operations materialization/publication and repository dispatch. PR jobs do not
receive the archive secrets.

```powershell
gh workflow run strategy-signal-delivery-outbox.yml --ref <reviewed-branch> -f verify_private_state_only=true
```

This proves the real private transport boundary, not a freshly generated market
decision, Telegram delivery or A4 closure. Four scheduled producers' subsequent
runtime receipts and full Operations publication still need separate acceptance.

## Recovery and remaining gates

Hydration runs before consumers in an isolated job, not as a concurrently readable
filesystem release. It stages verified bytes on the same filesystem and rolls
back installation failures. If rollback also fails, the original subtrees remain
in an explicitly reported `.ledger-backup-*` directory; preserve that job
workspace and restore from the verified private revision. Never publish from a
partially hydrated directory. Never upload the backup/checkpoint itself publicly.

To recover a read-only view, use `alpha ops private-ledgers restore --revision
<exact-private-SHA> --ledger-root <fresh-private-directory> --receipt
<outside-repo-metadata-path>`. Do not move private main backwards or force push
to repair a consumer. Forward corrections use the existing canonical correction
contract, with retained original records and delivery evidence.

Code rollback must not restore an old public-only writer after private main has
advanced. Keep dispatch/delivery stopped for the affected operation until its
private reader/persistence path is repaired; inspect exact manifests and receipts.
All 267 files removed from the four active public subtrees were checked against
private commit `b798c41e593b58474a66bcb83f696d44286a46ce` (489915-byte archive,
SHA-256 `d6b389fba81b1b4832e003d2ae5fbbedfa1dc59ddd5b5fa0dd45b0001d7f1616`).
Existing Git history and nonactive historical model subtrees remain. The active
registry still declares local hydrated paths; those paths are not a public
fallback and may be absent in a clean public checkout.

## Formal result transport

The Formal strategy job retains its complete result directory, including failed
receipts and source inputs, in the same private archive. It does not upload the
directory to public Actions artifacts. The only public transfer is
`<strategy_id>/archive-binding.json`; it contains fixed identities, hashes, size
and the exact private commit/member, never a receipt reason or source payload.

The immutable member is
`archives/formal-strategy-results/<run_id>/attempt-<attempt>/<strategy_id>.zip`.
Bindings require the exact workflow run, code revision, plan bytes, task hash
and active model identity. Restore reads that commit and verifies compressed
size/SHA before bounded extraction. Every required sibling must validate before
the assembled directory appears; the original Formal atomic fan-in then checks
receipt states and preview evidence without changes. Failed receipts remain
failed, and retained/data-blocked evidence keeps its existing degraded semantics.
Missing results, malformed ZIPs, unavailable keys or changed same-member content
stop publication; there is no public artifact or latest-success fallback.

Only the **current attempt** is accepted. Both archive members and public
binding artifact names retain their producing attempt; neither is overwritten.
An older successful or data-blocked binding cannot hide a retry that failed
before uploading new evidence. `Rerun failed jobs` may therefore stop on missing
siblings; recovery requires **Rerun all jobs** or a new normal workflow run.
This conservative boundary avoids a second job-provenance API/state layer. Do
not force expensive research solely for acceptance: use the next eligible run
when replay is not operationally required. A new attempt can retain different
evidence without overwriting the old member.

Four strategy jobs may append different immutable members concurrently. The
existing archive helper freezes each ZIP once, builds a tree from current private
main without checking out unrelated datasets, and uses fast-forward-only pushes.
It retries at most five times only when a rejected push observes a moved remote
head; all sibling changes remain in each new parent. An unchanged remote head
fails immediately. An existing member must have identical bytes. This bounded
append retry **does not apply to mutable signal-ledger CAS**, which continues to
reject stale state and requires explicit authoritative restoration.

Local Git integration tests cover four concurrent writers, exact-byte restore,
same-member conflicts, unchanged-head write denial, sibling ledger updates,
malformed bindings/ZIPs and original fan-in failure/degradation behavior. This
does not establish a real production strategy transfer receipt; that acceptance
requires an eligible strategy run. Do not force retraining or notification to
manufacture transport acceptance.

**Not complete:** production Formal private-transfer acceptance, old public native
MTM material/historical disclosure inventory, post-cutover public-surface
negative proofs, entitled/denied/revoked runtime reads and A0–A7 acceptance. The
four producers, Outbox and Operations ran successfully after #1326/#1327; this
does not certify the remaining surfaces. G0 is incomplete and A4 remains FAIL.
`research_only=true`, `trade_ready=false`.
