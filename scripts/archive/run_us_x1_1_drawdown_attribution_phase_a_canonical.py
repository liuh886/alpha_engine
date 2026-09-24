"""Canonical score/return alignment entrypoint for Phase A attribution.

Experiment 007 retains the complete model score ledger. The production
`evaluate_candidate` path intersects scores with non-null raw forward returns
before portfolio selection. This entrypoint materializes that economic score
ledger explicitly, preserves both identities, then delegates to the reconciled
attribution engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import scripts.run_us_x1_1_drawdown_attribution_phase_a as core
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

SOURCE_SCORE_SHA256 = core.EXPECTED_SCORE_SHA256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_scores(path: Path, frame: pd.DataFrame) -> str:
    output = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    output["datetime"] = pd.to_datetime(output["datetime"]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")
    return _sha256(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def materialize_economic_scores(
    root: Path,
    *,
    provider_uri: Path,
    source_score_ledger: Path,
    output_path: Path,
) -> dict[str, Any]:
    if _sha256(source_score_ledger) != SOURCE_SCORE_SHA256:
        raise ValueError("source score ledger does not match Experiment 007")
    scores = pd.read_csv(source_score_ledger)
    scores["datetime"] = pd.to_datetime(
        scores["datetime"], errors="raise"
    ).dt.normalize()
    scores["instrument"] = scores["instrument"].astype(str)
    scores["score"] = pd.to_numeric(scores["score"], errors="raise")
    symbols = sorted(scores["instrument"].unique())
    start = scores["datetime"].min().strftime("%Y-%m-%d")
    end = scores["datetime"].max().strftime("%Y-%m-%d")

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri.resolve())
    runtime.initialize(root.resolve())
    provider_identity = str(
        runtime.metadata().get("provider_identity_sha256", "")
    )
    if provider_identity != core.EXPECTED_PROVIDER:
        raise ValueError(f"unexpected provider identity: {provider_identity}")
    returns = normalize_qlib_frame_index(
        runtime.features(
            symbols,
            [core.RETURN_EXPRESSION],
            start,
            end,
        )
    )
    returns.columns = ["return"]
    valid = returns.loc[
        np.isfinite(returns["return"].to_numpy(dtype=float))
    ].reset_index()[["datetime", "instrument"]]
    valid["datetime"] = pd.to_datetime(valid["datetime"]).dt.normalize()
    valid["instrument"] = valid["instrument"].astype(str)
    economic = scores.merge(
        valid,
        on=["datetime", "instrument"],
        how="inner",
        validate="one_to_one",
    )
    economic = economic.sort_values(
        ["datetime", "instrument"], kind="mergesort"
    ).reset_index(drop=True)
    if economic.empty:
        raise ValueError("economic score ledger is empty")
    economic_hash = _write_scores(output_path, economic)
    by_date = (
        scores.groupby("datetime").size().rename("source_rows").to_frame()
        .join(
            economic.groupby("datetime").size().rename("economic_rows"),
            how="left",
        )
        .fillna(0)
    )
    by_date["excluded_rows"] = by_date["source_rows"] - by_date["economic_rows"]
    return {
        "source_score_identity_sha256": SOURCE_SCORE_SHA256,
        "economic_score_identity_sha256": economic_hash,
        "source_rows": int(len(scores)),
        "economic_rows": int(len(economic)),
        "excluded_rows": int(len(scores) - len(economic)),
        "dates_with_exclusions": int((by_date["excluded_rows"] > 0).sum()),
        "max_excluded_rows_on_one_date": int(by_date["excluded_rows"].max()),
        "provider_identity_sha256": provider_identity,
        "alignment_contract": (
            "inner_join_complete_model_scores_with_non_null_raw_forward_10d_returns_"
            "before_cross_sectional_ranking_and_selection"
        ),
    }


def run(
    root: Path,
    *,
    provider_uri: Path,
    source_score_ledger: Path,
    reproduction_result: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    economic_path = output_dir / "aligned_inputs/economic_scores.csv"
    alignment = materialize_economic_scores(
        root,
        provider_uri=provider_uri,
        source_score_ledger=source_score_ledger,
        output_path=economic_path,
    )
    original_expected = core.EXPECTED_SCORE_SHA256
    core.EXPECTED_SCORE_SHA256 = str(
        alignment["economic_score_identity_sha256"]
    )
    try:
        payload = core.run(
            root,
            provider_uri,
            economic_path,
            reproduction_result,
            output_dir,
        )
    finally:
        core.EXPECTED_SCORE_SHA256 = original_expected
    payload["score_alignment"] = alignment
    payload["score_identity_sha256"] = alignment[
        "economic_score_identity_sha256"
    ]
    payload["source_model_score_identity_sha256"] = SOURCE_SCORE_SHA256
    _write_json(output_dir / "drawdown_attribution_phase_a.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--source-score-ledger", type=Path, required=True)
    parser.add_argument("--reproduction-result", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/us_x1_1_drawdown_attribution_phase_a_v1"
        ),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        provider_uri=args.provider_uri,
        source_score_ledger=args.source_score_ledger,
        reproduction_result=args.reproduction_result,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
