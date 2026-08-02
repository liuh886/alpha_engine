# Daily US Low-Turnover Decision Operations

Status: diagnostic-only operating workflow  
Strategy status: not independently validated  
Automatic order routing: disabled

## One-time configuration

Set a truthful SEC fair-access identity before the first live run. It should contain an application or organization name and a monitored contact address.

Windows PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
  "SEC_USER_AGENT",
  "AlphaEngine Research your-contact@example.com",
  "User"
)
```

Restart the terminal or scheduled task after changing the variable. The plaintext value is used only in the HTTP request header. Artifacts store its presence and SHA-256 identity, not the value itself.

For GitHub Actions, create a repository variable named `SEC_USER_AGENT`. When it is absent, the scheduled workflow uses the public repository URL as a non-secret project identity; a monitored contact value is still preferred.

## Manual live run

Run after the US market has closed and daily bars have settled:

```bash
uv run python scripts/run_latest_us_low_turnover_decision.py
```

The command performs the complete chain:

1. downloads adjusted OHLCV for the frozen 23 candidates plus QQQ and SOX;
2. verifies a common complete session across all 25 identities;
3. builds source-bound SEC Company Facts fundamentals;
4. calculates the two PIT fundamental factors;
5. calculates basket relative-momentum and drawdown-resilience factors;
6. builds the four-factor relationship map;
7. composes the frozen low-turnover candidate;
8. creates an immutable Decision Desk ticket;
9. writes manifests for every stage.

A source-bound fundamentals CSV may be supplied when SEC access is being diagnosed:

```bash
uv run python scripts/run_latest_us_low_turnover_decision.py \
  --fundamentals-csv path/to/fundamentals.csv
```

## Local scheduling

Run:

```bash
uv run python scripts/setup_cron.py
```

On Windows, this writes `scripts/run_daily_us_decision.bat` and prints a Task Scheduler command for Tuesday through Saturday at 07:30 local time. On Linux or macOS, it writes an importable crontab fragment to `artifacts/alpha-engine.crontab` with the same schedule. Review it before installing with `crontab artifacts/alpha-engine.crontab`.

07:30 local time is intentionally conservative for both China and Japan system time zones and covers US winter and summer market close.

## GitHub Actions schedule

`.github/workflows/daily-us-low-turnover-decision.yml` runs at 23:30 UTC Monday through Friday. It always uploads available diagnostic artifacts, including source blockers, before preserving a failed status when the governed pipeline cannot complete.

Before each run, the workflow restores the most recent cached:

- `artifacts/decision_ledger`;
- `artifacts/factor_registry.db`.

After the run and diagnostic upload, it saves a new immutable state cache keyed by the workflow run and attempt. This continuity is required for:

- comparisons with the previous ticket;
- cumulative paper-turnover accounting;
- the append-only ticket identity chain;
- persistent factor-card and relationship records.

The cache is an operational continuation mechanism, not authoritative performance evidence. Existing same-date ticket identities still fail closed and cannot be overwritten by restored or newly generated state.

The workflow summary reports:

- whether prior Decision Desk state was restored;
- resolved complete market session;
- number of price symbols and rows;
- SEC factor-ready coverage;
- named source blockers;
- multifactor and turnover-gate status;
- final ticket identity when produced.

## Output locations

- `artifacts/market_snapshots/us_small_pool_v1/`
- `artifacts/forward_shadow_runs/`
- `artifacts/decision_ledger/us/`
- `artifacts/operations/`

Research Artifact Studio can display ledger evidence only when it is exported into a manifest-declared bundle.

## Failure interpretation

A failed daily run is useful evidence, not a reason to bypass a gate.

Common failures include:

- one Yahoo symbol is missing or has a different latest date;
- the session is still open;
- SEC ticker-to-CIK resolution fails;
- a company lacks compatible quarterly revenue or gross-profit concepts;
- one of the four factors is missing or redundant;
- annual paper turnover exceeds the frozen ceiling;
- an existing same-date ticket has a different identity.

Do not remove a stock, alter a factor, relax the turnover ceiling, or overwrite a ticket merely to make the daily job green. Resolve source identity and contract issues explicitly.
