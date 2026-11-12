"""Deterministic, non-overlapping Colab campaign assignments (no scheduler).

The agent freezes a batch with the existing canonical runner. Each separately
launched Colab session receives ONE assigned shard. No live queue, polling,
lease-stealing, cross-session writer, model fitting, or trade promotion here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError

SCHEMA = "p2_colab_campaign_shards_v1"
ID = re.compile(r"[a-z][a-z0-9_-]{2,63}")


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def compile_shards(batch: dict, shard_count: int) -> dict:
    """Allocate complete trial identities before any cloud session starts."""
    if (
        not isinstance(batch, dict)
        or batch.get("research_only") is not True
        or batch.get("trade_ready") is not False
        or batch.get("pit_certified") is not False
        or not isinstance(shard_count, int)
        or isinstance(shard_count, bool)
        or not 1 <= shard_count <= 8
    ):
        raise ExchangeError("unsupported research campaign or shard count")
    entries = batch.get("trials", [])
    ids = [t["trial_id"] for t in entries]
    if not ids or len(set(ids)) != len(ids) or shard_count > len(ids):
        raise ExchangeError("empty/duplicate trials or excessive shard count")
    if not ID.fullmatch(str(batch.get("batch_id", ""))):
        raise ExchangeError("invalid batch ID")
    # Do not choose shards from return statistics: stable round-robin by ID.
    sorted_ids = sorted(ids)
    shards = []
    for i in range(shard_count):
        selected = sorted_ids[i::shard_count]
        shards.append({
            "shard_id": f"s{i + 1:02d}",
            "trial_ids": selected,
            "trial_ids_sha256": _sha(selected),
            "output_namespace": f"{batch['batch_id']}/s{i + 1:02d}",
            "trial_count": len(selected),
        })
    core = {
        "schema_version": SCHEMA,
        "batch_id": batch["batch_id"],
        "batch_spec_sha256": batch["batch_spec_sha256"],
        "runner_git_sha": batch["runner_git_sha"],
        "source_identity": batch["data"],
        "campaign_trial_count": len(sorted_ids),
        "campaign_trial_ids_sha256": _sha(sorted_ids),
        "shard_count": shard_count,
        "shards": shards,
        "partition_method": "sorted_trial_id_round_robin_v1",
        "execution": "owner_launched_independent_notebooks_only",
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
        "review_status": "unreviewed_shard_assignments",
    }
    return {**core, "manifest_sha256": _sha(core)}


def assigned_trial_ids(manifest: dict, batch: dict, shard_id: str) -> frozenset[str]:
    """Reject mismatched manifests, overlapping identities, or unknown shards."""
    if not isinstance(manifest, dict) or not ID.fullmatch(str(shard_id)):
        raise ExchangeError("invalid shard manifest or shard ID")
    expected = compile_shards(batch, manifest.get("shard_count"))
    if manifest != expected:
        raise ExchangeError("frozen shard contract does not match canonical batch")
    selected = [s for s in expected["shards"] if s["shard_id"] == shard_id]
    if len(selected) != 1:
        raise ExchangeError("unknown shard ID")
    return frozenset(selected[0]["trial_ids"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--batch-spec", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--shard-count", type=int)
    args = parser.parse_args(argv)
    try:
        from src.research.colab_experiment_batch import plan

        batch = plan(json.loads(args.batch_spec.read_text(encoding="utf-8")))
        if args.action == "create":
            if args.shard_count is None:
                raise ExchangeError("shard count required for create")
            manifest = compile_shards(batch, args.shard_count)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            with args.manifest.open("x", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2)
        else:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            if manifest != compile_shards(batch, manifest.get("shard_count")):
                raise ExchangeError("manifest/batch identity mismatch")
        print(json.dumps({
            "status": "SHARD_PLAN_VERIFIED_NOT_EXECUTED",
            "manifest_sha256": manifest["manifest_sha256"],
            "shard_count": manifest["shard_count"],
            "trial_count": manifest["campaign_trial_count"],
            "assignments": [
                {"shard_id": s["shard_id"], "count": s["trial_count"]}
                for s in manifest["shards"]
            ],
            "research_only": True,
            "trade_ready": False,
        }, indent=2))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"BLOCKED_SHARD_CONTRACT: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
