# Weekly US Fundamental Validation

This workflow runs the first step of the minimal daily-model path. It does not train a model and does not alter the frozen factor rules.

## What it does

Once per week, after the US market has closed, it:

1. downloads daily adjusted OHLCV for the frozen US pool;
2. reconstructs quarterly revenue and gross-profit observations from SEC Company Facts using filed dates;
3. requires complete factor-ready coverage for every frozen candidate;
4. runs the fixed fundamental-acceleration validation;
5. uploads the decision, source coverage, manifests, and logs.

The weekly cadence is intentional. The underlying information changes with public financial filings, not every trading day.

## Required SEC identity

SEC automated access requires a declared application or organization name and a monitored contact email. The GitHub Actions workflow does not use an anonymous repository-URL fallback.

Create a repository Actions variable named `SEC_USER_AGENT` with a value in this form:

```text
AlphaEngine Research monitored-contact@example.com
```

Use an address that is actually monitored. Do not commit the real value to the repository. The plaintext value is sent only as the HTTP User-Agent; evidence stores only its presence and SHA-256 identity.

Without this repository variable, the workflow fails closed with `live_fundamental_validation_blocked` before performance evaluation.

## Manual run

```bash
uv run python scripts/run_latest_us_fundamental_validation.py
```

For a local run, set the same `SEC_USER_AGENT` environment variable first.

## Results

A completed run produces exactly one research decision:

- `simple_fundamental_factor_not_supported`;
- `simple_fundamental_factor_independent_validation_required`.

Incomplete SEC coverage produces `live_fundamental_validation_blocked` and does not weaken the coverage requirement.

## Boundary

The source is a current SEC Company Facts reconstruction using filed dates. It is useful for observed research and diagnostics, but it is not described as a pristine archived historical-vintage source. All outputs remain `research_only=true` and `trade_ready=false`.
