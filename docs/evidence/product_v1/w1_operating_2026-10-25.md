# W1 / #1277 — real operating evidence audit

**BLOCKED / insufficient evidence**, main `58a56c14c`, through completed market
session 2026-10-23. Research only; trade ready false. This is not release approval.

The [source-bound ledger](w1_operating_2026-10-25.json) accounts for the last
20 exchange sessions separately for US/XNYS and CN/XSHG. The current private
archive contains 211 captures for 27 distinct formal run/attempts, selected by
latest capture per attempt, without a previous-green fallback. Git blob/size,
archive SHA-256 and every indexed member hash/size were verified. Both markets
have observations on only **7 of 20** sessions; **0 independently qualified**.
Unknown manual interventions remain null. Earlier five-strategy observations
are retained and cannot silently qualify today's four-strategy fleet.

The current accepted identities/cadences are read from the registry: QQQ v4.3
daily US; US x1.3 every 10 provider sessions; CN_27 v1.3 every 30 completed CN
sessions; BYD v1.3 daily CN. A not-due evaluation is valid when its frozen
contract and exact evidence prove it. No daily rebalance was required here.
CN_27 actual due-cycle proof remains unqualified; synthetic tests do not fill it.

Latest attempt [40169478271:1](https://github.com/liuh886/alpha_engine/actions/runs/40169478271)
has provider cutoffs 2026-10-23 for both markets. Its four strategy checks
mechanically verify, but publication failed, so the whole observation stays
blocked. The latest-main comparison reports `semantic_no_change`; the shell
then reads boolean false via `jq -e`, whose exit code is 1, before reaching the
existing no-change branch. No success or recovery is inferred from the earlier
successful attempt or already-merged data PR #1280. Fix this observed defect
separately; retain this immutable failure record.

## Repeat the existing checks

```powershell
uv run --frozen alpha ops acceptance --collect-repository liuh886/alpha_engine --input-root artifacts/product-v1-1277/latest --through 2026-10-23 --output artifacts/product-v1-1277/latest/acceptance-report.json
uv run --frozen python -m pytest tests/test_operating_acceptance.py -q
gh api repos/liuh886/alpha-engine-data-archive/git/trees/main
```

The archive requires authorized private repository access. Follow the `archives`
tree identity and exact selected blob hashes retained in the ledger to inspect
the same packets. Existing `build_acceptance_report` remains the acceptance
authority; no review declarations were fabricated. Private decisions/targets
and raw packets remain in the existing private store/local ignored artifacts.

| Check | Result |
| --- | --- |
| Archive identity and indexed members | PASS |
| Existing negative/cadence/duplicate/holiday tests | PASS: 16 |
| Last 20 sessions explicitly accounted for per market | PASS (includes missing) |
| 20 real independently qualified sessions | BLOCKED: 0 |
| Independently confirmed manual intervention counts | BLOCKED |
| Actual CN_27 due cycle and incident recovery | NOT_TESTED |

Next: independently review exact packets and intervention counts, accumulate
missing real sessions through existing workflows, repair the observed no-change
publication failure under a separate issue, and demonstrate actual recovery.
No workflow, strategy, sealed decision or source data changed. Reverting this
evidence-only PR removes this audit projection without changing original packets.
