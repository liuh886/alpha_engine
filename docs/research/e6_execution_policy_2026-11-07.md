# E6 execution policy implementation and acceptance

Continuation of #1381 / #1380. This is a scoped zero-fit execution experiment;
no Colab, provider refresh, new model search, strategy registration, scheduler,
database, broker or frontend path is added. Original E4/v6/E5 evidence stays
immutable. The E5 main archive and raw v6 provider archive are reused by hash.

Authority: [pre-result frozen contract](../../configs/research_experiments/e6_us73_execution_policy_v1.json),
[actual results](e6_us73_execution_results_2026-11-07.md), and
[independent acceptance](../evidence/e6_us73_execution_2026-11-07/README.md).

The contract was committed as `e02b58b486` before the first E6 replay. SHA256:
`1a034d711b6b8e6fd4cb5bb8a0877e769c68d05e585450585984ccfefe964424`.
Primary forward design `weekly_min5_buffer10_asc` was chosen before E6 results,
not selected as a historical winner. All seven named arms use the same four
E4 strategies, eight folds, one-session delay, Top5, 8bps, calendar and fold-end
liquidation convention. These are 224 post-fit evaluations, not 224 new models
or independent financial samples.

## Canonical engine and deterministic policy

An optional selection callback on `_simulate_portfolio` chooses target weights;
the existing engine alone computes returns, drift, turnover, friction and
liquidation. The callback must return a finite long-only fully invested TopK
vector. Without it E4/E5 behavior remains unchanged, including original ties.

`execution_selection` orders by descending score then a declared deterministic
symbol key: ascending (primary), descending or salted SHA256 (sensitivity).
Ranking is invariant to source column order. No best-return tie rule is chosen.

Weekly means the first actual exchange session of each ISO week, including
holiday weeks. A five-session minimum counts from entry and is not reset by
resizing. Rank buffer retains incumbents through rank10. Non-rebalance days
carry drifted weights exactly. Minimum-hold/buffer-only arms also carry drift
when membership is unchanged; weekly scheduled rebalances restore equal
weights. Initial anchor entry and forced fold-end exit remain explicit.

## Capacity admission screen, not invented fills

73 source-bound raw Close/Volume pairs are reconstructed from the exact v6
provider archive; Volume must equal E5's series. Adjusted close is reconciled
to E5 within CSV float precision. Capacity uses raw Close×Volume, avoiding the
additional dividend adjustment in research prices. It is a dollar-volume
proxy, not VWAP or exact traded dollar value.

The20-session mean ends strictly before the fill date. Each entry/rebalance/
forced-exit leg receives a capital ceiling based on1% participation, its trade
weight and simulated NAV. USD1m/10m are explicit hypothetical starting-capital
scenarios, not account balances. Past20-session volatility is attached to each
leg to inspect high-volatility/low-capacity names. Screen breaches reject a
capacity claim; there is no fabricated partial-fill or impact model.

Actual execution capacity remains BLOCKED: historical as-traded volume units,
vendor first-available vintages, spread/impact and actual fills are unverified.
The original frames were observed2026-11-06; that observation cannot be
backdated to their historical trading dates. Policy return tables remain
price-proxy research and are not certified capacity-constrained fill returns.

## Maintained commands

Run `uv run --frozen python -m src.research.e6_execution --help` with
`--contract`, exact `--e5-package`, exact `--raw-source`, and a new private
`--output`. Optional `--arm/--strategy/--fold` create an explicitly PARTIAL
vertical slice. Only a complete224-result matrix produces a comparison.
Each result must first reproduce the source E5 delayed control.

Run `uv run --frozen python -m src.research.e6_report --help` with the frozen
contract, complete `--run-root`, registered `--forward-root` and fresh private
`--output`. It validates result identities/hashes and evaluator consistency,
then emits the fixed paired screens and all arms without choosing a winner.

## Forward workflow, intentionally not started

`uv run --frozen python -m src.research.e6_forward --help` exposes only
owner-operated `register`, `bind-model`, `prediction`, `market`, `outcome`,
`evaluate`, `status`. Persistence reuses StudyWorkspace atomic exclusive
receipts in one private experiment namespace; this is not a strategy registry.

An actual empty registration was sealed before the first future session,
2026-11-09. Predictions must be observed after signal-session close and before
the next session opens. Generated-at timestamps cannot excuse late submission.
Pool, contract and model identities are fixed; modified receipts cannot replace
retained evidence. Market packets require a fixed adjustment-basis identifier,
source hash, post-close availability and an action-adjustment evidence hash.
These are source-receipt bindings, not independent corporate-action/PIT proof.

Five-session labels can be recorded only after maturity. Continuous forward
paper evaluation uses the same engine and fixed primary policy and does not
force terminal liquidation at each read. There is no automatic refresh or fit.
The local first-seen clock is not an independently attested timestamp service.

The existing tree model binaries were not archived. They remain missing,
not fabricated or refit in E6. `bind-model` requires the exact previously frozen
recipe/training-input receipts plus actual binary hash before the first forward
market session. Capturing model research would need separate explicit work;
this negative historical result does not authorize it. Incomplete capacity,
action-bridge or source evidence never becomes actual-fill certification.

## Observed disposition

All224 comparisons and224 independent arithmetic/policy/capacity audits PASS;
model fits0. The fresh offline replay of primary XGB p03/2026H2 reproduces
the packaged NAV/risk and capacity summaries. Original E4/v6/E5 archive hashes
were independently re-read unchanged.

Neither model passes the predeclared historical screen in any arm. Primary
p03 turnover falls79.2%, yet paired medians vs60d/120d momentum are-2.55/-2.98pp,
with turnover still1.91x/2.55x the matched baselines. Primary LGB is-4.01/-2.85pp.
P03's daily tie sensitivity reaches23.00pp for a single fold. Keep this failure
memory; do not revise thresholds or choose a more profitable tie rule.

Technical implementation PASS; historical ML premium NOT_SUPPORTED; actual
capacity BLOCKED; forward NOT_STARTED with two missing model artifacts. No
PIT, independent holdout, model promotion or trading-readiness acceptance.

Private local delivery: `D:/Documents/AlphaEnginePrivate/P2-E6/2026-11-07/delivery/`.
Four files written/read back under
`AlphaEngine/03_Data/Research_Exchange_P2/incoming_unreviewed/e6-us73-execution-v1-fe4c551062/`.
Main ZIP SHA256
`2f09756d3eb14142c9a047dd48072d4bfd76eb24df13f08aaad07b57beab350e`;
manifest SHA256
`863753a650200fb5064c4d87274cb41e0700169e76b66d88457210ff999bcd8f`.
Remote Drive synchronization/ACL and source-rights approvals were not
recertified or automatically enabled.
