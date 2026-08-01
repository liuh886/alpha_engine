# Market-Data Git History Cleanup Plan

Date: 2026-08-01
Status: gated — do not execute before CN selected pool v3 is merged

## Objective

Remove historical market-data blobs from the source repository after the selected US/CN memberships are frozen, while retaining reproducibility through manifests, source identities, hashes and acquisition scripts.

## Why this is separate

Deleting CSV files from the current branch reduces the working tree but does not remove their blobs from Git history. A history rewrite changes commit identities, affects every branch and tag, and requires all local clones to be replaced or carefully reset.

## Preconditions

- `us_selected_equities_v2` remains frozen.
- `cn_selected_equities_v3` is approved and merged.
- No open PR depends on old data-file commits.
- A full mirror backup and `git bundle` are created and verified.
- Current selected data are exported to an external immutable artifact with checksums.
- Repository collaborators acknowledge the required re-clone/reset procedure.

## Target architecture

Keep in Git:

- selected-pool YAML contracts;
- provider/source configuration;
- acquisition and validation code;
- coverage reports and compact manifests;
- SHA-256 identities and dataset version metadata;
- tiny deterministic test fixtures only.

Move outside Git:

- `data/csv_clean/**` market histories;
- generated Qlib binaries and feature stores;
- provider snapshots and repeated materialisations;
- large research outputs that can be regenerated.

Recommended storage order:

1. object storage or versioned dataset release;
2. GitHub Release assets for bounded snapshots;
3. Git LFS only when external object storage is unavailable.

## Rewrite procedure

1. Freeze repository writes and record the current `main` SHA.
2. Create and verify:
   - bare mirror clone;
   - `git bundle --all` backup;
   - external selected-data snapshot and checksum manifest.
3. Use `git filter-repo`, not `filter-branch`, to purge approved paths from all branches and tags.
4. Re-add only compact manifests, download instructions and test fixtures in the rewritten tip.
5. Run repository tests against a fresh clone of the rewritten repository.
6. Force-push rewritten branches and approved tags with explicit expected SHAs.
7. Delete obsolete remote branches and tags that retain large blobs.
8. Ask all collaborators and automation runners to re-clone; old clones must not push.
9. Verify repository object size after GitHub garbage collection.

## Initial purge candidates

Subject to a final path audit:

- `data/csv_clean/**`
- `data/qlib_data/**`
- `data/providers/**` generated market datasets
- `data/snapshots/**`
- other generated market-data copies discovered by object-size analysis

Exceptions must be allowlisted explicitly, especially compact instrument manifests and test fixtures.

## Verification gates

- selected-pool files resolve correctly in a fresh clone;
- dataset downloader reconstructs the expected selected membership;
- manifest hashes match the external snapshot;
- no authoritative experiment can silently fall back to missing broad data;
- `git count-objects -vH` and largest-object reports show the expected reduction;
- CI passes from a clean checkout.

## Rollback

The mirror and bundle remain read-only until the rewritten repository has passed CI and at least one clean-clone reproduction. Rollback means restoring refs from the verified mirror, not attempting an in-place reverse rewrite.
