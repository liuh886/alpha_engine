# CN130 provider-snapshot drift attribution

**Issue:** #345  
**Decision:** `unexplained_provider_drift_blocking`  
**Research boundary:** `research_only=true`, `trade_ready=false`

## Executive conclusion

The two observed CN130 results are both valid only for their exact provider snapshots. The available Actions artifacts do not contain enough evidence to classify the difference as append-only, a legitimate historical adjustment revision, or pipeline nondeterminism.

Further CN factor or parameter search remains blocked. Neither +20.1818% nor +13.2736% may be described as snapshot-independent performance, and neither historical result is automatically restated.

## Compared evidence

| Field | PR #289 snapshot | PR #344 snapshot |
|---|---|---|
| Workflow run | `30707914152` | `30733728747` |
| Artifact | `8820979579` | `8828889722` |
| Cutoff | 2026-06-18 | 2026-07-31 |
| Provider identity | `83f5251f...7779f2` | `bf5fa137...05d8` |
| Calendar sessions | 1,321 | 1,351 |
| Selected source | AkShare/Sina for all 131 files | AkShare/Sina for all 131 files |

The exact XGBoost candidate is unchanged:

```text
xgb:daily_ranker:cn_balanced_ohlcv:gain5_round100_leaves31_leaf10_lr0.05/xgb_rank_ndcg/original
```

Its four-window development evidence changed as follows:

| Metric | Old snapshot | New snapshot | Difference |
|---|---:|---:|---:|
| Compounded strategy return | 68.60% | 58.91% | -9.69 pp |
| CSI 300 return | 40.29% | 40.29% | 0.00 pp |
| Compounded relative excess | 20.18% | 13.27% | -6.91 pp |
| Worst drawdown | -16.12% | -19.10% | -2.98 pp |

## What the manifests prove

The comparison establishes all of the following:

- identical market and selected-pool identity;
- identical 131-symbol file set;
- identical selected provider and provider symbol for every file;
- identical first date for every file;
- identical committed pre-refresh inventory;
- exactly 30 additional rows in every refreshed source file;
- a different full-file SHA-256 for every source file;
- the benchmark return is unchanged while candidate returns and selections change.

## What the artifacts do not prove

Neither artifact retains the source CSV bytes, Qlib binary fields, overlapping-bar digests, adjustment factors or a historical-prefix hash through 2026-06-18.

A full-file hash must change when 30 sessions are appended. Therefore, the 131 changed full-file hashes cannot distinguish among:

1. a pure append with byte-identical historical prefixes;
2. qfq historical-price revisions caused by later corporate actions;
3. upstream corrections;
4. calendar or normalization changes;
5. nondeterministic rebuilding.

The source contract declares `qfq_adjusted`, so historical revision is plausible, but it is not proven by the retained evidence.

## Governance fix

This PR adds a reusable snapshot-comparison command and a provider-snapshot policy.

Future selected-pool builds must retain historical-prefix SHA-256 values at the older snapshot cutoff. An `append_only_reproducible` claim is allowed only when every overlapping prefix hash matches. Changed prefixes require exact bar-level diff and corporate-action attribution.

Every frozen experiment must bind:

- provider snapshot identity;
- cutoff;
- source inventory;
- calendar and feature hashes;
- pool/reference identities.

A refresh creates a new evidence revision. It does not overwrite the prior run and is not adopted automatically by a frozen model.

## Final decision

`unexplained_provider_drift_blocking`

The two snapshots are now preserved as distinct evidence identities. CN model search may resume only after a future comparison supplies prefix-complete or raw-bar evidence and reaches one of the non-blocking decisions defined in `provider_snapshot_policy_v1`.
