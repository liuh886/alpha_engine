# Prospective Shadow Decision Runbook

Status: research-only operational workflow  
Cutover contract: `configs/operations/prospective_shadow_cutover_v1.yaml`

## Purpose

This workflow starts forward, timestamped, immutable decision records for manual review. It does not validate a strategy, send orders, or authorize live trading.

Reading July 2026 market data means the former 2026H2 untouched-validation plan for existing strategy families is no longer available. The cutover contract records that change explicitly. Any future low-turnover multi-factor candidate must declare a new independent window after its factors and rules are frozen.

## Prerequisites

1. Refresh a long-form prices CSV through the intended as-of trading date.
2. Confirm the CSV contains `date,symbol,open,high,low,close` and the full frozen pool plus references.
3. Initialize and backfill FactorRegistry v2.
4. Use the frozen market spec declared in the cutover contract.
5. For China, do not run until Issue #223 provides the live point-in-time tradability data path.

## Initialize the factor ledger

```bash
uv run python scripts/migrate_factor_knowledge_registry.py \
  --db artifacts/factor_registry.db \
  --report artifacts/factor_knowledge/migration_report.json

uv run python scripts/backfill_factor_history_batch1.py \
  --db artifacts/factor_registry.db \
  --report artifacts/factor_knowledge/history_batch1.json
```

## Run one US shadow cycle

```bash
uv run python scripts/run_prospective_shadow_cycle.py \
  --market us \
  --as-of-date 2026-07-31 \
  --prices-csv data/forward_shadow/us_prices_2026-07-31.csv \
  --spec configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2.yaml \
  --registry-db artifacts/factor_registry.db \
  --ledger-dir artifacts/decision_ledger \
  --workspace-dir artifacts/forward_shadow_runs
```

An optional point-in-time factor score artifact may be supplied with:

```text
--factor-scores artifacts/factor_scores/us_2026-07-31.json
```

## Outputs

The cycle writes:

- a content-addressed rotation workspace;
- a run manifest binding all inputs and output identities;
- `artifacts/decision_ledger/us/YYYY-MM-DD.json`;
- `artifacts/decision_ledger/us/YYYY-MM-DD.md`;
- `artifacts/decision_ledger/us/ledger_manifest.json`.

## Daily operating rules

- Run only after end-of-day data are complete.
- The CSV last date must exactly equal `--as-of-date`.
- Review all warnings before using the ticket as research context.
- Do not overwrite a same-date ticket. Corrected inputs require a new governance decision; the ledger fails closed.
- Treat `ENTER_CANDIDATE` and `REDUCE_CANDIDATE` as prompts for manual review, not orders.
- Track the cumulative paper-turnover budget; the default annual ceiling is 4.0x.
- Never reinterpret the resulting 2026H2 record as untouched validation evidence.

## Promotion boundary

A shadow record may accumulate prospective evidence, but it remains `diagnostic_only` until a separately frozen candidate completes its declared validation. Broker integration and automatic order routing remain out of scope.
