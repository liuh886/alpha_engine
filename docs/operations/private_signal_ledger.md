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
5. Only after confirmed private persistence may the temporary public mirror and
   existing dispatch chain continue. This first integration deliberately keeps
   the mirror and other raw artifact paths until a separate removal PR. They
   remain P0 disclosures, not protected backups or a second authority.

No-op persistence does not publish a new checkpoint. It authenticates a dry-run
receive-pack request to verify write-key scope without changing strategy state.
A push failure may mean an unconfirmed write; restore authoritative main before
retrying rather than assuming nothing was accepted.

## Consumers

- QQQ, US ranker, CN27 and BYD restore before existing due/build logic and persist
  before public mirror publication. Mirror staging includes the full restored
  tree, avoiding dirty sibling subtrees if private main is ahead of public main.
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
Normal public-ledger removal is a separate reviewed PR after continuity evidence.

**Not complete:** all four producers' live continuity receipts, public Git/raw
artifact removal, historical disclosure inventory, four-surface anonymous
negatives, entitled/denied/revoked runtime reads and A0–A7 acceptance. G0 is
incomplete and A4 remains FAIL. `research_only=true`, `trade_ready=false`.
