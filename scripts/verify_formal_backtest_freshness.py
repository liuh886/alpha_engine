"""Fail closed when a published formal backtest is older than its market cutoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class FormalBacktestFreshnessError(ValueError):
    """Raised when the formal publication set is stale or internally inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBacktestFreshnessError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalBacktestFreshnessError(f"JSON root must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path) -> dict[str, Any]:
    root = root.resolve()
    policy = _object(root / "freshness.json")
    catalog = _object(root / "catalog.json")
    if policy.get("cutoff_policy") != "latest_completed_trading_session":
        raise FormalBacktestFreshnessError("unsupported cutoff policy")
    if policy.get("research_only") is not True or policy.get("trade_ready") is not False:
        raise FormalBacktestFreshnessError("freshness policy weakens research boundary")

    markets = policy.get("markets")
    required = policy.get("required_models")
    records = catalog.get("records")
    if not isinstance(markets, dict) or not markets:
        raise FormalBacktestFreshnessError("market cutoffs are missing")
    if not isinstance(required, list) or not required:
        raise FormalBacktestFreshnessError("required model list is missing")
    if not isinstance(records, list):
        raise FormalBacktestFreshnessError("formal catalog records are missing")

    by_id = {
        str(row.get("model_id")): row
        for row in records
        if isinstance(row, dict) and row.get("model_id")
    }
    if set(by_id) != set(str(value) for value in required):
        raise FormalBacktestFreshnessError(
            "formal catalog does not exactly match freshness required_models"
        )

    verified: list[dict[str, Any]] = []
    for model_id in required:
        record = by_id[str(model_id)]
        package_path = root / str(record.get("path") or "")
        if not package_path.is_file():
            raise FormalBacktestFreshnessError(f"{model_id}: package is missing")
        observed_hash = _sha256(package_path)
        if observed_hash != record.get("sha256"):
            raise FormalBacktestFreshnessError(f"{model_id}: catalog SHA-256 mismatch")

        package = _object(package_path)
        if package.get("model_id") != model_id:
            raise FormalBacktestFreshnessError(f"{model_id}: package identity mismatch")
        if package.get("publication_status") != "accepted_formal_baseline":
            raise FormalBacktestFreshnessError(f"{model_id}: not an accepted baseline")
        if package.get("research_only") is not True or package.get("trade_ready") is not False:
            raise FormalBacktestFreshnessError(f"{model_id}: research boundary mismatch")

        market = str(package.get("market") or "")
        expected = str(markets.get(market) or "")
        if not expected:
            raise FormalBacktestFreshnessError(f"{model_id}: no cutoff for market {market!r}")
        actual = str(package.get("evidence_cutoff") or "")
        date_range = package.get("date_range")
        end = str(date_range.get("end") or "") if isinstance(date_range, dict) else ""
        freshness = package.get("freshness")
        if actual != expected or end != expected:
            raise FormalBacktestFreshnessError(
                f"{model_id}: stale formal package; expected {expected}, "
                f"evidence_cutoff={actual!r}, date_range.end={end!r}"
            )
        if not isinstance(freshness, dict):
            raise FormalBacktestFreshnessError(f"{model_id}: freshness receipt is missing")
        if freshness.get("status") != "current":
            raise FormalBacktestFreshnessError(f"{model_id}: freshness status is not current")
        if freshness.get("required_cutoff") != expected:
            raise FormalBacktestFreshnessError(f"{model_id}: freshness cutoff mismatch")
        if freshness.get("latest_completed_session") != expected:
            raise FormalBacktestFreshnessError(f"{model_id}: latest session mismatch")

        verified.append(
            {
                "model_id": model_id,
                "market": market,
                "required_cutoff": expected,
                "package_sha256": observed_hash,
            }
        )

    return {
        "schema_version": "1.0.0",
        "status": "current",
        "cutoff_policy": policy["cutoff_policy"],
        "verified_models": verified,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    receipt = verify(args.root)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
