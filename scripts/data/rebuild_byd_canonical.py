#!/usr/bin/env python3
"""Rebuild the BYD canonical snapshot by merging frozen v1 baseline with
all accumulated prospective observations.

Produces a v2 snapshot that extends the historical baseline to the latest
available prospective observation date. The old v1 snapshot is NEVER modified.
All SHA256 hashes are recomputed and sealed in a new manifest.

Usage:
  python scripts/data/rebuild_byd_canonical.py \
    --v1-snapshot data/research/byd_canonical_v1_snapshot.tar.xz \
    --shadow-store data/research/byd_prospective_shadow \
    --output data/research/byd_canonical_v2_snapshot.tar.xz
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

import pandas as pd


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v1-snapshot", type=Path, required=True,
                   help="Path to byd_canonical_v1_snapshot.tar.xz")
    p.add_argument("--shadow-store", type=Path, required=True,
                   help="Path to byd_prospective_shadow directory")
    p.add_argument("--output", type=Path, required=True,
                   help="Output path for v2 snapshot tar.xz")
    return p.parse_args()


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_chain_linked_observations(shadow_store: Path) -> pd.DataFrame:
    """Collect all chain-linked adjusted OHLCV rows from prospective observations."""
    obs_dir = shadow_store / "observations"
    if not obs_dir.exists():
        return pd.DataFrame()

    rows = []
    for path in sorted(obs_dir.glob("*.json")):
        obs = json.loads(path.read_text(encoding="utf-8"))
        chain = obs.get("chain_linked_adjusted_ohlcv", {})
        if not chain:
            continue
        date_str = obs.get("signal_date", path.stem)
        row = {
            "date": date_str,
            "open": float(chain["open"]),
            "high": float(chain["high"]),
            "low": float(chain["low"]),
            "close": float(chain["close"]),
            "volume": float(chain["volume"]),
        }
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df


def extend_session_audit(frozen_audit: pd.DataFrame, new_sessions: pd.DataFrame,
                         shadow_store: Path) -> pd.DataFrame:
    """Extend session_audit.csv with eligibility flags from prospective observations."""
    frozen_dates = set(frozen_audit["date"].dt.strftime("%Y-%m-%d"))
    new_rows = []
    for _, row in new_sessions.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        if date_str in frozen_dates:
            continue
        # Read eligibility from the observation
        obs_path = shadow_store / "observations" / f"{date_str}.json"
        eligible = False
        if obs_path.exists():
            obs = json.loads(obs_path.read_text(encoding="utf-8"))
            eligible = bool(obs.get("open_research_eligible", False))
        new_rows.append({"date": row["date"], "open_research_eligible": eligible})

    if not new_rows:
        return frozen_audit

    new_df = pd.DataFrame(new_rows)
    new_df["date"] = pd.to_datetime(new_df["date"])
    result = pd.concat([frozen_audit, new_df], ignore_index=True)
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return result


def main():
    args = parse_args()

    if not args.v1_snapshot.exists():
        raise FileNotFoundError(f"v1 snapshot not found: {args.v1_snapshot}")

    # Verify v1 identity
    v1_expected = "2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179"
    v1_actual = compute_sha256(args.v1_snapshot)
    if v1_actual != v1_expected:
        raise RuntimeError(f"v1 snapshot SHA256 mismatch: expected {v1_expected}, got {v1_actual}")

    # Collect new observations
    new_data = collect_chain_linked_observations(args.shadow_store)
    if new_data.empty:
        print("No new prospective observations — v2 snapshot would be identical to v1")
        shutil.copy2(args.v1_snapshot, args.output)
        return

    print(f"Collected {len(new_data)} new observation(s): "
          f"{new_data['date'].min().date()} to {new_data['date'].max().date()}")

    # Extract v1 to temp dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(args.v1_snapshot, "r:xz") as tf:
            tf.extractall(tmp_path)

        # Read frozen CSVs
        adjusted_path = tmp_path / "adjusted_ohlcv.csv"
        session_path = tmp_path / "session_audit.csv"
        manifest_path = tmp_path / "manifest.json"

        frozen_adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
        frozen_session = pd.read_csv(session_path, parse_dates=["date"])
        frozen_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Verify frozen data cutoff — new observations must start after it
        frozen_cutoff = pd.Timestamp(frozen_manifest["cutoff"])
        new_after_cutoff = new_data[new_data["date"] > frozen_cutoff]
        if len(new_after_cutoff) == 0:
            print("All new observations are on or before frozen cutoff — no extension needed")
            shutil.copy2(args.v1_snapshot, args.output)
            return

        print(f"Extending from {frozen_cutoff.date()} with "
              f"{len(new_after_cutoff)} post-cutoff observation(s)")

        # Extend adjusted OHLCV
        extended = pd.concat([frozen_adjusted, new_after_cutoff], ignore_index=True)
        extended = extended.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        extended.to_csv(adjusted_path, index=False)

        # Extend session audit
        extended_session = extend_session_audit(frozen_session, new_after_cutoff, args.shadow_store)
        extended_session.to_csv(session_path, index=False)

        # Update manifest
        new_cutoff = extended["date"].max().strftime("%Y-%m-%d")
        manifest = dict(frozen_manifest)
        manifest["cutoff"] = new_cutoff
        manifest["rows"] = int(len(extended))
        manifest["last_date"] = new_cutoff
        manifest["schema_version"] = "byd_canonical_adjusted_ohlcv_v2"

        # Recompute SHA256s
        adjusted_csv = adjusted_path.read_bytes()
        session_csv = session_path.read_bytes()
        manifest["adjusted_sha256"] = hashlib.sha256(adjusted_csv).hexdigest()
        manifest["session_audit_sha256"] = hashlib.sha256(session_csv).hexdigest()

        manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        manifest["manifest_sha256"] = hashlib.sha256(manifest_json).hexdigest()
        manifest_path.write_bytes(manifest_json)

        # Archive to new tar.xz
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.output, "w:xz") as tf:
            for name in ["adjusted_ohlcv.csv", "session_audit.csv",
                         "manifest.json", "quarantined_open_dates.csv"]:
                fpath = tmp_path / name
                if fpath.exists():
                    tf.add(fpath, arcname=name)

    # Final SHA256
    output_sha = compute_sha256(args.output)
    print(f"\nCanonical v2 snapshot written: {args.output}")
    print(f"SHA256: {output_sha}")
    print(f"Cutoff: {new_cutoff}")
    print(f"Sessions: {len(extended)} (was {len(frozen_adjusted)})")
    print(f"New manifest SHA256: {manifest['manifest_sha256']}")


if __name__ == "__main__":
    main()
