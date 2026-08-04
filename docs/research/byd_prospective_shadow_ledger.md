# BYD prospective shadow ledger protocol

Historical BYD model exploration stops with canonical V1.0 as the retained baseline. V1.2 and V1.3 were rejected under their frozen gates. This protocol records new evidence without changing those decisions or re-optimizing the same history.

## Data versioning

The immutable canonical v1 snapshot ends on 2026-08-03. Each later observation is chain-linked to that adjusted-price anchor and records the complete provider-response identities used to create it.

A daily observation may append a new date but may never replace:

- an immutable canonical v1 row;
- a previously written prospective signal record;
- a previously matured forward-outcome record.

An independent unadjusted source confirms each new raw row. A disputed or zero-volume open is preserved as evidence but is not eligible for signal execution or forward-label timing.

## Signal content

Every post-close observation stores:

- canonical V1.0 base target;
- rejected V1.3 shadow target and active branch;
- long drawdown, recovery, momentum-transition and open-structure factors;
- market and volatility states;
- data availability timestamp, data-version identifier and content hashes.

These are shadow observations only. They are not orders and cannot alter the retained V1.0 model.

## Outcome content

Once sufficient independently eligible opens exist, immutable 5-, 10- and 20-open outcome records compare the shadow path with canonical V1.0 at the frozen cost convention. The derived CSV ledger may be rebuilt, but its source JSON records are append-only.

## Research threshold

No new BYD model contract may be proposed until the ledger contains at least twelve months, ten completed recovery events and the event/state concentration evidence required by Issue #518. If the evidence is sparse, the observation window is extended rather than the gates relaxed.
