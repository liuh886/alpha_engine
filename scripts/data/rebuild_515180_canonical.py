#!/usr/bin/env python3
"""Rebuild the 515180 ETF canonical artifact by merging frozen v1 baseline
with all accumulated prospective paired observations.

Produces a v2 artifact that extends the historical baseline to the latest
available observation date.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import pandas as pd


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v1-artifact", type=Path, required=True,
                   help="Path to 515180_canonical_v1_artifact.zip.b64")
    p.add_argument("--paired-store", type=Path, required=True,
                   help="Path to byd_515180_prospective directory")
    p.add_argument("--output", type=Path, required=True,
                   help="Output path for v2 artifact zip.b64")
    return p.parse_args()


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    args = parse_args()

    if not args.v1_artifact.exists():
        raise FileNotFoundError(f"v1 artifact not found: {args.v1_artifact}")

    # Verify v1 identity
    v1_data = args.v1_artifact.read_bytes()
    v1_expected = "7e077664516b74546ec118f2bf0484ee650577a0898623f3f0cb8623397e061f"
    decoded = base64.b64decode(v1_data)
    v1_actual = compute_sha256(decoded)
    if v1_actual != v1_expected:
        raise RuntimeError(f"v1 artifact SHA256 mismatch: expected {v1_expected}, got {v1_actual}")

    # Collect new ETF observations from paired store
    obs_dir = args.paired_store / "observations"
    if not obs_dir.exists():
        print("No paired observations — v2 artifact would be identical to v1")
        shutil.copy2(args.v1_artifact, args.output)
        return

    new_rows = []
    for path in sorted(obs_dir.glob("*.json")):
        obs = json.loads(path.read_text(encoding="utf-8"))
        etf_chain = obs.get("etf_chain_linked_adjusted_ohlcv", {})
        if not etf_chain:
            continue
        date_str = obs.get("signal_date", path.stem)
        # Get raw ETF data for raw_ohlcv.csv extension
        etf_raw = obs.get("etf_primary_raw_ohlcv", {})
        etf_adjusted = obs.get("etf_adjusted_ohlcv", etf_chain)
        row = {
            "date": date_str,
            "open_raw": float(etf_raw.get("open", 0)),
            "high_raw": float(etf_raw.get("high", 0)),
            "low_raw": float(etf_raw.get("low", 0)),
            "close_raw": float(etf_raw.get("close", 0)),
            "volume_raw": float(etf_raw.get("volume", 0)),
            "open_adj": float(etf_adjusted.get("open", 0)),
            "high_adj": float(etf_adjusted.get("high", 0)),
            "low_adj": float(etf_adjusted.get("low", 0)),
            "close_adj": float(etf_adjusted.get("close", 0)),
        }
        new_rows.append(row)

    if not new_rows:
        print("No new ETF observations — v2 artifact would be identical to v1")
        shutil.copy2(args.v1_artifact, args.output)
        return

    new_df = pd.DataFrame(new_rows)
    new_df["date"] = pd.to_datetime(new_df["date"])
    new_df = new_df.sort_values("date").drop_duplicates(subset=["date"], keep="last")

    print(f"Collected {len(new_df)} new ETF observation(s): "
          f"{new_df['date'].min().date()} to {new_df['date'].max().date()}")

    # Extract v1 to temp dir
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(tmp_path / "artifact.zip", "w") as zf:
            zf.write(decoded)  # Not quite right — need to handle extraction properly

        # Actually, extract the decoded zip
        zip_path = tmp_path / "artifact.zip"
        zip_path.write_bytes(decoded)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_path)

        # Read frozen CSVs
        raw_csv = tmp_path / "raw_ohlcv.csv"
        adj_csv = tmp_path / "adjusted_ohlcv.csv"
        manifest_path = tmp_path / "manifest.json"
        session_path = tmp_path / "session_audit.csv"

        frozen_raw = pd.read_csv(raw_csv, parse_dates=["date"])
        frozen_adj = pd.read_csv(adj_csv, parse_dates=["date"])
        frozen_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frozen_session = pd.read_csv(session_path, parse_dates=["date"])
        frozen_cutoff = pd.Timestamp(frozen_manifest["cutoff"])

        new_after = new_df[new_df["date"] > frozen_cutoff]
        if len(new_after) == 0:
            print("No post-cutoff ETF observations — no extension needed")
            shutil.copy2(args.v1_artifact, args.output)
            return

        print(f"Extending ETF from {frozen_cutoff.date()} with "
              f"{len(new_after)} post-cutoff observation(s)")

        # Extend raw OHLCV
        raw_cols = ["date", "open", "high", "low", "close", "volume"]
        new_raw = new_after[["date", "open_raw", "high_raw", "low_raw",
                             "close_raw", "volume_raw"]].copy()
        new_raw.columns = raw_cols
        extended_raw = pd.concat([frozen_raw[raw_cols], new_raw], ignore_index=True)
        extended_raw = extended_raw.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        extended_raw.to_csv(raw_csv, index=False)

        # Extend adjusted OHLCV
        adj_cols = ["date", "open", "high", "low", "close",
                    "volume", "factor", "adjustment_anchor_date",
                    "adjustment_anchor_factor", "price_role"]
        # For new rows, carry forward the last factor
        last_factor = frozen_adj["factor"].iloc[-1]
        last_anchor_date = frozen_adj["adjustment_anchor_date"].iloc[-1]
        last_anchor_factor = frozen_adj["adjustment_anchor_factor"].iloc[-1]
        new_adj = new_after[["date", "open_adj", "high_adj", "low_adj",
                             "close_adj"]].copy()
        new_adj.columns = ["date", "open", "high", "low", "close"]
        new_adj["volume"] = new_after["volume_raw"]
        new_adj["factor"] = last_factor
        new_adj["adjustment_anchor_date"] = last_anchor_date
        new_adj["adjustment_anchor_factor"] = last_anchor_factor
        new_adj["price_role"] = "adjusted_feature_and_label"
        extended_adj = pd.concat([frozen_adj[adj_cols], new_adj[adj_cols]], ignore_index=True)
        extended_adj = extended_adj.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        extended_adj.to_csv(adj_csv, index=False)

        # Extend session audit
        new_session_rows = []
        for _, row in new_after.iterrows():
            date_str = row["date"].strftime("%Y-%m-%d")
            obs_path = args.paired_store / "observations" / f"{date_str}.json"
            eligible = False
            if obs_path.exists():
                obs = json.loads(obs_path.read_text(encoding="utf-8"))
                eligible = bool(obs.get("common_open_eligible", False))
            new_session_rows.append({"date": row["date"], "open_research_eligible": eligible})
        new_session = pd.DataFrame(new_session_rows)
        new_session["date"] = pd.to_datetime(new_session["date"])
        extended_session = pd.concat([frozen_session, new_session], ignore_index=True)
        extended_session = extended_session.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        extended_session.to_csv(session_path, index=False)

        # Update manifest
        new_cutoff = extended_adj["date"].max().strftime("%Y-%m-%d")
        manifest = dict(frozen_manifest)
        manifest["cutoff"] = new_cutoff
        manifest["rows"] = int(len(extended_adj))
        manifest["last_date"] = new_cutoff
        manifest["schema_version"] = "cn_etf_canonical_total_return_v2"

        new_raw_bytes = raw_csv.read_bytes()
        new_adj_bytes = adj_csv.read_bytes()
        new_session_bytes = session_path.read_bytes()
        manifest["raw_sha256"] = hashlib.sha256(new_raw_bytes).hexdigest()
        manifest["adjusted_sha256"] = hashlib.sha256(new_adj_bytes).hexdigest()
        manifest["session_audit_sha256"] = hashlib.sha256(new_session_bytes).hexdigest()

        manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        manifest["manifest_sha256"] = hashlib.sha256(manifest_json).hexdigest()
        manifest_path.write_bytes(manifest_json)

        # Repack zip
        new_zip_path = tmp_path / "v2_artifact.zip"
        with zipfile.ZipFile(new_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in tmp_path.iterdir():
                if f.is_file() and f.name != "v2_artifact.zip" and f.name != "artifact.zip":
                    zf.write(f, arcname=f.name)

        # Encode to base64
        new_b64 = base64.b64encode(new_zip_path.read_bytes())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(new_b64)

    output_sha = compute_sha256(new_zip_path.read_bytes() if new_zip_path.exists() else b"")
    print(f"\nETF canonical v2 artifact written: {args.output}")
    print(f"Zip SHA256: {output_sha}")
    print(f"Cutoff: {new_cutoff}")


if __name__ == "__main__":
    main()
