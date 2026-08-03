"""Canonicalize aggregate relative-excess metrics for Experiment 012.

The core runner retains all economic ledgers and performs two complete evidence
materializations. This entrypoint rewrites aggregate relative excess using the
repository's canonical geometric definition:

    strategy_nav / benchmark_nav - 1

It then regenerates both run manifests, proves exact run-A/run-B identity again,
and emits the final governed decision from the corrected aggregate metrics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import scripts.run_us_x1_1_rank_aware_sector_cap as core


def canonical_relative_excess(
    compounded_total_return: float,
    compounded_benchmark_return: float,
) -> float:
    benchmark_nav = 1.0 + compounded_benchmark_return
    if benchmark_nav <= 0:
        raise ValueError("benchmark NAV must remain positive")
    return (1.0 + compounded_total_return) / benchmark_nav - 1.0


def canonicalize_aggregates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row["compounded_relative_excess"] = canonical_relative_excess(
            float(row["compounded_total_return"]),
            float(row["compounded_benchmark_return"]),
        )
        row["relative_excess_definition"] = "strategy_nav_divided_by_benchmark_nav_minus_1"
        result.append(row)
    return result


def _canonicalize_run(run_root: Path) -> dict[str, Any]:
    result_path = run_root / "rank_aware_sector_cap.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["aggregates"] = canonicalize_aggregates(payload["aggregates"])
    payload["metric_definitions"] = {
        "window_excess_return": "strategy_total_return_minus_benchmark_total_return",
        "compounded_relative_excess": "strategy_nav_divided_by_benchmark_nav_minus_1",
    }
    core._write_json(result_path, payload)
    core._write_manifest(run_root)
    return payload


def run(
    root: Path,
    *,
    provider_uri: Path,
    score_ledger_root: Path,
    reproduction_result: Path,
    universe_path: Path,
    classification_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    core.run(
        root,
        provider_uri=provider_uri,
        score_ledger_root=score_ledger_root,
        reproduction_result=reproduction_result,
        universe_path=universe_path,
        classification_path=classification_path,
        output_dir=output_dir,
    )

    run_a = output_dir / "run_a"
    run_b = output_dir / "run_b"
    payload_a = _canonicalize_run(run_a)
    _canonicalize_run(run_b)
    manifest_a = core._file_manifest(run_a)
    manifest_b = core._file_manifest(run_b)
    if manifest_a != manifest_b:
        differing = sorted(
            key
            for key in set(manifest_a) | set(manifest_b)
            if manifest_a.get(key) != manifest_b.get(key)
        )
        raise ValueError(f"canonical repeated materializations differ: {differing}")

    decision = core._decision(
        payload_a["aggregates"],
        payload_a["window_results"],
        deterministic=True,
    )
    tree_payload = json.dumps(
        manifest_a,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    tree_sha256 = hashlib.sha256(tree_payload).hexdigest()
    final = {
        **payload_a,
        "repeated_materialization": {
            "status": "exact",
            "run_a_file_count": len(manifest_a),
            "run_b_file_count": len(manifest_b),
            "run_a_tree_sha256": tree_sha256,
            "run_b_tree_sha256": tree_sha256,
        },
        "decision": decision,
    }
    final_path = output_dir / "rank_aware_sector_cap_result.json"
    core._write_json(final_path, final)
    core._write_json(
        output_dir / "evidence_manifest.json",
        {
            "schema_version": "1.0",
            "run_a": manifest_a,
            "run_b": manifest_b,
            "result_sha256": core.sha256_file(final_path),
        },
    )
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--score-ledger-root", type=Path, required=True)
    parser.add_argument("--reproduction-result", type=Path, required=True)
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=Path("configs/research_universes/us_selected_equities_v2.yaml"),
    )
    parser.add_argument(
        "--classification-path",
        type=Path,
        default=Path("configs/research_classifications/us87_sector_industry_v1.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us_x1_1_rank_aware_sector_cap_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root.resolve(),
        provider_uri=args.provider_uri.resolve(),
        score_ledger_root=args.score_ledger_root.resolve(),
        reproduction_result=args.reproduction_result.resolve(),
        universe_path=args.universe_path.resolve(),
        classification_path=args.classification_path.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
