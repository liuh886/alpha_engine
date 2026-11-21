"""Apply a governed, allowlisted CN ETF volume-basis correction to evidence.

The governed 515180 series is provider-reported **lots** (手). The #1472
Eastmoney fund path multiplied provider lots by 100, so the published
2026-11-17 row carries share volume while its neighbours carry lots. This tool
corrects an explicit ``(symbol, session)`` allowlist in the committed market
evidence and re-seals the catalog symbol digest; it changes nothing else.

The contract is deliberately narrow and fail-closed:

* only allowlisted symbols/sessions are touched;
* the current value must equal the recorded ``before`` volume, so a second run
  cannot divide an already-corrected series again;
* the corrected value must be exactly ``before / 100`` (1 lot = 100 shares) and
  stay within an order-of-magnitude band of the local neighbour median, proving
  the correction restores the lot basis rather than skewing a normal row;
* the symbol file must currently match its catalog digest (seal consistency);
* every other bar in the symbol and every other catalog row must be unchanged;
* a receipt is written under ``docs/evidence/`` recording before/after values,
  provider evidence and the reason.

The tool does not recompute derived factor series. Volume-derived factor rows
for the affected session (and its rolling windows) remain as published until a
governed market-evidence rebuild; the receipt records that residual explicitly.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

MARKET = "cn"
MARKET_EVIDENCE_RELATIVE = Path("data/research/market_evidence")
DEFAULT_RECEIPT_RELATIVE = Path(
    "docs/evidence/cn_etf_volume_basis_2026-11-21/correction-receipt.json"
)
SHARES_PER_LOT = 100.0
_NEIGHBOUR_WINDOW = 5
_NEIGHBOUR_MIN_RATIO = 0.05
_NEIGHBOUR_MAX_RATIO = 20.0

# Explicit allowlist: symbol -> session -> expected pre-correction evidence.
# The 2026-11-17 row was published by the #1472 Eastmoney fund path after a
# lot-to-share x100 conversion. Its neighbours (and the governed Tencent
# transport) are provider-reported lots.
CORRECTION_ALLOWLIST: dict[str, dict[str, dict[str, Any]]] = {
    "515180": {
        "2026-11-17": {
            "before_volume": 249_556_800.0,
            "shares_per_lot": SHARES_PER_LOT,
            "reason": (
                "Published from the #1472 Eastmoney fund path, which converted "
                "provider lots to shares (x100). The governed CN ETF series is "
                "provider-reported lots, so the row must be divided by 100."
            ),
        }
    }
}

_PROVIDER_EVIDENCE = {
    "governed_series_basis": "provider_reported_lots",
    "governed_source_transport": "tencent_qfq_history",
    "offending_path": "akshare fund_etf_hist_em (#1472) multiplied lots by 100",
    "cross_vendor_check": (
        "Sina fund_etf_hist_sina volume / governed volume == 100.0000 over "
        "1,403 overlap rows; Sina shares map 100:1 to governed lots"
    ),
    "eastmoney_check": (
        "fund_etf_hist_em reports volume in 手 (lots) and 成交额 in CNY; "
        "#1472's lot-to-share conversion produced the 100x row"
    ),
    "post_correction_neighbour_example": {
        "2026-11-19": 2_185_007.0,
        "2026-11-20": 3_051_139.0,
    },
}
_DERIVED_SERIES_NOTE = (
    "Only bars[].volume is corrected. Volume-derived factor_series rows for "
    "2026-11-17 and their rolling windows are not recomputed here; they remain "
    "as published until the next governed market-evidence rebuild."
)


class VolumeBasisCorrectionError(ValueError):
    """Raised when a correction would exceed its narrow allowlisted contract."""


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _pretty_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_canonical_json(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise VolumeBasisCorrectionError(f"invalid {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise VolumeBasisCorrectionError(f"{label} root must be an object: {path}")
    if _canonical_json(payload) != raw:
        raise VolumeBasisCorrectionError(
            f"{label} is not in canonical JSON form: {path}"
        )
    return payload, _sha256(raw)


def _find_bar(payload: Mapping[str, Any], session: str, *, symbol: str) -> dict[str, Any]:
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise VolumeBasisCorrectionError(f"{symbol} evidence has no bars list")
    matches = [bar for bar in bars if isinstance(bar, dict) and bar.get("time") == session]
    if len(matches) != 1:
        raise VolumeBasisCorrectionError(
            f"{symbol} {session}: expected exactly one bar, found {len(matches)}"
        )
    return matches[0]


def _local_neighbour_median(
    bars: Sequence[Mapping[str, Any]], session: str
) -> float:
    index = next(
        position for position, bar in enumerate(bars) if bar.get("time") == session
    )
    neighbours = [
        float(bar["volume"])
        for position, bar in enumerate(bars)
        if position != index
        and abs(position - index) <= _NEIGHBOUR_WINDOW
        and isinstance(bar.get("volume"), (int, float))
    ]
    if not neighbours:
        raise VolumeBasisCorrectionError(
            f"{session}: no neighbour volumes are available for basis sanity"
        )
    return float(sorted(neighbours)[len(neighbours) // 2])


def _apply_symbol_correction(
    payload: dict[str, Any],
    *,
    symbol: str,
    sessions: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before = copy.deepcopy(payload)
    corrections: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    for session, entry in sessions.items():
        if session in seen_sessions:
            raise VolumeBasisCorrectionError(f"{symbol}: duplicate session {session}")
        seen_sessions.add(session)
        bar = _find_bar(payload, session, symbol=symbol)
        before_volume = float(entry["before_volume"])
        shares_per_lot = float(entry.get("shares_per_lot", SHARES_PER_LOT))
        if not math.isfinite(shares_per_lot) or shares_per_lot <= 1.0:
            raise VolumeBasisCorrectionError(
                f"{symbol} {session}: invalid shares_per_lot {shares_per_lot}"
            )
        current_volume = float(bar.get("volume"))
        after_volume = before_volume / shares_per_lot
        if not math.isclose(current_volume, before_volume, rel_tol=0.0, abs_tol=1e-6):
            if math.isclose(current_volume, after_volume, rel_tol=0.0, abs_tol=1e-6):
                raise VolumeBasisCorrectionError(
                    f"{symbol} {session}: already corrected to {after_volume}; "
                    "refusing to divide again"
                )
            raise VolumeBasisCorrectionError(
                f"{symbol} {session}: current volume {current_volume} does not "
                f"match recorded before value {before_volume}"
            )
        if not after_volume.is_integer() or after_volume <= 0.0:
            raise VolumeBasisCorrectionError(
                f"{symbol} {session}: {before_volume}/{shares_per_lot} is not a "
                "positive whole lot"
            )
        neighbour_median = _local_neighbour_median(payload["bars"], session)
        ratio = after_volume / neighbour_median
        if not _NEIGHBOUR_MIN_RATIO <= ratio <= _NEIGHBOUR_MAX_RATIO:
            raise VolumeBasisCorrectionError(
                f"{symbol} {session}: corrected lot volume {after_volume} is "
                f"{ratio:.3f}x the neighbour median {neighbour_median}; refusing "
                "to apply an implausible lot basis"
            )
        bar["volume"] = float(int(after_volume))
        corrections.append(
            {
                "symbol": symbol,
                "session": session,
                "before_volume": before_volume,
                "after_volume": float(int(after_volume)),
                "shares_per_lot": shares_per_lot,
                "local_neighbour_median": neighbour_median,
                "local_neighbour_ratio_after": ratio,
                "reason": str(entry["reason"]),
            }
        )

    _assert_only_allowlisted_bars_changed(before, payload, sessions, corrections)
    return corrections


def _assert_only_allowlisted_bars_changed(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    sessions: Mapping[str, Mapping[str, Any]],
    corrections: Sequence[Mapping[str, Any]],
) -> None:
    expected = {str(correction["session"]): correction["after_volume"] for correction in corrections}
    if set(before) != set(after):
        raise VolumeBasisCorrectionError("correction changed the symbol payload keys")
    for key in before:
        if key == "bars":
            continue
        if before[key] != after[key]:
            raise VolumeBasisCorrectionError(
                f"correction unexpectedly changed non-bar evidence field: {key}"
            )
    before_bars = before.get("bars")
    after_bars = after.get("bars")
    if not isinstance(before_bars, list) or not isinstance(after_bars, list):
        raise VolumeBasisCorrectionError("correction lost the bars list")
    if len(before_bars) != len(after_bars):
        raise VolumeBasisCorrectionError("correction changed the bar count")
    for old_bar, new_bar in zip(before_bars, after_bars):
        session = old_bar.get("time")
        if session not in sessions:
            if old_bar != new_bar:
                raise VolumeBasisCorrectionError(
                    f"correction changed a non-allowlisted bar: {session}"
                )
            continue
        if {key: value for key, value in old_bar.items() if key != "volume"} != {
            key: value for key, value in new_bar.items() if key != "volume"
        }:
            raise VolumeBasisCorrectionError(
                f"correction changed non-volume fields on allowlisted bar: {session}"
            )
        if new_bar.get("volume") != expected[str(session)]:
            raise VolumeBasisCorrectionError(
                f"allowlisted bar {session} did not receive the expected lot volume"
            )


def correct_cn_etf_volume_basis(
    root: Path,
    *,
    allowlist: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    apply: bool = False,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and optionally apply the allowlisted volume-basis correction."""

    root = Path(root)
    allowlist = CORRECTION_ALLOWLIST if allowlist is None else allowlist
    if not allowlist:
        raise VolumeBasisCorrectionError("correction allowlist is empty")
    evidence_root = root / MARKET_EVIDENCE_RELATIVE / MARKET
    catalog_path = evidence_root / "catalog.json"
    catalog, catalog_sha_before = _load_canonical_json(catalog_path, label="catalog")
    rows = catalog.get("symbols")
    if not isinstance(rows, list):
        raise VolumeBasisCorrectionError("catalog has no symbols list")
    rows_by_symbol = {
        str(row.get("symbol")): row for row in rows if isinstance(row, dict)
    }
    for symbol in allowlist:
        if symbol not in rows_by_symbol:
            raise VolumeBasisCorrectionError(
                f"allowlisted symbol {symbol} is absent from the catalog"
            )

    corrections: list[dict[str, Any]] = []
    symbol_updates: list[tuple[Path, bytes]] = []
    new_catalog = copy.deepcopy(catalog)
    new_rows_by_symbol = {
        str(row.get("symbol")): row for row in new_catalog["symbols"]
    }
    for symbol, sessions in allowlist.items():
        row = rows_by_symbol[symbol]
        relative = row.get("path")
        if not isinstance(relative, str) or not relative:
            raise VolumeBasisCorrectionError(f"{symbol}: catalog path is missing")
        symbol_path = evidence_root / relative
        payload, symbol_sha_before = _load_canonical_json(
            symbol_path, label=f"{symbol} evidence"
        )
        if row.get("sha256") != symbol_sha_before:
            raise VolumeBasisCorrectionError(
                f"{symbol}: catalog digest does not match the symbol evidence"
            )
        session_corrections = _apply_symbol_correction(
            payload, symbol=symbol, sessions=sessions
        )
        new_bytes = _canonical_json(payload)
        symbol_sha_after = _sha256(new_bytes)
        for correction in session_corrections:
            correction["symbol_sha256_before"] = symbol_sha_before
            correction["symbol_sha256_after"] = symbol_sha_after
        corrections.extend(session_corrections)
        new_rows_by_symbol[symbol]["sha256"] = symbol_sha_after
        symbol_updates.append((symbol_path, new_bytes))

    catalog_summary_before = {
        "catalog_sha256": catalog_sha_before,
        "symbol_count": len(rows),
        "symbols": {
            symbol: str(rows_by_symbol[symbol].get("sha256")) for symbol in allowlist
        },
    }
    new_catalog_bytes = _canonical_json(new_catalog)
    catalog_summary_after = {
        "catalog_sha256": _sha256(new_catalog_bytes),
        "symbol_count": len(new_catalog["symbols"]),
        "symbols": {
            symbol: str(new_rows_by_symbol[symbol].get("sha256"))
            for symbol in allowlist
        },
    }
    _assert_catalog_only_reseals_allowlisted_symbols(
        catalog,
        new_catalog,
        allowlist,
        catalog_summary_before,
        catalog_summary_after,
    )

    receipt = {
        "schema_version": "cn_etf_volume_basis_correction_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "applied": bool(apply),
        "market": MARKET,
        "allowlist": {
            symbol: {
                session: {
                    "before_volume": float(entry["before_volume"]),
                    "shares_per_lot": float(
                        entry.get("shares_per_lot", SHARES_PER_LOT)
                    ),
                }
                for session, entry in sessions.items()
            }
            for symbol, sessions in allowlist.items()
        },
        "corrections": corrections,
        "catalog": {
            "before": catalog_summary_before,
            "after": catalog_summary_after,
        },
        "provider_evidence": _PROVIDER_EVIDENCE,
        "derived_series_note": _DERIVED_SERIES_NOTE,
        "research_only": True,
        "trade_ready": False,
    }

    if apply:
        for symbol_path, new_bytes in symbol_updates:
            current = symbol_path.read_bytes()
            if _sha256(current) == _sha256(new_bytes):
                continue
            symbol_path.write_bytes(new_bytes)
        if catalog_path.read_bytes() != new_catalog_bytes:
            catalog_path.write_bytes(new_catalog_bytes)
        target_receipt = (
            Path(receipt_path)
            if receipt_path is not None
            else root / DEFAULT_RECEIPT_RELATIVE
        )
        target_receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt["receipt_path"] = str(target_receipt)
        encoded_receipt = _pretty_json(receipt)
        target_receipt.write_bytes(encoded_receipt)
        receipt["receipt_sha256"] = _sha256(encoded_receipt)
    return receipt


def _assert_catalog_only_reseals_allowlisted_symbols(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    allowlist: Mapping[str, Any],
    before_summary: Mapping[str, Any],
    after_summary: Mapping[str, Any],
) -> None:
    if set(before) != set(after):
        raise VolumeBasisCorrectionError("correction changed catalog top-level keys")
    for key in before:
        if key == "symbols":
            continue
        if before[key] != after[key]:
            raise VolumeBasisCorrectionError(
                f"correction unexpectedly changed catalog field: {key}"
            )
    before_rows = before.get("symbols")
    after_rows = after.get("symbols")
    if not isinstance(before_rows, list) or not isinstance(after_rows, list):
        raise VolumeBasisCorrectionError("catalog symbols are missing")
    if len(before_rows) != len(after_rows):
        raise VolumeBasisCorrectionError("correction changed the catalog row count")
    for old_row, new_row in zip(before_rows, after_rows):
        symbol = str(old_row.get("symbol"))
        if symbol not in allowlist:
            if old_row != new_row:
                raise VolumeBasisCorrectionError(
                    f"correction changed a non-allowlisted catalog row: {symbol}"
                )
            continue
        if {key: value for key, value in old_row.items() if key != "sha256"} != {
            key: value for key, value in new_row.items() if key != "sha256"
        }:
            raise VolumeBasisCorrectionError(
                f"correction changed non-digest fields for {symbol}"
            )
        if new_row.get("sha256") != after_summary["symbols"][symbol]:
            raise VolumeBasisCorrectionError(
                f"correction did not reseal {symbol} with the new digest"
            )
    if before_summary["symbol_count"] != after_summary["symbol_count"]:
        raise VolumeBasisCorrectionError("correction changed catalog symbol count")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the corrected evidence and receipt (default: dry run).",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Override the receipt path (default: under docs/evidence/).",
    )
    args = parser.parse_args(argv)
    result = correct_cn_etf_volume_basis(
        args.root, apply=args.apply, receipt_path=args.receipt
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
