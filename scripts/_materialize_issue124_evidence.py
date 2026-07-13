"""Materialize durable Issue #124 evidence from final GitHub Actions artifacts.

This one-time helper is deleted before merge.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

SOURCE_RUN_ID = 29203030333
SOURCE_PR = 145
SOURCE_HEAD_SHA = "c53bc485647c4876b2155ac0a1bb704f1056ad72"
SOURCE_BASE_SHA = "aee95750a819fa414b5e204c322772c9fe61adca"
OUTPUT_ROOT = Path("docs/evidence/issue-124")
INPUT_ROOT = Path(".evidence-input")

MARKETS = {
    "cn": {
        "experiment_id": "cn_10d_csi300_baseline",
        "artifact_id": 8263550974,
        "artifact_sha256": "22a1937f0615b4a446f24b7a33e9df82ed15ba6adeb1f45de15a288b6d6497e5",
    },
    "us": {
        "experiment_id": "us_10d_qqq_baseline",
        "artifact_id": 8262955618,
        "artifact_sha256": "5f33b73f8018d0e2e477e3877d96fc9340bc7037e5e17e7e915e5bc9072da44c",
    },
}

FILES = (
    "real_market_acceptance.json",
    "factor_diagnostics.json",
    "real_market_research_manifest.json",
)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def source_run_dir(market: str, experiment_id: str) -> Path:
    expected = INPUT_ROOT / market / "artifacts" / "research_runs" / experiment_id
    if expected.is_dir():
        return expected
    matches = list((INPUT_ROOT / market).rglob(f"research_runs/{experiment_id}"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"could not uniquely resolve {market} run directory: {matches}"
        )
    return matches[0]


def validate_market(
    market: str,
    acceptance: dict[str, Any],
    diagnostics: dict[str, Any],
    manifest: dict[str, Any],
    file_hashes: dict[str, str],
) -> None:
    if acceptance.get("accepted") is not True:
        raise ValueError(f"{market}: acceptance did not pass")
    summary = acceptance.get("summary", {})
    if summary.get("failed") != 0 or summary.get("passed") != 10:
        raise ValueError(f"{market}: unexpected acceptance summary: {summary}")
    if diagnostics.get("schema_version") != "1.1":
        raise ValueError(f"{market}: expected diagnostic schema 1.1")
    for key, expected in {
        "diagnostic_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "promotion_evaluated": False,
        "trade_ready": False,
    }.items():
        if diagnostics.get(key) is not expected:
            raise ValueError(f"{market}: invalid {key}={diagnostics.get(key)!r}")
    contract = diagnostics.get("return_contract", {})
    if contract.get("horizon_days") != 10 or contract.get("rebalance_days") != 10:
        raise ValueError(f"{market}: non-10D return contract: {contract}")
    windows = diagnostics.get("windows", [])
    if len(windows) != 4:
        raise ValueError(f"{market}: expected four complete OOS windows")
    for window in windows:
        if window.get("excluded_tail_sessions") != 10:
            raise ValueError(f"{market}: window tail not horizon-contained: {window}")
        if window.get("label_horizon_sessions") != 10:
            raise ValueError(f"{market}: wrong label horizon: {window}")
    if manifest.get("acceptance_sha256") != file_hashes["real_market_acceptance.json"]:
        raise ValueError(f"{market}: acceptance hash mismatch")
    if manifest.get("factor_diagnostics_sha256") != file_hashes["factor_diagnostics.json"]:
        raise ValueError(f"{market}: diagnostic hash mismatch")
    if manifest.get("diagnostic_only") is not True:
        raise ValueError(f"{market}: manifest is not diagnostic-only")
    if manifest.get("promotion_eligible") is not False:
        raise ValueError(f"{market}: manifest is promotion eligible")
    if manifest.get("trade_ready") is not False:
        raise ValueError(f"{market}: manifest is trade ready")


def unique_expressions(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for factor in diagnostics.get("factors", []):
        grouped.setdefault(str(factor["expression"]), []).append(factor)
    rows: list[dict[str, Any]] = []
    metric_keys = (
        "recommended_orientation",
        "oriented_rank_icir",
        "oriented_mean_rank_ic",
        "oriented_mean_top_bottom_spread",
        "positive_oriented_window_ratio",
        "direction_agreement",
        "coverage_ratio",
        "valid_dates",
    )
    for expression, factors in grouped.items():
        first = factors[0]
        for factor in factors[1:]:
            if any(factor.get(key) != first.get(key) for key in metric_keys):
                raise ValueError(f"alias metrics diverged for {expression}")
        rows.append(
            {
                "expression": expression,
                "alias_ids": [str(item["id"]) for item in factors],
                "families": sorted({str(item["family"]) for item in factors}),
                "orientation": first.get("recommended_orientation"),
                "oriented_icir": first.get("oriented_rank_icir"),
                "oriented_rank_ic": first.get("oriented_mean_rank_ic"),
                "oriented_spread": first.get("oriented_mean_top_bottom_spread"),
                "positive_window_ratio": first.get("positive_oriented_window_ratio"),
                "direction_agreement": first.get("direction_agreement"),
                "coverage_ratio": first.get("coverage_ratio"),
                "valid_dates": first.get("valid_dates"),
            }
        )
    rows.sort(
        key=lambda item: (
            float("-inf") if item["oriented_icir"] is None else float(item["oriented_icir"]),
            float("-inf")
            if item["positive_window_ratio"] is None
            else float(item["positive_window_ratio"]),
        ),
        reverse=True,
    )
    return rows


def number(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def factor_table(rows: list[dict[str, Any]], limit: int = 7) -> str:
    output: list[str] = []
    for row in rows[:limit]:
        expression = str(row["expression"]).replace("|", "\\|")
        output.append(
            "| `{} ` | {} | {} | {} | {} | {} | {} | {} |".format(
                expression,
                len(row["alias_ids"]),
                row["orientation"],
                number(row["oriented_icir"]),
                number(row["oriented_rank_ic"]),
                number(row["oriented_spread"]),
                number(row["positive_window_ratio"], 2),
                str(bool(row["direction_agreement"])).lower(),
            )
        )
    return "\n".join(output).replace("` ", "`")


def check_details(acceptance: dict[str, Any], name: str) -> dict[str, Any]:
    for check in acceptance.get("checks", []):
        if check.get("name") == name:
            details = check.get("details", {})
            return details if isinstance(details, dict) else {}
    raise KeyError(name)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    market_data: dict[str, dict[str, Any]] = {}
    index_files: dict[str, dict[str, str]] = {}

    for market, metadata in MARKETS.items():
        source_dir = source_run_dir(market, str(metadata["experiment_id"]))
        target_dir = OUTPUT_ROOT / market
        target_dir.mkdir(parents=True, exist_ok=True)
        copied: dict[str, Path] = {}
        hashes: dict[str, str] = {}
        for filename in FILES:
            source = source_dir / filename
            if not source.is_file():
                raise FileNotFoundError(source)
            target = target_dir / filename
            shutil.copyfile(source, target)
            copied[filename] = target
            hashes[filename] = sha256(target)
            index_files[f"{market}/{filename}"] = {"sha256": hashes[filename]}

        acceptance = load(copied["real_market_acceptance.json"])
        diagnostics = load(copied["factor_diagnostics.json"])
        manifest = load(copied["real_market_research_manifest.json"])
        validate_market(market, acceptance, diagnostics, manifest, hashes)
        market_data[market] = {
            "acceptance": acceptance,
            "diagnostics": diagnostics,
            "manifest": manifest,
            "hashes": hashes,
            "unique": unique_expressions(diagnostics),
        }

    index = {
        "schema_version": "1.0",
        "issue": 124,
        "source": {
            "pull_request": SOURCE_PR,
            "workflow_run_id": SOURCE_RUN_ID,
            "workflow_head_sha": SOURCE_HEAD_SHA,
            "base_main_sha": SOURCE_BASE_SHA,
            "artifacts": {
                market: {
                    "artifact_id": metadata["artifact_id"],
                    "artifact_sha256": metadata["artifact_sha256"],
                }
                for market, metadata in MARKETS.items()
            },
        },
        "files": index_files,
        "decision": {
            "issue_124_acceptance_complete": True,
            "diagnostic_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
        },
    }
    (OUTPUT_ROOT / "evidence_index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    cn = market_data["cn"]
    us = market_data["us"]
    cn_acceptance = cn["acceptance"]
    us_acceptance = us["acceptance"]
    cn_diagnostics = cn["diagnostics"]
    us_diagnostics = us["diagnostics"]
    cn_coverage = check_details(cn_acceptance, "universe_provider_coverage")
    us_coverage = check_details(us_acceptance, "universe_provider_coverage")
    cn_csv = check_details(cn_acceptance, "source_csv_integrity")
    us_csv = check_details(us_acceptance, "source_csv_integrity")

    readme = f"""# Issue #124 Final Real-Market Evidence

This directory preserves the final, post-fix CN and US evidence generated by GitHub Actions run `{SOURCE_RUN_ID}` from execution PR #{SOURCE_PR} at head `{SOURCE_HEAD_SHA}`.

The run used `main` after PR #142 (machine-precision OHLC tolerance) and PR #144 (forward-label containment inside each OOS diagnostic window). The execution workflow itself is not merged.

## Outcome

| Market | Acceptance | Covered universe | CSV integrity | Diagnostic schema | Factor IDs | Unique expressions | Sampled dates | Promotion eligible | Trade ready |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CN | {cn_acceptance['summary']['passed']} pass / {cn_acceptance['summary']['warnings']} warn / {cn_acceptance['summary']['failed']} fail | {cn_coverage['covered']} / {cn_coverage['requested']} (min {cn_coverage['minimum_symbols']}) | {cn_csv['inspected']} inspected, {len(cn_csv['invalid'])} invalid, {len(cn_csv['missing'])} missing | {cn_diagnostics['schema_version']} | {cn_diagnostics['factor_count']} | {len(cn['unique'])} | {cn_diagnostics['sampled_rebalance_dates']} | false | false |
| US | {us_acceptance['summary']['passed']} pass / {us_acceptance['summary']['warnings']} warn / {us_acceptance['summary']['failed']} fail | {us_coverage['covered']} / {us_coverage['requested']} (min {us_coverage['minimum_symbols']}) | {us_csv['inspected']} inspected, {len(us_csv['invalid'])} invalid, {len(us_csv['missing'])} missing | {us_diagnostics['schema_version']} | {us_diagnostics['factor_count']} | {len(us['unique'])} | {us_diagnostics['sampled_rebalance_dates']} | false | false |

Both markets passed real-provider identity, calendar coverage, benchmark coverage, universe coverage, and source-CSV integrity. Both retain an explicit survivorship-bias warning because the universes are static curated memberships dated 2026-07-11.

## Return and sampling contract

Both reports use the raw forward return `Ref($close, -10) / $close - 1`, a 10-session horizon, and a 10-session rebalance cadence. CN uses Top/Bottom 15 and US uses Top/Bottom 10.

The four complete OOS windows are 2024H1, 2024H2, 2025H1, and 2025H2. The final 10 market sessions of each window are excluded before sampling, so forward labels cannot cross the window boundary.

The current helper excludes 2026H1 because its natural end date is 2026-06-30 while the declared `test_end` is 2026-06-18. This is a follow-up design question, not an acceptance failure.

## CN leading unique expressions

| Expression | Alias IDs | Orientation | Oriented ICIR | Oriented Rank IC | Oriented Top-Bottom spread | Positive-window ratio | Direction agreement |
|---|---:|---|---:|---:|---:|---:|---:|
{factor_table(cn['unique'])}

The strongest CN unique expression has oriented ICIR around 0.215 and only 50% window-direction consistency. Several volatility expressions show positive oriented IC but negative oriented spread, so they are not coherent promotion candidates.

## US leading unique expressions

| Expression | Alias IDs | Orientation | Oriented ICIR | Oriented Rank IC | Oriented Top-Bottom spread | Positive-window ratio | Direction agreement |
|---|---:|---|---:|---:|---:|---:|---:|
{factor_table(us['unique'])}

20-day momentum and risk-controlled momentum lead the US library, but the best ICIR remains below 0.30. The risk-controlled leader is positive in only half of the OOS windows. Volatility is more directionally stable but remains weak in absolute ICIR terms.

## Evidence hashes

| File | SHA-256 |
|---|---|
"""
    for relative_path, payload in index_files.items():
        readme += f"| `{relative_path}` | `{payload['sha256']}` |\n"

    readme += """

The acceptance and diagnostic hashes match the values recorded inside each market manifest.

## Decision

Issue #124's execution objective is satisfied: real non-synthetic providers and versioned research universes were used; benchmarks remained reference-only; no missing value was replaced with zero or a neutral label; diagnostics remained blocked until acceptance passed; and final outputs remain diagnostic-only, not promotion eligible, and not trade ready.

No factor or model is approved for promotion. Factor-library changes require a separate reviewed task that cites these hashes and does not simultaneously change the universe, dates, cadence, or evaluation contract.

## Known follow-ups

1. Report canonical factor expressions separately from group aliases: CN has 47 factor IDs but 23 unique expressions; US has 24 IDs but 9 unique expressions.
2. Define and test the policy for an incomplete final half-year OOS window.
3. Review these final statistics before any remove, invert, retain, or isolate decision.
"""
    (OUTPUT_ROOT / "README.md").write_text(readme, encoding="utf-8")

    print(
        json.dumps(
            {
                "output_root": str(OUTPUT_ROOT),
                "cn_acceptance_sha256": cn["hashes"]["real_market_acceptance.json"],
                "cn_diagnostics_sha256": cn["hashes"]["factor_diagnostics.json"],
                "us_acceptance_sha256": us["hashes"]["real_market_acceptance.json"],
                "us_diagnostics_sha256": us["hashes"]["factor_diagnostics.json"],
                "cn_unique_expressions": len(cn["unique"]),
                "us_unique_expressions": len(us["unique"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
