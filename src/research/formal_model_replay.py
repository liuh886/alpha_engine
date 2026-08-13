from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from scripts.byd_formal_refresh_common import extend_byd_input, extend_etf_input
from scripts.byd_v1_3_formal_builder import build_package as build_byd_package
from src.artifacts.formal_bundle_reader import FormalBundleReadError, load_formal_run
from src.artifacts.formal_refresh import load_object
from src.artifacts.qqq_v4_3_formal import (
    JOINT_STRATEGY,
    MODEL_ID as QQQ_MODEL_ID,
    build_formal_package as build_qqq_package,
)
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.data.data_recipe import DataRecipeError, prepare_data_recipe
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID as BYD_MODEL_ID
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.replay_comparison import compare_package_sections
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison

RUNNER_ID = "formal_model_replay_v2"
QQQ_REPLAY_ID = "qqq_v4_3"
BYD_REPLAY_ID = "byd_v1_3"
REPLAY_IDS = (QQQ_REPLAY_ID, BYD_REPLAY_ID)

BYD_PREDECESSOR_PACKAGE = Path(
    "data/research/formal_backtests/byd_v1_2_convex_momentum_budget_v1.json"
)
BYD_SNAPSHOT = Path("data/research/byd_canonical_v1_snapshot.tar.xz")
ETF_ARTIFACT = Path("data/research/515180_canonical_v1_artifact.zip.b64")
BYD_SHADOW_STORE = Path("data/research/byd_prospective_shadow")
ETF_PAIRED_STORE = Path("data/research/byd_515180_prospective")
BYD_SIGNAL_LEDGER = (
    Path("data/research/strategy_signal_ledgers")
    / "byd_v1_3_recovery_event_low_vol_confirmation_v1"
)
QQQ_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
QQQ_RECIPE_ID = "qqq-rotation-sgov"


class FormalModelReplayError(ValueError):
    """Raised when a formal replay contract is structurally invalid."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FormalModelReplayError(f"expected JSON object: {path}")
    return payload


def _resolve(root: Path, relative: Path) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def _historical_predecessor(root: Path) -> dict[str, Any]:
    path = _resolve(root, BYD_PREDECESSOR_PACKAGE)
    if not path.is_file():
        raise FormalModelReplayError(f"BYD v1.2 historical evidence is missing: {path}")
    package = _load_json(path)
    if package.get("model_id") != "byd_v1_2_convex_momentum_budget_v1":
        raise FormalModelReplayError("BYD v1.2 historical evidence identity is invalid")
    if package.get("research_only") is not True or package.get("trade_ready") is not False:
        raise FormalModelReplayError("BYD v1.2 historical evidence violates research boundary")
    return package


def _receipt(
    *,
    replay_id: str,
    model_id: str,
    baseline: Mapping[str, Any] | None,
    decision: str,
    reason: str | None = None,
    comparison: Mapping[str, Any] | None = None,
    data_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    completed = decision == "exact_replay"
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "runner": RUNNER_ID,
        "replay_id": replay_id,
        "model_version_id": model_id,
        "status": "completed" if completed else "blocked",
        "decision": decision,
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
    if baseline is not None:
        payload["baseline"] = dict(baseline)
    if reason:
        payload["reason"] = reason
    if comparison is not None:
        payload["trace_reproduction"] = dict(comparison)
    if data_identity is not None:
        payload["data_identity"] = dict(data_identity)
    return payload


def replay_qqq_v4_3(
    *,
    root: str | Path,
    refresh_data: bool = False,
) -> dict[str, Any]:
    normalized_root = Path(root).resolve()
    try:
        accepted = load_formal_run(normalized_root, QQQ_MODEL_ID)
        baseline = accepted.identity
        expected = accepted.replay_trace()
        cutoff = accepted.evidence_cutoff
    except (FileNotFoundError, FormalBundleReadError, json.JSONDecodeError) as exc:
        return _receipt(
            replay_id=QQQ_REPLAY_ID,
            model_id=QQQ_MODEL_ID,
            baseline=None,
            decision="invalid_evidence",
            reason=str(exc),
        )

    try:
        prepared = prepare_data_recipe(
            QQQ_RECIPE_ID,
            root=normalized_root,
            cutoff=cutoff,
            refresh=refresh_data,
        )
        manifest_path = Path(str(prepared["product_manifest_path"])).resolve()
        strategy_root = Path(str(prepared["strategy_bundle_root"])).resolve()
        manifest = _load_json(manifest_path)
        if manifest.get("professional_source_ready") is not True:
            return _receipt(
                replay_id=QQQ_REPLAY_ID,
                model_id=QQQ_MODEL_ID,
                baseline=baseline,
                decision="data_blocked",
                reason=(
                    "QQQ v4.3 exact replay requires the professional governed ETF source; "
                    "configure TIINGO_API_TOKEN and rebuild the exact-cutoff recipe"
                ),
                data_identity={
                    "recipe_id": QQQ_RECIPE_ID,
                    "strategy_manifest_sha256": _sha256(manifest_path),
                    "professional_source_ready": False,
                },
            )

        bridge_path = _resolve(normalized_root, QQQ_BRIDGE_CONTRACT)
        contract = yaml.safe_load(bridge_path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict):
            raise FormalModelReplayError("QQQ v4.3 bridge contract must be a mapping")
        bars, coverage, strategy_identity = fetch_governed_etf_strategy_bars(
            symbols=["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"],
            start=str(contract["data"]["start_date"]),
            end=cutoff,
            bundle_dir=strategy_root,
        )
        fear_greed = fetch_cnn_fear_greed(end_date=cutoff)
        _, results, diagnostics = run_v4_33_comparison(
            bars,
            contract,
            fear_greed,
            cash_symbol="SGOV",
        )
        result = results[JOINT_STRATEGY]
        observed = build_qqq_package(
            result,
            bars,
            generated_at=accepted.generated_at,
            evidence_cutoff=cutoff,
            backtest_id=accepted.run_id,
            evidence={
                "replay_runner": RUNNER_ID,
                "model_selection_reopened": False,
            },
            freshness={
                "status": "replay",
                "required_cutoff": cutoff,
                "model_selection_reopened": False,
                "research_only": True,
                "trade_ready": False,
            },
        )
        comparison = compare_package_sections(expected, observed)
        fear_csv = fear_greed.sort_index().to_csv(date_format="%Y-%m-%d").encode("utf-8")
        data_identity = {
            "recipe_id": QQQ_RECIPE_ID,
            "strategy_manifest_path": str(manifest_path.relative_to(normalized_root)),
            "strategy_manifest_sha256": _sha256(manifest_path),
            "strategy_bundle_id": manifest.get("bundle_id"),
            "professional_source_ready": True,
            "strategy_identity": strategy_identity,
            "fear_greed_sha256": _sha256_bytes(fear_csv),
            "coverage_rows": int(len(coverage)),
            "retrospective_diagnostics_present": bool(diagnostics),
        }
        if not comparison["exact"]:
            return _receipt(
                replay_id=QQQ_REPLAY_ID,
                model_id=QQQ_MODEL_ID,
                baseline=baseline,
                decision="invalid_evidence",
                reason="maintained QQQ v4.3 execution does not reproduce the accepted Bundle v2 trace",
                comparison=comparison,
                data_identity=data_identity,
            )
        return _receipt(
            replay_id=QQQ_REPLAY_ID,
            model_id=QQQ_MODEL_ID,
            baseline=baseline,
            decision="exact_replay",
            comparison=comparison,
            data_identity=data_identity,
        )
    except (DataRecipeError, FileNotFoundError, OSError) as exc:
        return _receipt(
            replay_id=QQQ_REPLAY_ID,
            model_id=QQQ_MODEL_ID,
            baseline=baseline,
            decision="data_blocked",
            reason=str(exc),
        )
    except (FormalModelReplayError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return _receipt(
            replay_id=QQQ_REPLAY_ID,
            model_id=QQQ_MODEL_ID,
            baseline=baseline,
            decision="invalid_evidence",
            reason=str(exc),
        )


def _extract_byd_base_inputs(root: Path, target: Path) -> tuple[Path, Path, dict[str, str]]:
    byd_archive = _resolve(root, BYD_SNAPSHOT)
    etf_b64 = _resolve(root, ETF_ARTIFACT)
    byd_dir = target / "byd-base"
    etf_dir = target / "etf-base"
    byd_dir.mkdir()
    etf_dir.mkdir()
    with tarfile.open(byd_archive, mode="r:xz") as archive:
        archive.extractall(byd_dir, filter="data")
    decoded = base64.b64decode(etf_b64.read_bytes())
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        archive.extractall(etf_dir)
    return (
        byd_dir,
        etf_dir,
        {
            "byd_snapshot_sha256": _sha256(byd_archive),
            "etf_artifact_b64_sha256": _sha256(etf_b64),
            "etf_decoded_sha256": _sha256_bytes(decoded),
        },
    )


def _extend_byd_inputs(
    *,
    root: Path,
    temporary: Path,
    byd_base: Path,
    etf_base: Path,
    cutoff: str,
) -> tuple[Path, Path, dict[str, Any]]:
    byd_manifest = load_object(byd_base / "manifest.json")
    etf_manifest = load_object(etf_base / "manifest.json")
    byd_base_cutoff = str(byd_manifest["cutoff"])
    etf_base_cutoff = str(etf_manifest["cutoff"])
    if cutoff < byd_base_cutoff or cutoff < etf_base_cutoff:
        raise FormalModelReplayError(
            "accepted BYD cutoff predates the frozen canonical base input"
        )

    if cutoff == byd_base_cutoff:
        byd_dir = byd_base
        final_byd_manifest = byd_manifest
    else:
        byd_dir = temporary / "byd-extended"
        final_byd_manifest = extend_byd_input(
            base_dir=byd_base,
            shadow_store=_resolve(root, BYD_SHADOW_STORE),
            cutoff=cutoff,
            output_dir=byd_dir,
        )

    if cutoff == etf_base_cutoff:
        etf_dir = etf_base
        final_etf_manifest = etf_manifest
    else:
        etf_dir = temporary / "etf-extended"
        final_etf_manifest = extend_etf_input(
            base_dir=etf_base,
            paired_store=_resolve(root, ETF_PAIRED_STORE),
            cutoff=cutoff,
            output_dir=etf_dir,
        )

    if str(final_byd_manifest["cutoff"]) != cutoff:
        raise FormalModelReplayError("BYD governed input did not reach accepted cutoff")
    if str(final_etf_manifest["cutoff"]) != cutoff:
        raise FormalModelReplayError("515180 governed input did not reach accepted cutoff")
    return byd_dir, etf_dir, {
        "byd_manifest_sha256": str(final_byd_manifest["manifest_sha256"]),
        "etf_manifest_sha256": str(final_etf_manifest["manifest_sha256"]),
        "byd_schema_version": str(final_byd_manifest["schema_version"]),
        "etf_schema_version": str(final_etf_manifest["schema_version"]),
    }


def replay_byd_v1_3(*, root: str | Path) -> dict[str, Any]:
    normalized_root = Path(root).resolve()
    try:
        accepted = load_formal_run(normalized_root, BYD_MODEL_ID)
        baseline = accepted.identity
        expected = accepted.replay_trace()
        predecessor = _historical_predecessor(normalized_root)
        cutoff = accepted.evidence_cutoff
    except (
        FileNotFoundError,
        FormalBundleReadError,
        FormalModelReplayError,
        json.JSONDecodeError,
    ) as exc:
        return _receipt(
            replay_id=BYD_REPLAY_ID,
            model_id=BYD_MODEL_ID,
            baseline=None,
            decision="invalid_evidence",
            reason=str(exc),
        )

    try:
        with tempfile.TemporaryDirectory(prefix="alpha-byd-v1-3-replay-") as tmp:
            temporary = Path(tmp)
            byd_base, etf_base, source_identity = _extract_byd_base_inputs(
                normalized_root,
                temporary,
            )
            byd_dir, etf_dir, governed_identity = _extend_byd_inputs(
                root=normalized_root,
                temporary=temporary,
                byd_base=byd_base,
                etf_base=etf_base,
                cutoff=cutoff,
            )

            import src.research.byd_515180_allocation as allocation

            allocation.ETF_CUTOFF = cutoff
            allocation.ETF_SCHEMA = governed_identity["etf_schema_version"]
            allocation.WINDOWS["retrospective_2025_plus"] = ("2025-01-01", cutoff)
            allocation.WINDOWS["full_overlap"] = ("2019-11-26", cutoff)

            observed = build_byd_package(
                byd_dir=byd_dir,
                etf_dir=etf_dir,
                signal_ledger=_resolve(normalized_root, BYD_SIGNAL_LEDGER),
                cutoff=cutoff,
                generated_at=accepted.generated_at,
                predecessor_package=predecessor,
            )

        comparison = compare_package_sections(expected, observed)
        data_identity = {**source_identity, **governed_identity}
        if not comparison["exact"]:
            return _receipt(
                replay_id=BYD_REPLAY_ID,
                model_id=BYD_MODEL_ID,
                baseline=baseline,
                decision="invalid_evidence",
                reason="maintained BYD v1.3 execution does not reproduce the accepted Bundle v2 trace",
                comparison=comparison,
                data_identity=data_identity,
            )
        return _receipt(
            replay_id=BYD_REPLAY_ID,
            model_id=BYD_MODEL_ID,
            baseline=baseline,
            decision="exact_replay",
            comparison=comparison,
            data_identity=data_identity,
        )
    except FileNotFoundError as exc:
        return _receipt(
            replay_id=BYD_REPLAY_ID,
            model_id=BYD_MODEL_ID,
            baseline=baseline,
            decision="data_blocked",
            reason=str(exc),
        )
    except (
        FormalModelReplayError,
        FormalBundleReadError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        return _receipt(
            replay_id=BYD_REPLAY_ID,
            model_id=BYD_MODEL_ID,
            baseline=baseline,
            decision="invalid_evidence",
            reason=str(exc),
        )


def replay_formal_models(
    replay_id: str,
    *,
    root: str | Path,
    refresh_data: bool = False,
) -> dict[str, Any]:
    if replay_id == "all":
        requested = list(REPLAY_IDS)
    elif replay_id in REPLAY_IDS:
        requested = [replay_id]
    else:
        raise FormalModelReplayError(
            f"unsupported formal replay {replay_id!r}; expected one of {[*REPLAY_IDS, 'all']}"
        )

    results: list[dict[str, Any]] = []
    for current in requested:
        if current == QQQ_REPLAY_ID:
            results.append(
                replay_qqq_v4_3(
                    root=root,
                    refresh_data=refresh_data,
                )
            )
        else:
            results.append(replay_byd_v1_3(root=root))

    exact = all(result.get("decision") == "exact_replay" for result in results)
    return {
        "schema_version": "2.0",
        "runner": RUNNER_ID,
        "requested_replay": replay_id,
        "status": "completed" if exact else "blocked",
        "decision": "exact_replay" if exact else "replay_failed",
        "results": results,
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
