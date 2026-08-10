"""Publish the user-authorized BYD v1.3 low-vol recovery model.

Complete package construction is shared with live refresh. This module adds the
promotion-only checks that the frozen #745 selection evidence is reproduced,
then switches the formal catalog from V1.2 to V1.3 under explicit user authority.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from scripts.byd_formal_publication_common import write_json
from scripts.byd_v1_3_formal_builder import build_package
from src.research.byd_v1_2_convex_momentum import CANDIDATE as V12_MODEL_ID
from src.research.byd_v1_3_low_vol_recovery import DISPLAY_NAME, MODEL_ID, PUBLIC_MODEL_ID

PACKAGE_NAME = f"{MODEL_ID}.json"
SUPERSEDED_MODEL_ID = V12_MODEL_ID
EXPECTED = {
    "candidate_cagr": 0.37838108480564925,
    "champion_cagr": 0.35843544390055615,
    "candidate_sharpe": 0.9538094286223441,
    "candidate_max_drawdown": -0.4892927084747377,
    "relative_terminal_wealth": 0.09753521715046087,
    "turnover_units": 16.76311113908823,
    "max_period_positive_share": 0.5689759320440935,
}


class BYDV13FormalPromotionError(ValueError):
    """Raised when the frozen BYD v1.3 selection evidence cannot be reproduced."""


def _metric(package: Mapping[str, Any], key: str) -> float:
    metrics = package.get("metrics")
    if not isinstance(metrics, Mapping):
        raise BYDV13FormalPromotionError("BYD v1.3 package metrics are missing")
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BYDV13FormalPromotionError(f"BYD v1.3 metric is invalid: {key}")
    return float(value)


def _assert_expected(name: str, actual: float, *, tolerance: float = 1e-10) -> None:
    expected = float(EXPECTED[name])
    if not math.isclose(float(actual), expected, rel_tol=tolerance, abs_tol=tolerance):
        raise BYDV13FormalPromotionError(
            f"frozen #745 evidence drift: {name} expected {expected}, got {actual}"
        )


def verify_frozen_selection_evidence(package: Mapping[str, Any]) -> None:
    """Require the exact pre-promotion #745 result before changing formal identity."""

    _assert_expected("candidate_cagr", _metric(package, "CAGR"))
    _assert_expected("champion_cagr", _metric(package, "Benchmark V1.2 CAGR"))
    _assert_expected("candidate_sharpe", _metric(package, "Sharpe Ratio"))
    _assert_expected("candidate_max_drawdown", _metric(package, "Max Drawdown"))
    _assert_expected(
        "relative_terminal_wealth", _metric(package, "Relative Terminal Wealth vs V1.2")
    )
    _assert_expected("turnover_units", _metric(package, "Turnover"))
    _assert_expected(
        "max_period_positive_share", _metric(package, "Maximum Positive Period Share")
    )

    periods = package.get("period_attribution")
    if not isinstance(periods, list) or len(periods) != 3:
        raise BYDV13FormalPromotionError("BYD v1.3 period attribution is incomplete")
    if any(float(row.get("relative_terminal_wealth", 0.0)) < 0.0 for row in periods):
        raise BYDV13FormalPromotionError("BYD v1.3 frozen period evidence regressed")


def promote(
    *,
    root: Path,
    byd_dir: Path,
    etf_dir: Path,
    signal_ledger: Path,
    generated_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    freshness = json.loads((root / "freshness.json").read_text(encoding="utf-8"))
    predecessor_path = root / f"{SUPERSEDED_MODEL_ID}.json"
    predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(freshness, dict):
        raise BYDV13FormalPromotionError("formal catalog or freshness root is invalid")
    if not isinstance(predecessor, dict):
        raise BYDV13FormalPromotionError("accepted V1.2 predecessor package is invalid")
    markets = freshness.get("markets")
    if not isinstance(markets, dict) or not markets.get("cn"):
        raise BYDV13FormalPromotionError("CN formal freshness cutoff is missing")
    cutoff = str(markets["cn"])

    package = build_package(
        byd_dir=byd_dir,
        etf_dir=etf_dir,
        signal_ledger=signal_ledger,
        cutoff=cutoff,
        generated_at=generated_at,
        predecessor_package=predecessor,
    )
    verify_frozen_selection_evidence(package)
    package["backtest_id"] = f"{MODEL_ID}-formal-user-authorized-2026-08-10"
    package_sha = write_json(root / PACKAGE_NAME, package)

    records = [
        dict(row)
        for row in catalog.get("records", [])
        if isinstance(row, dict)
        and row.get("model_id") not in {MODEL_ID, SUPERSEDED_MODEL_ID}
    ]
    records.append(
        {
            "display_name": DISPLAY_NAME,
            "display_order": 4,
            "model_id": MODEL_ID,
            "path": PACKAGE_NAME,
            "publication_status": "accepted_formal_baseline",
            "sha256": package_sha,
        }
    )
    records.sort(
        key=lambda row: (int(row.get("display_order", 999)), str(row.get("model_id")))
    )
    catalog["records"] = records
    catalog["published_at"] = generated_at
    catalog["research_only"] = True
    catalog["trade_ready"] = False
    write_json(root / "catalog.json", catalog)

    required = [
        str(value)
        for value in freshness.get("required_models", [])
        if str(value) not in {MODEL_ID, SUPERSEDED_MODEL_ID}
    ]
    required.append(MODEL_ID)
    freshness["required_models"] = required
    freshness["declared_at"] = generated_at
    freshness["research_only"] = True
    freshness["trade_ready"] = False
    write_json(root / "freshness.json", freshness)

    return {
        "schema_version": "1.0.0",
        "status": "accepted_formal_baseline_promoted",
        "model_id": MODEL_ID,
        "public_model_id": PUBLIC_MODEL_ID,
        "superseded_model_id": SUPERSEDED_MODEL_ID,
        "package_sha256": package_sha,
        "evidence_cutoff": cutoff,
        "historical_date_range_end": package["date_range"]["end"],
        "promotion_authority": "explicit_user_direction_2026_08_10",
        "historical_evidence_consumed": True,
        "fresh_historical_holdout": False,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/research/formal_backtests"))
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument(
        "--signal-ledger",
        type=Path,
        default=Path(
            "data/research/strategy_signal_ledgers/"
            "byd_v1_3_recovery_event_low_vol_confirmation_v1"
        ),
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = promote(
        root=args.root,
        byd_dir=args.byd_dir,
        etf_dir=args.etf_dir,
        signal_ledger=args.signal_ledger,
        generated_at=args.generated_at,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
