# Cross-repository CI policy

This repository participates in the shared CI policy used across Zhihao Liu's maintained projects.

## Enforced boundary

`CI Governance / Policy` runs only when workflows, the policy manifest, package manifests or lockfiles change. Normal product, content, research and data pull requests do not receive another always-on check.

The machine-readable authority is `.github/ci-policy.json`. `scripts/check_ci_policy.py` inventories every workflow and blocks drift in the workflows explicitly listed as governed.

The common rules are:

- pull-request workflows must use read-only top-level permissions;
- PR and push workflows must define concurrency cancellation;
- required PR gates cannot depend on hard-coded historical workflow run IDs;
- uploaded diagnostic artifacts must declare bounded retention;
- PR diagnostics are retained for at most 14 days, deployable builds for 7 days and durable evidence for at most 90 days through an explicit exception;
- production High/Critical dependency risk is blocking; development and tooling risk is advisory;
- a JavaScript package must use one declared package manager and one matching lockfile.

## Legacy and research workflows

Only stable core workflows are blocking under this policy today. Other workflows remain inventoried and produce modernization warnings. They should be promoted into `governed_workflows` when materially edited rather than creating a repository-wide migration failure.

## Branch protection

Recommended required-check names are recorded in the policy manifest. Repository branch-protection settings are managed in GitHub settings and are not changed by this repository workflow.
