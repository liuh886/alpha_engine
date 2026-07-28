"""Rebuild an isolated CN provider after repairing invalid OHLCV sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.build_market_providers import DEFAULT_FIELDS, build_market_provider
from src.data.adapters.base import MarketDataAdapter
from src.data.market_provider import load_provider_manifest
from src.data.router import MarketDataRouter, RouterAttempt
from src.data.validation.schema import validate_market_data

SCHEMA_VERSION = "1.0"
EVIDENCE_TYPE = "isolated_cn_ohlcv_source_repair"
CANONICAL_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
)
REPAIR_PROVIDER_ORDER = ("efinance", "akshare")
MIN_DATE_OVERLAP_RATIO = 0.95


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _manifest_sources(manifest: dict[str, Any]) -> dict[str, str]:
    entries = manifest.get("source_csvs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("provider manifest must contain source_csvs")
    sources: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("source_csvs entries must be objects")
        name = str(entry.get("name", "")).strip()
        digest = str(entry.get("sha256", "")).strip()
        if Path(name).name != name or not name.endswith(".csv"):
            raise ValueError(f"invalid source filename in manifest: {name!r}")
        if len(digest) != 64:
            raise ValueError(f"invalid source digest for {name}")
        if name in sources:
            raise ValueError(f"duplicate source filename in manifest: {name}")
        sources[name] = digest
    return sources


def _resolve_source(
    name: str,
    expected_sha256: str,
    source_dirs: tuple[Path, ...],
) -> Path:
    mismatches: list[str] = []
    for directory in source_dirs:
        candidate = directory / name
        if not candidate.is_file():
            continue
        observed = _sha256(candidate)
        if observed == expected_sha256:
            return candidate
        mismatches.append(observed)
    if mismatches:
        raise ValueError(
            f"manifest hash mismatch for {name}: observed={mismatches}"
        )
    raise FileNotFoundError(f"manifest-pinned source is unavailable: {name}")


def _normalise_frame(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    missing = set(CANONICAL_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"{source} is missing columns: {sorted(missing)}")
    result = frame[list(CANONICAL_COLUMNS)].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in CANONICAL_COLUMNS[1:]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result["date"].isna().any():
        raise ValueError(f"{source} contains unparseable dates")
    return result


def _source_validation_errors(
    frame: pd.DataFrame,
    *,
    symbol: str,
) -> list[str]:
    errors: list[str] = []
    if frame["date"].duplicated().any():
        errors.append("duplicate dates")
    ok, _, schema_errors = validate_market_data(frame, symbol)
    if not ok:
        errors.extend(str(error) for error in schema_errors)
    return errors


def _date_set(frame: pd.DataFrame) -> set[pd.Timestamp]:
    return set(pd.to_datetime(frame["date"], errors="coerce").dropna())


def _coverage(
    original: pd.DataFrame,
    repaired: pd.DataFrame,
) -> dict[str, Any]:
    original_dates = _date_set(original)
    repaired_dates = _date_set(repaired)
    overlap = original_dates.intersection(repaired_dates)
    ratio = len(overlap) / len(original_dates) if original_dates else 0.0
    return {
        "original_first": min(original_dates).date().isoformat(),
        "original_last": max(original_dates).date().isoformat(),
        "repaired_first": min(repaired_dates).date().isoformat(),
        "repaired_last": max(repaired_dates).date().isoformat(),
        "original_dates": len(original_dates),
        "repaired_dates": len(repaired_dates),
        "overlap_ratio": round(ratio, 6),
    }


def _attempt_payload(attempt: RouterAttempt) -> dict[str, Any]:
    return attempt.to_dict()


def _default_router() -> MarketDataRouter:
    from src.data.adapters.akshare_adapter import AkShareAdapter
    from src.data.adapters.efinance_adapter import EFinanceAdapter

    adapters: list[MarketDataAdapter] = [
        EFinanceAdapter(),
        AkShareAdapter(),
    ]
    return MarketDataRouter(
        adapters=adapters,
        policy={"cn": list(REPAIR_PROVIDER_ORDER)},
    )


def _fetch_replacement(
    *,
    symbol: str,
    original: pd.DataFrame,
    router: MarketDataRouter,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    original_dates = _date_set(original)
    if not original_dates:
        raise ValueError(f"cannot determine original date range for {symbol}")
    start = min(original_dates).date().isoformat()
    end = max(original_dates).date().isoformat()
    response = router.fetch_daily_bars(
        symbol=symbol,
        market="cn",
        start=start,
        end=end,
        validate=True,
    )
    attempts = [_attempt_payload(item) for item in response.attempts]
    if not response.ok or response.result is None:
        raise RuntimeError(
            f"all repair providers failed for {symbol}: "
            f"{json.dumps(attempts, sort_keys=True)}"
        )

    repaired = _normalise_frame(
        response.result.df,
        source=f"{response.result.provider}:{symbol}",
    )
    if repaired.empty:
        raise RuntimeError(f"repair provider returned no rows for {symbol}")
    errors = _source_validation_errors(repaired, symbol=symbol)
    coverage = _coverage(original, repaired)
    if coverage["repaired_first"] > coverage["original_first"]:
        errors.append("replacement starts after original")
    if coverage["repaired_last"] < coverage["original_last"]:
        errors.append("replacement ends before original")
    if coverage["overlap_ratio"] < MIN_DATE_OVERLAP_RATIO:
        errors.append(
            "replacement date overlap "
            f"{coverage['overlap_ratio']:.4f} < {MIN_DATE_OVERLAP_RATIO:.2f}"
        )
    if errors:
        raise RuntimeError(
            f"replacement validation failed for {symbol}: {'; '.join(errors)}"
        )

    selected = next(item for item in response.attempts if item.ok)
    metadata = {
        "symbol": symbol,
        "selected_provider": selected.provider,
        "provider_symbol": selected.provider_symbol,
        "attempts": attempts,
        "date_coverage": coverage,
    }
    return repaired, metadata


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, lineterminator="\n")


def _validate_output_sources(csv_dir: Path) -> int:
    invalid = 0
    for path in sorted(csv_dir.glob("*.csv")):
        try:
            frame = _normalise_frame(pd.read_csv(path), source=path.name)
        except (OSError, ValueError):
            invalid += 1
            continue
        if _source_validation_errors(frame, symbol=path.stem):
            invalid += 1
    return invalid


def repair_cn_manifest_ohlcv_sources(
    *,
    original_manifest_path: str | Path,
    source_csv_dirs: list[str | Path],
    output_root: str | Path,
    router: MarketDataRouter | None = None,
    evidence_output: str | Path | None = None,
) -> dict[str, Any]:
    """Repair schema-invalid sources and atomically publish an isolated copy."""

    manifest_path = Path(original_manifest_path).resolve()
    output = Path(output_root).resolve()
    source_dirs = tuple(Path(item).resolve() for item in source_csv_dirs)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output root is not empty: {output}")
    if manifest_path.name != "provider_manifest.json":
        raise ValueError("original manifest must be named provider_manifest.json")

    manifest = load_provider_manifest(
        manifest_path.parent,
        expected_market="cn",
        required=True,
        verify_files=False,
    )
    if manifest is None:
        raise FileNotFoundError(f"provider manifest is unavailable: {manifest_path}")
    sources = _manifest_sources(manifest)
    resolved = {
        name: _resolve_source(name, digest, source_dirs)
        for name, digest in sources.items()
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.rmdir()
    repair_router = router or _default_router()
    repair_manifest: dict[str, Any]
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-staging-",
        dir=output.parent,
    ) as temporary:
        stage = Path(temporary) / "payload"
        csv_out = stage / "data" / "csv_source"
        csv_out.mkdir(parents=True)
        replacements: list[dict[str, Any]] = []
        invalid_before = 0

        for name, source_path in sorted(resolved.items()):
            symbol = Path(name).stem
            original = _normalise_frame(
                pd.read_csv(source_path),
                source=name,
            )
            validation_errors = _source_validation_errors(
                original,
                symbol=symbol,
            )
            destination = csv_out / name
            if not validation_errors:
                shutil.copy2(source_path, destination)
                continue

            invalid_before += 1
            repaired, metadata = _fetch_replacement(
                symbol=symbol,
                original=original,
                router=repair_router,
            )
            _write_csv(destination, repaired)
            metadata.update(
                {
                    "original_sha256": sources[name],
                    "repaired_sha256": _sha256(destination),
                    "original_validation_errors": validation_errors,
                }
            )
            replacements.append(metadata)

        invalid_after = _validate_output_sources(csv_out)
        final_count = len(list(csv_out.glob("*.csv")))
        if final_count != len(sources):
            raise RuntimeError(
                f"source count changed: original={len(sources)} final={final_count}"
            )
        if invalid_after:
            raise RuntimeError(f"repaired sources remain invalid: {invalid_after}")

        provider_dir = stage / "data" / "providers" / "cn"
        new_provider_manifest = build_market_provider(
            csv_dir=csv_out,
            provider_dir=provider_dir,
            market="cn",
            include_fields=DEFAULT_FIELDS,
        )
        new_manifest_path = provider_dir / "provider_manifest.json"
        repair_manifest = {
            "schema_version": SCHEMA_VERSION,
            "evidence_type": EVIDENCE_TYPE,
            "repair_provider_order": list(REPAIR_PROVIDER_ORDER),
            "original_provider": {
                "provider_identity_sha256": manifest.get(
                    "provider_identity_sha256"
                ),
                "manifest_sha256": _sha256(manifest_path),
                "calendar": manifest.get("calendar"),
                "instruments": manifest.get("instruments"),
            },
            "new_provider": {
                "provider_identity_sha256": new_provider_manifest.get(
                    "provider_identity_sha256"
                ),
                "manifest_sha256": _sha256(new_manifest_path),
                "calendar": new_provider_manifest.get("calendar"),
                "instruments": new_provider_manifest.get("instruments"),
            },
            "source_count": len(sources),
            "invalid_before": invalid_before,
            "invalid_after": invalid_after,
            "replacements": replacements,
            "research_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
        }
        evidence_dir = (
            stage / "artifacts" / "evidence" / "cn_ohlcv_repair"
        )
        _write_json(
            evidence_dir / "repair_manifest.json",
            repair_manifest,
        )
        stage.replace(output)
    if evidence_output is not None:
        _write_json(Path(evidence_output), repair_manifest)
    return repair_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--source-csv-dir",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Optional second copy of the durable repair manifest.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = repair_cn_manifest_ohlcv_sources(
            original_manifest_path=args.provider_manifest,
            source_csv_dirs=args.source_csv_dir,
            output_root=args.output_root,
            evidence_output=args.evidence_output,
        )
    except Exception as exc:
        print(f"CN OHLCV repair failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "source_count": result["source_count"],
                "invalid_before": result["invalid_before"],
                "invalid_after": result["invalid_after"],
                "replacements": len(result["replacements"]),
                "new_provider_identity": result["new_provider"][
                    "provider_identity_sha256"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
