"""Deterministic, non-overlapping Colab campaign assignments (no scheduler).

The agent freezes a batch with the existing canonical runner. Each separately
launched Colab session receives ONE assigned shard. No live queue, polling,
lease-stealing, cross-session writer, model fitting, or trade promotion here.

`merge_shards` verifies the independently transported per-window ZIPs and seals
one merged, still-unreviewed evidence set; it never ranks or selects winners.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError

SCHEMA = "p2_colab_campaign_shards_v1"
ID = re.compile(r"[a-z][a-z0-9_-]{2,63}")
TRIAL_FILES = ("study-receipt.json", "study-spec.json", "trial-result.json")


class ShardMergeError(ExchangeError):
    """A cross-window shard merge failed full-coverage/identity verification."""


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


def _pin_values(pin: Any, shard_id: str) -> tuple[Path, str, str]:
    """Resolve one externally pinned transport ZIP without trusting its shape."""
    if not isinstance(pin, dict):
        raise ShardMergeError(f"invalid shard pin: {shard_id}")
    try:
        archive = Path(pin["archive"])
        archive_sha256 = pin["archive_sha256"]
        index_sha256 = pin["index_sha256"]
    except (KeyError, TypeError) as exc:
        raise ShardMergeError(f"incomplete shard pin: {shard_id}") from exc
    if not isinstance(archive_sha256, str) or not isinstance(index_sha256, str):
        raise ShardMergeError(f"invalid shard pin hashes: {shard_id}")
    return archive, archive_sha256, index_sha256


def _shard_member_trials(archive: Path, batch_id: str) -> set[str]:
    """Re-read an already verified ZIP for duplicate/incomplete trial inventory."""
    prefix = f"{batch_id}/trials/"
    inventory: dict[str, list[str]] = {}
    with zipfile.ZipFile(archive) as pack:
        names = [info.filename for info in pack.infolist()]
    if len(names) != len(set(names)):
        raise ShardMergeError("duplicate shard archive member")
    for name in names:
        if name in (f"{batch_id}/batch-plan.json", "checkpoint-index.json"):
            continue
        if not name.startswith(prefix):
            raise ShardMergeError("unexpected shard archive member")
        trial_id, _, member = name[len(prefix):].partition("/")
        if not trial_id or member not in TRIAL_FILES:
            raise ShardMergeError("unexpected shard trial member")
        inventory.setdefault(trial_id, []).append(member)
    for trial_id, members in inventory.items():
        if len(members) != len(TRIAL_FILES) or set(members) != set(TRIAL_FILES):
            raise ShardMergeError(f"incomplete shard trial evidence: {trial_id}")
    return set(inventory)


def merge_shards(*, batch_spec: Path, data_root: Path, manifest: dict,
                 shard_pins: dict[str, dict[str, Any]],
                 output_root: Path, archive: Path) -> dict:
    """Merge independently transported shard ZIPs into one sealed unreviewed set.

    Every shard must restore to exactly its frozen assignment; the union must
    equal the full batch; inputs stay untouched; the merged set is resealed with
    the existing checkpoint archive format and is never ranked.
    """
    from src.research import colab_experiment_batch as core

    if not isinstance(manifest, dict) or not isinstance(shard_pins, dict):
        raise ShardMergeError("invalid shard manifest or pins")
    batch = core._inputs(batch_spec, data_root)[0]
    try:
        expected = compile_shards(batch, manifest.get("shard_count"))
    except ExchangeError as exc:
        raise ShardMergeError(f"invalid frozen shard manifest: {exc}") from exc
    if manifest != expected:
        raise ShardMergeError("frozen shard manifest differs from canonical batch plan")

    planned_ids = [s["shard_id"] for s in expected["shards"]]
    if set(shard_pins) != set(planned_ids):
        raise ShardMergeError(
            "shard pins must exactly cover planned shards: "
            f"missing={sorted(set(planned_ids) - set(shard_pins))} "
            f"extra={sorted(set(shard_pins) - set(planned_ids))}")

    if output_root.exists() or output_root.is_symlink():
        raise ShardMergeError("merged output root must be fresh")
    if archive.exists() or archive.is_symlink():
        raise ShardMergeError("merged archive must be fresh")
    if archive.resolve().is_relative_to(output_root.resolve()):
        raise ShardMergeError("merged archive must be outside the merged output root")
    core._outside_checkout(output_root)
    core._outside_checkout(archive)

    assignments = {s["shard_id"]: set(s["trial_ids"]) for s in expected["shards"]}
    all_trial_ids = {t["trial_id"] for t in batch["trials"]}
    seen: set[str] = set()
    statuses: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="p2-shard-merge-") as temporary:
        scratch = Path(temporary)
        for shard_id in sorted(assignments):
            restored = scratch / shard_id
            archive_path, archive_pin, index_pin = _pin_values(shard_pins[shard_id], shard_id)
            core.restore_archive(
                batch_spec=batch_spec, data_root=data_root, archive=archive_path,
                expected_archive_sha256=archive_pin, expected_index_sha256=index_pin,
                output_root=restored)
            members = _shard_member_trials(archive_path, batch["batch_id"])
            trials_root = restored / batch["batch_id"] / "trials"
            restored_ids = (sorted(p.name for p in trials_root.iterdir())
                            if trials_root.is_dir() else [])
            if any(not (trials_root / trial_id).is_dir() for trial_id in restored_ids):
                raise ShardMergeError(f"unexpected non-directory shard trial entry: {shard_id}")
            assigned = assignments[shard_id]
            if set(restored_ids) != assigned or members != assigned:
                raise ShardMergeError(
                    f"shard {shard_id} trial assignment mismatch: "
                    f"missing={sorted(assigned - set(restored_ids))} "
                    f"extra={sorted(set(restored_ids) - assigned)}")
            duplicates = seen & assigned
            if duplicates:
                raise ShardMergeError(f"duplicate trial identity across shards: {sorted(duplicates)}")
            seen |= assigned
            for trial_id in sorted(assigned):
                directory = trials_root / trial_id
                files = sorted(p.name for p in directory.iterdir())
                if files != list(TRIAL_FILES) or any(not (directory / n).is_file() for n in files):
                    raise ShardMergeError(f"incomplete shard trial evidence: {shard_id}/{trial_id}")
                wrapper = json.loads((directory / "trial-result.json").read_text(encoding="utf-8"))
                if wrapper.get("study_status") not in ("ready", "blocked"):
                    raise ShardMergeError(f"invalid shard trial status: {shard_id}/{trial_id}")
                statuses[trial_id] = wrapper["study_status"]
        if seen != all_trial_ids:
            raise ShardMergeError(
                "merged shard union differs from batch trials: "
                f"missing={sorted(all_trial_ids - seen)}")

        output_root.mkdir(parents=True, exist_ok=False)
        base = output_root / batch["batch_id"]
        core._write_new(base / "batch-plan.json", batch)
        for shard_id in sorted(assignments):
            for trial_id in sorted(assignments[shard_id]):
                destination = base / "trials" / trial_id
                destination.mkdir(parents=True, exist_ok=False)
                source = scratch / shard_id / batch["batch_id"] / "trials" / trial_id
                for name in TRIAL_FILES:
                    shutil.copyfile(source / name, destination / name)
        sealed = core.checkpoint_archive(
            batch_spec=batch_spec, data_root=data_root,
            output_root=output_root, archive=archive)

    ready = sum(status == "ready" for status in statuses.values())
    return {
        "status": "SHARD_MERGE_SEALED_UNREVIEWED",
        "batch_id": batch["batch_id"],
        "manifest_sha256": expected["manifest_sha256"],
        "shard_count": expected["shard_count"],
        "shard_ids": sorted(assignments),
        "trial_count": len(all_trial_ids),
        "ready": ready,
        "blocked": len(statuses) - ready,
        "merged_root": str(output_root),
        "archive": str(archive),
        "archive_sha256": sealed["archive_sha256"],
        "archive_size_bytes": sealed["archive_size_bytes"],
        "index_sha256": sealed["index_sha256"],
        "index_files": sealed["files"],
        "review_status": "incoming_unreviewed",
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
        "ranking_performed": False,
        "winner_claimed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify", "merge"))
    parser.add_argument("--batch-spec", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--shard-pins", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "merge":
            required = {"data-root": args.data_root, "shard-pins": args.shard_pins,
                        "output-root": args.output_root, "archive": args.archive}
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise ExchangeError(f"merge requires {', '.join('--' + name for name in missing)}")
            result = merge_shards(
                batch_spec=args.batch_spec, data_root=args.data_root,
                manifest=json.loads(args.manifest.read_text(encoding="utf-8")),
                shard_pins=json.loads(args.shard_pins.read_text(encoding="utf-8")),
                output_root=args.output_root, archive=args.archive)
            print(json.dumps(result, indent=2))
            return 0
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
    except (ExchangeError, OSError, ValueError, KeyError, TypeError,
            zipfile.BadZipFile) as exc:
        print(f"BLOCKED_SHARD_CONTRACT: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
