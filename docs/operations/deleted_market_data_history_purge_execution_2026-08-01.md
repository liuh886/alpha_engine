# Deleted Market-Data History Purge — Execution Contract

Date: 2026-08-01  
Decision sources: Issues #263, #269 and #270

## Approved scope

This operation removes exactly 138 obsolete CSV paths from every reachable branch and tag:

- 46 first-round US removals;
- 58 first-round CN removals;
- 33 second-round CN removals;
- the invalid orphan `ALBA.csv`.

The authoritative path list is `configs/data_quality/history_purge_paths_v1.txt`.

This first history-cleanup phase deliberately preserves current selected-pool data. It does not remove all of `data/csv_clean`, `data/qlib_data`, or provider materialisations because AlphaEngine still depends on current selected data. A full market-data externalisation must be a later migration with a durable downloader, checksum manifest and storage destination.

## Safety sequence

The one-shot workflow:

1. refuses to run if any pull request remains open;
2. validates all 138 paths against a strict `data/csv_clean/<symbol>.csv` pattern;
3. creates a mirror clone and `git bundle --all` recovery backup;
4. uploads that backup before any ref is rewritten;
5. uses `git filter-repo` to remove each approved path from all branches and tags;
6. verifies no approved path is reachable in the rewritten mirror;
7. force-updates and prunes remote heads and tags;
8. verifies the result from a new mirror clone;
9. publishes the pre-rewrite bundle and audits as a release asset whose tag points to rewritten history;
10. records completion in Issue #270.

## Collaboration impact

All pre-rewrite commit IDs become obsolete. Existing local clones must be discarded and cloned again. Pushing from an old clone after the rewrite is prohibited because it can reintroduce removed objects and refs.

GitHub server-side garbage collection is asynchronous. Successful fresh-clone verification means the paths are no longer reachable even if the repository-size number does not fall immediately.
