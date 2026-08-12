#!/usr/bin/env python3
"""Refresh the accepted BYD v1.3 formal package append-only."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from scripts.byd_formal_refresh_common import (
    BYDFormalRefreshError,
    extend_byd_input,
    extend_etf_input,
    preserve_verified_prefix,
)
from scripts.byd_v1_3_formal_builder import build_package
from src.artifacts.formal_refresh import load_object, sha256, write_object
from src.research.byd_v1_2_convex_momentum import CANDIDATE as V12_MODEL_ID
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID


class BYDV13RefreshError(BYDFormalRefreshError):
    """Raised when the accepted V1.3 package cannot be refreshed safely."""


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SIGNAL_LEDGER = (
    Path("data/research/strategy_signal_ledgers") / MODEL_ID
)


def _stable_signal_ledger(signal_ledger: Path) -> str:
    expected = (REPOSITORY_ROOT / RUNTIME_SIGNAL_LEDGER).resolve()
    observed = signal_ledger.resolve()
    if observed != expected:
        raise BYDV13RefreshError(
            "BYD v1.3 refresh requires the canonical repository signal ledger: "
            f"{RUNTIME_SIGNAL_LEDGER.as_posix()}"
        )
    return RUNTIME_SIGNAL_LEDGER.as_posix()


def refresh_byd_v1_3(
    *,
    current_package: Path,
    predecessor_package: Path,
    base_byd_dir: Path,
    base_etf_dir: Path,
    shadow_store: Path,
    paired_store: Path,
    signal_ledger: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    current = load_object(current_package)
    predecessor = load_object(predecessor_package)
    if current.get("model_id") != MODEL_ID:
        raise BYDV13RefreshError("BYD refresh requires the accepted BYD v1.3 package")
    if predecessor.get("model_id") != V12_MODEL_ID:
        raise BYDV13RefreshError("BYD v1.3 refresh requires the immutable V1.2 predecessor")
    stable_signal_ledger = _stable_signal_ledger(signal_ledger)

    with tempfile.TemporaryDirectory(prefix="formal-byd-v1-3-refresh-") as temporary:
        root = Path(temporary)
        byd_dir = root / "byd"
        etf_dir = root / "etf"
        byd_manifest = extend_byd_input(
            base_dir=base_byd_dir,
            shadow_store=shadow_store,
            cutoff=cutoff,
            output_dir=byd_dir,
        )
        etf_manifest = extend_etf_input(
            base_dir=base_etf_dir,
            paired_store=paired_store,
            cutoff=cutoff,
            output_dir=etf_dir,
        )

        import src.research.byd_515180_allocation as allocation

        allocation.ETF_CUTOFF = cutoff
        allocation.ETF_SCHEMA = str(etf_manifest["schema_version"])
        allocation.WINDOWS["retrospective_2025_plus"] = ("2025-01-01", cutoff)
        allocation.WINDOWS["full_overlap"] = ("2019-11-26", cutoff)
        candidate = build_package(
            byd_dir=byd_dir,
            etf_dir=etf_dir,
            signal_ledger=signal_ledger,
            cutoff=cutoff,
            generated_at=generated_at,
            predecessor_package=predecessor,
        )

    for field in ("report", "positions", "trades"):
        candidate[field] = preserve_verified_prefix(
            field,
            current.get(field),
            candidate.get(field),
        )
    if candidate.get("portfolio_contract") != current.get("portfolio_contract"):
        raise BYDV13RefreshError("BYD v1.3 portfolio contract changed")

    candidate["backtest_id"] = f"{MODEL_ID}-through-{cutoff.replace('-', '_')}"
    candidate["evidence_cutoff"] = cutoff
    candidate["generated_at"] = generated_at
    candidate["date_range"] = {
        **dict(candidate["date_range"]),
        "end": min(str(candidate["date_range"]["end"]), cutoff),
    }
    candidate["operational_monitoring"] = {
        "status": "separate_runtime_signal_ledger",
        "ledger": stable_signal_ledger,
        "runtime_state_embedded": False,
    }
    candidate["freshness"] = {
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": str(candidate["date_range"]["end"]),
        "model_selection_reopened": False,
        "monitoring_source": stable_signal_ledger,
        "research_only": True,
        "trade_ready": False,
    }
    candidate["evidence"] = {
        **dict(candidate.get("evidence") or {}),
        "refresh_adapter": "refresh_byd_v1_3_formal",
        "byd_extended_manifest_sha256": str(byd_manifest["manifest_sha256"]),
        "etf_extended_manifest_sha256": str(etf_manifest["manifest_sha256"]),
        "shadow_store_manifest_sha256": sha256(shadow_store / "manifest.json"),
        "paired_store_manifest_sha256": sha256(paired_store / "manifest.json"),
        "model_selection_reopened": False,
    }
    candidate["research_only"] = True
    candidate["trade_ready"] = False
    write_object(output, candidate)
    return {
        "model_id": MODEL_ID,
        "appended_sessions": len(candidate["report"]) - len(current["report"]),
        "output_sha256": sha256(output),
        "cutoff": cutoff,
        "model_selection_reopened": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-package", type=Path, required=True)
    parser.add_argument("--predecessor-package", type=Path, required=True)
    parser.add_argument("--base-byd-dir", type=Path, required=True)
    parser.add_argument("--base-etf-dir", type=Path, required=True)
    parser.add_argument("--shadow-store", type=Path, required=True)
    parser.add_argument("--paired-store", type=Path, required=True)
    parser.add_argument("--signal-ledger", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = refresh_byd_v1_3(
        current_package=args.current_package,
        predecessor_package=args.predecessor_package,
        base_byd_dir=args.base_byd_dir,
        base_etf_dir=args.base_etf_dir,
        shadow_store=args.shadow_store,
        paired_store=args.paired_store,
        signal_ledger=args.signal_ledger,
        cutoff=args.cutoff,
        generated_at=args.generated_at,
        output=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
