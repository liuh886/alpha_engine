#!/usr/bin/env python3
"""Build a manifest-bound provider snapshot for US hierarchical rotation validation.

Reads the upstream provider manifest, verifies every source-CSV hash, extracts
exactly the frozen provider symbols (23 candidates + QQQ + ^SOX), excludes rows
on or after 2026-07-01, and writes a deterministic ``prices.csv`` +
``provider_manifest.json`` pair into the snapshot directory.

The snapshot manifest binds the combined prices hash, exact sorted symbol set,
observed date range, upstream identity, reserved cutoff, and its own recomputed
canonical identity.  Source-hash verification is distinguished from third-party
attestation — no attestation is fabricated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.market_provider import load_provider_manifest
from src.research.focus_watchlist_signal import sha256_file

DEFAULT_PROVIDER_ROOT = Path("data/providers/us")
DEFAULT_SOURCE_CSV_DIR = Path("data/watchlist_source")
DEFAULT_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/us_hierarchical_rotation_validation/provider_snapshot"
)
RESERVED_CUTOFF = pd.Timestamp("2026-07-01")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _identity_sha256(payload: dict[str, Any]) -> str:
    """Recompute canonical identity excluding the identity key itself."""
    identity = {
        k: v for k, v in payload.items() if k != "provider_identity_sha256"
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_required_symbols(pool: dict[str, Any]) -> list[str]:
    """Return sorted provider symbols: candidates + reference provider symbols."""
    candidates: list[str] = []
    for basket in pool.get("baskets", {}).values():
        for symbol in basket.get("symbols", []):
            candidates.append(str(symbol))

    ref_provider_symbols: list[str] = []
    for _display, meta in pool.get("references", {}).items():
        ref_provider_symbols.append(str(meta.get("provider_symbol", _display)))

    # Also include any symbol_metadata provider_symbol aliases
    alias_providers: set[str] = set()
    for _display, meta in pool.get("symbol_metadata", {}).items():
        p_sym = str(meta.get("provider_symbol", _display))
        if p_sym != str(_display):
            alias_providers.add(p_sym)

    all_symbols = sorted(set(candidates + ref_provider_symbols + list(alias_providers)))
    return all_symbols


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_snapshot(
    provider_root: Path,
    source_csv_dir: Path,
    spec_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Build a manifest-bound provider snapshot.

    Returns the snapshot manifest dict (also written to disk).
    """
    provider_root = Path(provider_root).resolve()
    source_csv_dir = Path(source_csv_dir).resolve()
    spec_path = Path(spec_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. load upstream provider manifest --------------------------------
    upstream = load_provider_manifest(provider_root, expected_market="us")
    upstream_identity = upstream.get("provider_identity_sha256", "unknown")
    upstream_manifest_bytes = (
        (provider_root / "provider_manifest.json").read_bytes()
    )
    upstream_manifest_sha256 = hashlib.sha256(upstream_manifest_bytes).hexdigest()

    # ---- 2. load spec + pool → required symbols ----------------------------
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    repo_root = spec_path.parents[2]
    pool_path = repo_root / str(spec["pool_spec"])
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))

    required_symbols = _resolve_required_symbols(pool)
    required_set = set(required_symbols)

    # ---- 3. verify every source CSV hash against upstream manifest ---------
    source_csvs = upstream.get("source_csvs", [])
    if not source_csvs:
        raise ValueError("upstream provider manifest has no source_csvs entries")

    source_entries = {
        Path(str(entry.get("name", ""))).stem: entry
        for entry in source_csvs
        if str(entry.get("name", "")).strip()
    }
    missing_entries = sorted(required_set - set(source_entries))
    if missing_entries:
        raise ValueError(
            f"upstream provider manifest is missing frozen sources: {missing_entries}"
        )

    verified_sources: list[dict[str, Any]] = []
    combined_frames: list[pd.DataFrame] = []

    for provider_symbol in required_symbols:
        src_entry = source_entries[provider_symbol]
        src_name = str(src_entry.get("name", ""))
        declared_hash = str(src_entry.get("sha256", ""))
        src_path = source_csv_dir / src_name

        if not src_path.is_file():
            raise FileNotFoundError(
                f"source CSV not found in {source_csv_dir}: {src_name}"
            )

        actual_hash = sha256_file(src_path)
        if actual_hash != declared_hash:
            raise ValueError(
                f"source CSV hash mismatch for {src_name}: "
                f"declared={declared_hash}, actual={actual_hash}"
            )

        # Read and filter to required symbols
        df = pd.read_csv(src_path)
        df.columns = [str(c).strip().lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if "symbol" in df.columns:
            observed_symbols = set(df["symbol"].dropna().astype(str).unique())
            if observed_symbols and observed_symbols != {provider_symbol}:
                raise ValueError(
                    f"source CSV identity mismatch for {src_name}: "
                    f"observed={sorted(observed_symbols)}, expected={provider_symbol}"
                )
        df["symbol"] = provider_symbol

        # Exclude reserved rows before the frame enters the combined snapshot.
        df = df[df["date"] < RESERVED_CUTOFF]
        if not df.empty:
            combined_frames.append(df)

        verified_sources.append({
            "name": src_name,
            "symbol": provider_symbol,
            "declared_sha256": declared_hash,
            "verified": True,
        })

    if not combined_frames:
        raise ValueError(
            "no observed rows after filtering to required symbols "
            f"and excluding dates >= {RESERVED_CUTOFF.date().isoformat()}"
        )

    # ---- 4. combine and write prices.csv -----------------------------------
    combined = pd.concat(combined_frames, ignore_index=True)
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

    # Ensure required columns
    for col in ["open", "high", "low", "close"]:
        if col not in combined.columns:
            raise ValueError(f"combined prices missing required column: {col}")

    observed_symbols = sorted(combined["symbol"].unique().tolist())
    missing_symbols = sorted(required_set - set(observed_symbols))

    if missing_symbols:
        raise ValueError(
            f"snapshot missing required symbols: {missing_symbols}"
        )

    prices_csv_path = output_dir / "prices.csv"
    combined.to_csv(prices_csv_path, index=False)
    prices_sha256 = sha256_file(prices_csv_path)

    first_date = combined["date"].min()
    last_date = combined["date"].max()
    observed_row_count = int(len(combined))

    # ---- 5. build and write snapshot manifest ------------------------------
    snapshot_manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_type": "provider_snapshot",
        "market": "us",
        "snapshot": {
            "prices_csv": "prices.csv",
            "prices_csv_sha256": prices_sha256,
            "symbols": observed_symbols,
            "symbol_count": len(observed_symbols),
            "first_observed_date": first_date.date().isoformat(),
            "last_observed_date": last_date.date().isoformat(),
            "observed_row_count": observed_row_count,
        },
        "calendar": {
            "first_day": first_date.date().isoformat(),
            "last_day": last_date.date().isoformat(),
            "reserved_cutoff": RESERVED_CUTOFF.date().isoformat(),
            "reserved_cutoff_rule": "exclude_rows_on_or_after",
        },
        "upstream": {
            "provider_manifest": "provider_manifest.json",
            "provider_identity_sha256": upstream_identity,
            "provider_manifest_sha256": upstream_manifest_sha256,
            "source_csvs": verified_sources,
            "source_hashes_verified": True,
            "source_attestation": (
                "hashes_verified_by_snapshot_builder_against_upstream_manifest; "
                "no_independent_third_party_attestation"
            ),
        },
        "spec": {
            "path": "configs/research_paradigms/"
            "us_structured_pool_hierarchical_rotation_v2.yaml",
            "sha256": sha256_file(spec_path),
            "experiment_id": str(spec.get("experiment_id", "")),
            "pool_path": str(spec.get("pool_spec", "")),
            "pool_sha256": sha256_file(pool_path),
        },
    }
    snapshot_manifest["provider_identity_sha256"] = _identity_sha256(
        snapshot_manifest
    )

    manifest_path = output_dir / "provider_manifest.json"
    manifest_path.write_text(
        json.dumps(snapshot_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(json.dumps({
        "status": "snapshot_built",
        "output_dir": str(output_dir),
        "prices_csv_sha256": prices_sha256,
        "symbol_count": len(observed_symbols),
        "observed_row_count": observed_row_count,
        "first_observed_date": first_date.date().isoformat(),
        "last_observed_date": last_date.date().isoformat(),
        "snapshot_identity_sha256": snapshot_manifest["provider_identity_sha256"],
    }, indent=2))

    return snapshot_manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a manifest-bound provider snapshot for US "
                    "hierarchical rotation validation."
    )
    parser.add_argument(
        "--provider-root",
        type=Path,
        default=DEFAULT_PROVIDER_ROOT,
        help="Directory containing the upstream provider_manifest.json.",
    )
    parser.add_argument(
        "--source-csv-dir",
        type=Path,
        default=DEFAULT_SOURCE_CSV_DIR,
        help="Directory containing the source CSV files referenced by the manifest.",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        help="Path to the frozen v2 spec YAML.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory to write prices.csv and provider_manifest.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_snapshot(
        provider_root=args.provider_root,
        source_csv_dir=args.source_csv_dir,
        spec_path=args.spec,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
