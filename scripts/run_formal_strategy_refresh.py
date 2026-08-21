"""Execute exactly one active strategy refresh task from a formal Bundle v2 plan."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.ranker_provisional_mtm import attach_ranker_provisional_mtm
from src.artifacts.formal_bundle_reader import load_formal_run
from src.artifacts.formal_preview_builder import (
    build_preview_bundle,
    project_provisional_mtm_preview,
)
from src.artifacts.formal_refresh import load_object, sha256, write_object
from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.artifacts.model_run_exporter import update_catalog
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import (
    load_active_strategy_runtime_capabilities,
)
from src.research.formal_model_replay import replay_byd_v1_3
from src.research.qqq_authoritative_replay import verify_qqq_authoritative_replay

RECEIPT_SCHEMA = "formal_strategy_refresh_receipt_v2"
PLAN_SCHEMA = "formal_refresh_plan_v5"
QQQ_MODEL_ID = "qqqi_qqq_tqqq_v4_3"
US_MODEL_ID = "us_x1_3"
CN_X1_2_MODEL_ID = "cn_x1_2"
BYD_MODEL_ID = "byd_v1_3_recovery_event_low_vol_confirmation_v1"
BYD_PREDECESSOR = Path(
    "data/research/historical_model_evidence/byd_v1_2_convex_momentum_budget_v1.json"
)


class StrategyRefreshBlocked(RuntimeError):
    """Raised when one strategy cannot produce publishable governed evidence."""

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _run(command: Sequence[str], *, cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _verify_append_only_prefix(
    current: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, int]:
    observed: dict[str, int] = {}
    for field in ("report", "positions", "trades"):
        before = current.get(field)
        after = candidate.get(field)
        if not isinstance(before, list) or not isinstance(after, list):
            raise StrategyRefreshBlocked("invalid_evidence", f"CN x1.2 {field} is missing")
        if len(after) < len(before) or after[: len(before)] != before:
            raise StrategyRefreshBlocked(
                "invalid_evidence", f"CN x1.2 {field} changed before the reporting boundary"
            )
        observed[field] = len(before)
    return observed


def _task(plan_path: Path, strategy_id: str) -> dict[str, Any]:
    plan = load_object(plan_path)
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("unsupported formal refresh plan schema")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("formal refresh plan tasks are missing")
    matches = [
        dict(value)
        for value in tasks
        if isinstance(value, Mapping) and value.get("strategy_id") == strategy_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one task for strategy {strategy_id!r}")
    active = load_active_strategy_catalog().by_strategy_id.get(strategy_id)
    if active is None:
        raise ValueError(f"strategy is not active: {strategy_id}")
    capability = load_active_strategy_runtime_capabilities()[strategy_id].formal_refresh
    task = matches[0]
    expected = {
        "model_family_id": active.model_family_id,
        "model_version_id": active.model_version_id,
        "model_kind": active.model_kind,
        "market": active.market,
        "publication_input": "native_bundle_v2",
        "formal_refresh_capability_status": capability.status,
        "formal_refresh_adapter_id": capability.adapter_id,
        "formal_refresh_block_reason": capability.reason,
    }
    for field, value in expected.items():
        if task.get(field) != value:
            raise ValueError(f"plan/active strategy mismatch for {strategy_id}: {field}")
    return task


def _base_receipt(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "strategy_id": task["strategy_id"],
        "model_family_id": task["model_family_id"],
        "model_version_id": task["model_version_id"],
        "model_kind": task["model_kind"],
        "market": task["market"],
        "planned_provider_cutoff": task["planned_provider_cutoff"],
        "publication_input": "native_bundle_v2",
        "formal_refresh_required": bool(task.get("formal_refresh_required")),
        "mtm_refresh_required": bool(task.get("mtm_refresh_required")),
        "formal_refresh_capability_status": task["formal_refresh_capability_status"],
        "formal_refresh_adapter_id": task.get("formal_refresh_adapter_id"),
        "formal_refresh_block_reason": task.get("formal_refresh_block_reason"),
        "research_only": True,
        "trade_ready": False,
    }


def _preview_record(root: Path, model_id: str) -> Mapping[str, Any] | None:
    catalog_path = root / "catalog.json"
    if not catalog_path.is_file():
        return None
    catalog = load_object(catalog_path)
    validate_catalog(catalog)
    if catalog.get("channel") != "preview":
        return None
    rows = catalog.get("records")
    if not isinstance(rows, list):
        return None
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("model_version_id") == model_id
    ]
    return matches[0] if len(matches) == 1 else None


def _current_preview_bundle_id(root: Path, model_id: str) -> str | None:
    record = _preview_record(root, model_id)
    return str(record.get("bundle_id") or "") or None if record is not None else None


def _materialize_refresh_state(
    *, root: Path, formal_v2_root: Path, model_id: str, target: Path
) -> dict[str, Any]:
    relative_root = formal_v2_root.resolve().relative_to(root)
    state = load_formal_run(root, model_id, relative_root=relative_root).refresh_state()
    state["schema_version"] = "1.0.0"
    state["record_type"] = "formal_model_backtest"
    state["publication_status"] = "accepted_formal_baseline"
    write_object(target, state)
    return state


def _seal_preview(
    *,
    root: Path,
    task: Mapping[str, Any],
    evidence_path: Path,
    result_root: Path,
    base_preview_root: Path | None = None,
) -> tuple[str, str]:
    strategy = load_active_strategy_catalog().by_strategy_id[str(task["strategy_id"])]
    preview_root = result_root / "model-runs"
    if preview_root.exists():
        shutil.rmtree(preview_root)
    base_preview_run = None
    if base_preview_root is not None:
        record = _preview_record(base_preview_root, strategy.model_version_id)
        if record is None:
            raise StrategyRefreshBlocked(
                "invalid_evidence", "base preview bundle is missing"
            )
        manifest_path = base_preview_root / str(record["manifest_path"])
        if (
            not manifest_path.is_file()
            or sha256(manifest_path) != record.get("manifest_sha256")
        ):
            raise StrategyRefreshBlocked(
                "invalid_evidence", "base preview manifest identity changed"
            )
        base_preview_run = manifest_path.parent
    if base_preview_run is None:
        manifest = build_preview_bundle(
            evidence_path,
            strategy,
            output_root=preview_root,
        )
    else:
        manifest = project_provisional_mtm_preview(
            evidence_path,
            strategy,
            base_preview_run=base_preview_run,
            output_root=preview_root,
        )
    catalog = update_catalog(
        [manifest], catalog_path=preview_root / "catalog.json", channel="preview"
    )
    rows = catalog.get("records")
    if not isinstance(rows, list) or len(rows) != 1:
        raise StrategyRefreshBlocked("invalid_evidence", "strategy preview catalog is invalid")
    record = rows[0]
    if not isinstance(record, Mapping) or record.get("model_version_id") != strategy.model_version_id:
        raise StrategyRefreshBlocked("invalid_evidence", "strategy preview identity changed")
    return sha256(preview_root / "catalog.json"), str(record.get("bundle_id") or "")


def _run_us(
    *,
    root: Path,
    task: Mapping[str, Any],
    provider_root: Path,
    formal_v2_root: Path,
    current_preview_root: Path,
    result_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    formal_required = bool(task.get("formal_refresh_required"))
    mtm_required = bool(task.get("mtm_refresh_required"))
    if not formal_required and not mtm_required:
        return {
            **_base_receipt(task),
            "execution_status": "current_no_change",
            "replay_verdict": "not_required_current_identity",
        }

    cutoff = str(task["planned_provider_cutoff"])
    provider_dir = provider_root / "data" / "providers" / "us"
    current_id = _current_preview_bundle_id(current_preview_root, US_MODEL_ID)

    if formal_required:
        candidate = result_root / "model-runs"
        _run(
            [
                sys.executable,
                "scripts/build_us_x1_3_preview.py",
                "--root",
                str(root),
                "--provider-dir",
                str(provider_dir),
                "--generated-at",
                generated_at,
                "--output-root",
                str(candidate),
            ],
            cwd=root,
        )
        candidate_id = _current_preview_bundle_id(candidate, US_MODEL_ID)
        if candidate_id is None:
            raise StrategyRefreshBlocked("invalid_evidence", "US x1.3 preview catalog is missing")
        changed = current_id != candidate_id
        return {
            **_base_receipt(task),
            "execution_status": "refreshed" if changed else "current_no_change",
            "candidate_bundle_id": candidate_id,
            "current_bundle_id": current_id,
            "output_sha256": sha256(candidate / "catalog.json"),
            "replay_verdict": "deterministic_native_bundle_rebuild",
        }

    with tempfile.TemporaryDirectory(prefix="us-ranker-mtm-") as temporary:
        package = Path(temporary) / "candidate.json"
        _materialize_refresh_state(
            root=root,
            formal_v2_root=formal_v2_root,
            model_id=US_MODEL_ID,
            target=package,
        )
        provisional = attach_ranker_provisional_mtm(
            package_path=package,
            provider_dir=provider_dir,
            ledger_dir=root / "data/research/strategy_signal_ledgers" / US_MODEL_ID,
            cutoff=cutoff,
        )
        if provisional is None:
            raise StrategyRefreshBlocked(
                "invalid_evidence",
                "US x1.3 MTM fast path was planned but produced no valuation observation",
            )
        candidate_state = load_object(package)
        output_sha, bundle_id = _seal_preview(
            root=root,
            task=task,
            evidence_path=package,
            result_root=result_root,
            base_preview_root=current_preview_root,
        )
    return {
        **_base_receipt(task),
        "execution_status": "refreshed",
        "candidate_evidence_cutoff": candidate_state.get("evidence_cutoff"),
        "performance_observation_end": _mapping(candidate_state.get("freshness")).get(
            "latest_mtm_date"
        ),
        "candidate_bundle_id": bundle_id,
        "current_bundle_id": current_id,
        "output_sha256": output_sha,
        "replay_verdict": "ledger_mtm_projection_no_historical_rebuild",
    }


def _run_qqq(
    *,
    root: Path,
    task: Mapping[str, Any],
    formal_v2_root: Path,
    result_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    if not bool(task.get("formal_refresh_required")):
        return {
            **_base_receipt(task),
            "execution_status": "current_no_change",
            "replay_verdict": "not_required_current_identity",
        }
    if not os.environ.get("TIINGO_API_TOKEN"):
        raise StrategyRefreshBlocked(
            "data_blocked",
            "QQQ refresh requires TIINGO_API_TOKEN for the governed professional ETF bundle",
        )

    cutoff = str(task["planned_provider_cutoff"])
    bundle = result_root / "qqq-bundle"
    with tempfile.TemporaryDirectory(prefix="qqq-refresh-state-") as temporary:
        current = Path(temporary) / "current.json"
        package = Path(temporary) / "candidate.json"
        _materialize_refresh_state(
            root=root, formal_v2_root=formal_v2_root, model_id=QQQ_MODEL_ID, target=current
        )
        _run(
            [
                sys.executable,
                "scripts/data/build_etf_reference_bundle.py",
                "--end-date",
                cutoff,
                "--output-root",
                str(bundle),
                "--require-professional",
            ],
            cwd=root,
        )
        _run(
            [
                sys.executable,
                "scripts/refresh_qqq_v4_3_formal.py",
                "--current-package",
                str(current),
                "--bundle-dir",
                str(bundle),
                "--cutoff",
                cutoff,
                "--generated-at",
                generated_at,
                "--output",
                str(package),
            ],
            cwd=root,
        )
        try:
            replay = verify_qqq_authoritative_replay(root, package_path=package, bundle_dir=bundle)
        except (ValueError, KeyError, OSError) as exc:
            raise StrategyRefreshBlocked("invalid_evidence", str(exc)) from exc
        if replay.get("decision") != "exact_replay":
            raise StrategyRefreshBlocked(
                "invalid_evidence", f"QQQ replay verdict: {replay.get('decision')}"
            )
        candidate = load_object(package)
        output_sha, bundle_id = _seal_preview(
            root=root, task=task, evidence_path=package, result_root=result_root
        )
    return {
        **_base_receipt(task),
        "execution_status": "refreshed",
        "candidate_evidence_cutoff": candidate.get("evidence_cutoff"),
        "performance_observation_end": _mapping(candidate.get("date_range")).get("end"),
        "candidate_bundle_id": bundle_id,
        "output_sha256": output_sha,
        "replay_verdict": "exact_replay",
    }


def _build_cn_x1_2_duplicate_ledgers(
    *, root: Path, provider_dir: Path, result_root: Path, cutoff: str
) -> tuple[Path, Path]:
    outputs: list[Path] = []
    for suffix in ("a", "b"):
        ledger = result_root / f"cn-x1-2-ledger-{suffix}" / "score-ledger.csv.gz"
        _run(
            [
                sys.executable,
                "scripts/build_cn_x1_2_prospective_ledger.py",
                "--repository-root",
                str(root),
                "--provider-dir",
                str(provider_dir),
                "--cutoff",
                cutoff,
                "--output",
                str(ledger),
            ],
            cwd=root,
        )
        outputs.append(ledger)
    if not all(path.is_file() for path in outputs):
        raise StrategyRefreshBlocked(
            "invalid_evidence", "CN x1.2 duplicate score ledgers are missing"
        )
    return outputs[0], outputs[1]


def _run_cn_x1_2(
    *,
    root: Path,
    task: Mapping[str, Any],
    provider_root: Path,
    formal_v2_root: Path,
    result_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    if not bool(task.get("formal_refresh_required")):
        return {
            **_base_receipt(task),
            "execution_status": "current_no_change",
            "replay_verdict": "not_required_current_identity",
        }

    cutoff = str(task["planned_provider_cutoff"])
    provider_dir = provider_root / "data" / "providers" / "cn"
    provider_manifest = provider_root / "artifacts" / "selected_pool_price_refresh_manifest.json"
    ledger_a, ledger_b = _build_cn_x1_2_duplicate_ledgers(
        root=root,
        provider_dir=provider_dir,
        result_root=result_root,
        cutoff=cutoff,
    )
    with tempfile.TemporaryDirectory(prefix="cn-x1-2-refresh-state-") as temporary:
        current_package = Path(temporary) / "current.json"
        package = Path(temporary) / "candidate.json"
        current_state = _materialize_refresh_state(
            root=root,
            formal_v2_root=formal_v2_root,
            model_id=CN_X1_2_MODEL_ID,
            target=current_package,
        )
        _run(
            [
                sys.executable,
                "scripts/refresh_ranker_formal.py",
                "cn",
                "--repository-root",
                str(root),
                "--current-package",
                str(current_package),
                "--provider-dir",
                str(provider_dir),
                "--provider-manifest",
                str(provider_manifest),
                "--ledger-a",
                str(ledger_a),
                "--ledger-b",
                str(ledger_b),
                "--cutoff",
                cutoff,
                "--generated-at",
                generated_at,
                "--model-id",
                CN_X1_2_MODEL_ID,
                "--exposure-policy",
                "breadth_scaled",
                "--refresh-adapter",
                "refresh_ranker_formal.cn_x1_2",
                "--trade-reason",
                "cn_x1_2_breadth_scaled_reporting_rebalance",
                "--output",
                str(package),
            ],
            cwd=root,
        )
        candidate = load_object(package)
        prefix = _verify_append_only_prefix(current_state, candidate)
        evidence = _mapping(candidate.get("evidence"))
        if evidence.get("model_selection_reopened") is not False:
            raise StrategyRefreshBlocked(
                "invalid_evidence", "CN x1.2 refresh reopened model selection"
            )
        output_sha, bundle_id = _seal_preview(
            root=root, task=task, evidence_path=package, result_root=result_root
        )
    freshness = _mapping(candidate.get("freshness"))
    return {
        **_base_receipt(task),
        "execution_status": "refreshed",
        "candidate_evidence_cutoff": candidate.get("evidence_cutoff"),
        "performance_observation_end": freshness.get("latest_realized_holding_end"),
        "candidate_bundle_id": bundle_id,
        "output_sha256": output_sha,
        "replay_verdict": {
            "frozen_prefix_rows": prefix,
            "duplicate_score_ledger_sha256": sha256(ledger_a),
            "model_selection_reopened": False,
        },
    }


def _extract_byd_inputs(root: Path, result_root: Path) -> tuple[Path, Path]:
    byd_base = result_root / "input" / "byd"
    etf_base = result_root / "input" / "515180"
    byd_base.mkdir(parents=True, exist_ok=True)
    etf_base.mkdir(parents=True, exist_ok=True)
    with tarfile.open(root / "data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz") as archive:
        archive.extractall(byd_base, filter="data")
    encoded = (root / "data/research/515180_canonical_v1_artifact.zip.b64").read_bytes()
    archive_path = result_root / "515180.zip"
    archive_path.write_bytes(base64.b64decode(encoded))
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(etf_base)
    return byd_base, etf_base


def _run_byd(
    *,
    root: Path,
    task: Mapping[str, Any],
    formal_v2_root: Path,
    result_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    if not bool(task.get("formal_refresh_required")):
        return {
            **_base_receipt(task),
            "execution_status": "current_no_change",
            "replay_verdict": "not_required_current_identity",
        }

    incumbent = replay_byd_v1_3(root=root)
    decision = str(incumbent.get("decision") or "")
    if decision != "exact_replay":
        status = "data_blocked" if decision == "data_blocked" else "invalid_evidence"
        raise StrategyRefreshBlocked(status, f"BYD incumbent replay verdict: {decision}")

    cutoff = str(task["planned_provider_cutoff"])
    byd_base, etf_base = _extract_byd_inputs(root, result_root)
    with tempfile.TemporaryDirectory(prefix="byd-refresh-state-") as temporary:
        current = Path(temporary) / "current.json"
        package = Path(temporary) / "candidate.json"
        _materialize_refresh_state(
            root=root, formal_v2_root=formal_v2_root, model_id=BYD_MODEL_ID, target=current
        )
        _run(
            [
                sys.executable,
                "scripts/refresh_byd_v1_3_formal.py",
                "--current-package",
                str(current),
                "--predecessor-package",
                str(root / BYD_PREDECESSOR),
                "--base-byd-dir",
                str(byd_base),
                "--base-etf-dir",
                str(etf_base),
                "--shadow-store",
                str(root / "data/research/byd_prospective_shadow"),
                "--paired-store",
                str(root / "data/research/byd_515180_prospective"),
                "--signal-ledger",
                str(root / "data/research/strategy_signal_ledgers" / BYD_MODEL_ID),
                "--cutoff",
                cutoff,
                "--generated-at",
                generated_at,
                "--output",
                str(package),
            ],
            cwd=root,
        )
        candidate = load_object(package)
        output_sha, bundle_id = _seal_preview(
            root=root, task=task, evidence_path=package, result_root=result_root
        )
    return {
        **_base_receipt(task),
        "execution_status": "refreshed",
        "candidate_evidence_cutoff": candidate.get("evidence_cutoff"),
        "performance_observation_end": _mapping(candidate.get("date_range")).get("end"),
        "candidate_bundle_id": bundle_id,
        "output_sha256": output_sha,
        "replay_verdict": "exact_incumbent_replay_then_append_only_refresh",
    }


def execute_strategy(
    *,
    root: Path,
    task: Mapping[str, Any],
    provider_root: Path,
    formal_v2_root: Path,
    current_preview_root: Path,
    result_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    if not bool(task.get("formal_refresh_required")) and not bool(
        task.get("mtm_refresh_required")
    ):
        return {
            **_base_receipt(task),
            "execution_status": "current_no_change",
            "replay_verdict": "not_required_current_identity",
        }

    capability_status = str(task.get("formal_refresh_capability_status") or "")
    if capability_status != "available":
        reason = str(task.get("formal_refresh_block_reason") or "")
        raise StrategyRefreshBlocked(
            "runtime_blocked",
            reason or f"formal refresh capability is {capability_status or 'missing'}",
        )

    adapters = {
        "us_x1_3_formal_refresh_v1": lambda: _run_us(
            root=root,
            task=task,
            provider_root=provider_root,
            formal_v2_root=formal_v2_root,
            current_preview_root=current_preview_root,
            result_root=result_root,
            generated_at=generated_at,
        ),
        "cn_x1_2_formal_refresh_v1": lambda: _run_cn_x1_2(
            root=root,
            task=task,
            provider_root=provider_root,
            formal_v2_root=formal_v2_root,
            result_root=result_root,
            generated_at=generated_at,
        ),
        "qqq_v4_3_formal_refresh_v1": lambda: _run_qqq(
            root=root,
            task=task,
            formal_v2_root=formal_v2_root,
            result_root=result_root,
            generated_at=generated_at,
        ),
        "byd_v1_3_formal_refresh_v1": lambda: _run_byd(
            root=root,
            task=task,
            formal_v2_root=formal_v2_root,
            result_root=result_root,
            generated_at=generated_at,
        ),
    }
    adapter_id = str(task.get("formal_refresh_adapter_id") or "")
    adapter = adapters.get(adapter_id)
    if adapter is None:
        raise StrategyRefreshBlocked(
            "runtime_blocked", f"unknown formal refresh adapter: {adapter_id or 'missing'}"
        )
    return adapter()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--provider-root", type=Path, required=True)
    parser.add_argument("--formal-v2-root", type=Path, required=True)
    parser.add_argument("--current-preview-root", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/formal-refresh/strategy-result"),
    )
    args = parser.parse_args()

    root = Path.cwd().resolve()
    task = _task(args.plan, args.strategy_id)
    result_root = args.output_root / args.strategy_id
    if result_root.exists():
        shutil.rmtree(result_root)
    result_root.mkdir(parents=True)
    receipt_path = result_root / "receipt.json"

    try:
        receipt = execute_strategy(
            root=root,
            task=task,
            provider_root=args.provider_root.resolve(),
            formal_v2_root=args.formal_v2_root.resolve(),
            current_preview_root=args.current_preview_root.resolve(),
            result_root=result_root.resolve(),
            generated_at=args.generated_at,
        )
    except StrategyRefreshBlocked as exc:
        receipt = {
            **_base_receipt(task),
            "execution_status": exc.status,
            "reason": exc.reason,
        }
        write_object(receipt_path, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        receipt = {
            **_base_receipt(task),
            "execution_status": "execution_failed",
            "reason": str(exc),
        }
        write_object(receipt_path, receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 1

    write_object(receipt_path, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
