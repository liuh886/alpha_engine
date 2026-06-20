from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.assistant.model_registry_index import _MODEL_STAGES, ModelRegistryIndex
from src.common.logging import get_logger
from src.common.paths import MODELS_DIR
from src.governance.service import GovernanceService
from src.research.evidence import EvidenceLedger

logger = get_logger(__name__)

# Minimum thresholds for RECOMMENDED promotion (Criterion C6)
_PROMOTION_GATES = {
    "excess_return_min": 0.0,  # excess return > 0
    "information_ratio_min": 0.5,  # IR > 0.5
    "mdd_benchmark_ratio_max": 1.5,  # MDD not worse than 1.5x benchmark
    "require_positive_net_return": True,  # positive post-turnover return
    "require_walk_forward": True,  # at least one walk-forward validation
}
_REQUIRED_PROMOTION_METRICS = {
    "excess_return": ("excess_return", "excess_annual_return"),
    "information_ratio": ("information_ratio", "sharpe"),
    "max_drawdown": ("max_drawdown",),
    "benchmark_max_drawdown": ("bench_max_drawdown", "benchmark_max_drawdown"),
    "net_return_after_costs": ("excess_return_with_cost", "net_return_after_costs"),
}


class ModelService:
    def __init__(self, *, project_root: str | Path, model_index: ModelRegistryIndex):
        self._project_root = Path(project_root)
        self._model_index = model_index
        self._gov = GovernanceService(self._project_root)
        self._evidence = EvidenceLedger(artifacts_dir=self._project_root / "artifacts")

    def delete_model(self, version_id: str) -> bool:
        """
        Delete a model version from index, YAML and disk.
        """
        # 1. Get info before deletion
        version = self._model_index.get_version(version_id)

        # 2. Update SQLite
        self._model_index.delete_version(version_id)

        # 3. Update YAML
        yaml_path = MODELS_DIR / "model_list.yaml"
        if yaml_path.exists():
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"models": []}

                data["models"] = [m for m in data.get("models", []) if m.get("id") != version_id]

                with open(yaml_path, "w", encoding="utf-8") as f:
                    yaml.dump(data, f, sort_keys=False)
            except Exception:
                logger.warning(
                    "Failed to update model_list.yaml after deleting version",
                    version_id=version_id,
                    exc_info=True,
                )

        # 4. Physical cleanup
        if version:
            # Delete .pkl file
            rel_path = version.get("path")
            if rel_path:
                abs_path = self._project_root / rel_path
                if abs_path.exists():
                    try:
                        abs_path.unlink()
                    except Exception:
                        logger.warning(
                            "Failed to delete model file from disk",
                            path=str(abs_path),
                            version_id=version_id,
                            exc_info=True,
                        )

            # Log deletion event
            self._gov.log_run_event(
                str(version.get("market") or "all"), "Model Deletion", f"ID: {version_id}"
            )

        return True

    def _check_promotion_gates(self, version_id: str) -> list[str]:
        """Check if a model version meets RECOMMENDED promotion gates.
        Returns a list of gate failure reasons (empty = all gates pass)."""
        version = self._model_index.get_version(version_id)
        if not version:
            return ["Model version not found"]

        failures = []
        metrics_json = version.get("metrics_json")
        if not metrics_json:
            return ["No metrics available for this model version"]

        try:
            metrics = json.loads(metrics_json) if isinstance(metrics_json, str) else metrics_json
        except (json.JSONDecodeError, TypeError):
            return ["Metrics data is corrupted"]

        metric_values: dict[str, Any] = {}
        for metric_name, aliases in _REQUIRED_PROMOTION_METRICS.items():
            value = next(
                (metrics[key] for key in aliases if key in metrics and metrics[key] is not None),
                None,
            )
            metric_values[metric_name] = value
            if value is None:
                failures.append(f"Missing required promotion metric: {metric_name}")

        # Gate 1: Excess return > 0
        excess_ret = metric_values["excess_return"]
        if excess_ret is not None and excess_ret <= _PROMOTION_GATES["excess_return_min"]:
            failures.append(f"Excess return {excess_ret:.2%} <= 0 (gate: > 0)")

        # Gate 2: Information ratio > 0.5
        ir = metric_values["information_ratio"]
        if ir is not None and ir < _PROMOTION_GATES["information_ratio_min"]:
            failures.append(f"Information ratio {ir:.2f} < 0.5 (gate: >= 0.5)")

        # Gate 3: Max drawdown not worse than 1.5x benchmark
        mdd = metric_values["max_drawdown"]
        bench_mdd = metric_values["benchmark_max_drawdown"]
        if mdd is not None and bench_mdd is not None and bench_mdd != 0:
            ratio = abs(mdd) / abs(bench_mdd)
            if ratio > _PROMOTION_GATES["mdd_benchmark_ratio_max"]:
                failures.append(f"Max DD ratio {ratio:.1f}x benchmark > 1.5x (gate: <= 1.5x)")

        # Gate 4: Positive post-turnover return (net of costs)
        net_ret = metric_values["net_return_after_costs"]
        if net_ret is not None and net_ret <= 0:
            failures.append(f"Net return after costs {net_ret:.2%} <= 0 (gate: > 0)")

        # Gate 5: Walk-forward validation (HARD GATE)
        payload = version.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}

        params = version.get("params") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}
        artifact_id = str(version.get("artifact_id") or payload.get("artifact_id") or version_id)
        walk_forward = None
        for candidate in (
            params.get("walk_forward"),
            version.get("walk_forward"),
            payload.get("walk_forward"),
        ):
            if not isinstance(candidate, dict):
                continue
            if (
                candidate.get("model_id") == version_id
                or candidate.get("artifact_id") == artifact_id
            ):
                walk_forward = candidate
                break

        if not walk_forward:
            failures.append(
                "Walk-forward validation not performed (HARD GATE — required for promotion)"
            )
        else:
            # Walk-forward data exists — now enforce gate_passed status
            gate_passed = walk_forward.get("gate_passed")
            if gate_passed is False:
                gate_failures = walk_forward.get("gate_failures", [])
                detail = (
                    "; ".join(str(f) for f in gate_failures) if gate_failures else "unknown reason"
                )
                failures.append(f"Walk-forward HARD GATE FAILED — promotion blocked ({detail})")
            elif gate_passed is None:
                # Legacy records without gate_passed field — treat as not validated
                failures.append(
                    "Walk-forward data exists but gate_passed status unknown (HARD GATE — revalidation required)"
                )

        inference_gate = version.get("inference_gate") or payload.get("inference_gate")
        reconstruction_gate = version.get("reconstruction_gate") or payload.get(
            "reconstruction_gate"
        )
        artifact_dir = self._project_root / "artifacts" / "artifacts" / artifact_id
        if artifact_dir.exists():
            marker_path = artifact_dir / ".registered"
            if not marker_path.is_file():
                inference_gate = None
                reconstruction_gate = None
            else:
                try:
                    marker = json.loads(marker_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError, TypeError):
                    marker = {}
                if marker.get("artifact_id") != artifact_id:
                    marker = {}
                inference_gate = marker.get("inference_gate")
                reconstruction_gate = marker.get("reconstruction_gate")

        if not (
            isinstance(inference_gate, dict)
            and inference_gate.get("artifact_id") == artifact_id
            and inference_gate.get("passed") is True
        ):
            failures.append("Fresh inference gate did not pass for this model artifact")

        if not (
            isinstance(reconstruction_gate, dict)
            and reconstruction_gate.get("artifact_id") == artifact_id
            and reconstruction_gate.get("passed") is True
            and str(reconstruction_gate.get("status") or "").lower() == "passed"
            and reconstruction_gate.get("clean_process") is True
        ):
            failures.append(
                "Clean-process reconstruction gate did not pass for this model artifact"
            )

        return failures

    def _build_model_evidence(self, version_id: str) -> dict[str, Any]:
        """Build the minimal promotion evidence reference without blocking promotion flow."""
        try:
            return self._evidence.build_bundle("model", version_id).to_dict()
        except Exception as exc:
            logger.warning(
                "Failed to build model promotion evidence",
                version_id=version_id,
                exc_info=True,
            )
            return {
                "subject_type": "model",
                "subject_id": str(version_id),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "sources": [],
                "metrics": {},
                "warnings": [f"Evidence bundle unavailable: {exc}"],
                "decision": None,
                "completeness_score": 0.0,
            }

    def promote_model(self, version_id: str, stage: str = "RECOMMENDED") -> dict:
        """
        Promote a model version to a new stage.
        If stage is RECOMMENDED, enforce promotion gates first.
        Returns {"ok": bool, "gate_failures": list[str]}.
        """
        stage = str(stage or "").upper().strip()
        if stage not in _MODEL_STAGES:
            raise ValueError(
                f"Unknown model stage: {stage or '<empty>'}. "
                f"Expected one of {sorted(_MODEL_STAGES)}"
            )

        version = self._model_index.get_version(version_id)
        if not version:
            return {"ok": False, "gate_failures": ["Model version not found"]}

        # Gate check for RECOMMENDED promotion
        is_recommended = stage == "RECOMMENDED"
        evidence = self._build_model_evidence(version_id) if is_recommended else None
        if is_recommended:
            gate_failures = self._check_promotion_gates(version_id)
            if gate_failures:
                logger.warning(
                    "Promotion gate check failed",
                    version_id=version_id,
                    failures=gate_failures,
                )
                return {"ok": False, "gate_failures": gate_failures, "evidence": evidence}

        yaml_path = MODELS_DIR / "model_list.yaml"
        yaml_before = yaml_path.read_bytes() if yaml_path.exists() else None
        old_stage = str(version.get("stage") or "STAGING").upper()
        alias_path: Path | None = None
        alias_before: bytes | None = None
        alias_existed = False

        try:
            if not self._model_index.update_stage(version_id, stage):
                raise RuntimeError("Model registry stage update failed")

            if yaml_path.exists():
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {"models": []}

                updated = False
                for m in data.get("models", []):
                    if m.get("id") == version_id:
                        m["stage"] = stage
                        updated = True
                        break

                if updated:
                    with open(yaml_path, "w", encoding="utf-8") as f:
                        yaml.dump(data, f, sort_keys=False)

            if is_recommended:
                market = str(version.get("market") or "unknown").lower()
                src_path_rel = version.get("path")
                if not src_path_rel:
                    raise FileNotFoundError("Promoted model has no artifact path")
                src_path = self._project_root / src_path_rel
                if not src_path.is_file():
                    raise FileNotFoundError(f"Promoted model artifact does not exist: {src_path}")
                alias_path = MODELS_DIR / f"recommended_{market}_model.pkl"
                alias_existed = alias_path.exists()
                alias_before = alias_path.read_bytes() if alias_existed else None
                alias_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src_path, alias_path)

            audit_id = uuid.uuid4().hex
            self._gov.log_run_event(
                str(version.get("market") or "all"),
                "Model Promotion",
                "SUCCESS",
                details={"model_id": version_id, "stage": stage, "audit_id": audit_id},
            )
            audit_persisted = any(
                event.get("details", {}).get("audit_id") == audit_id
                for event in self._gov.query_history(limit=20, outcome="SUCCESS")
            )
            if not audit_persisted:
                raise RuntimeError("Model promotion audit event was not persisted")
        except Exception as exc:
            logger.warning(
                "Model promotion rolled back",
                version_id=version_id,
                stage=stage,
                error=str(exc),
            )
            try:
                self._model_index.update_stage(version_id, old_stage)
            except Exception:
                logger.error("Failed to roll back model registry stage", exc_info=True)
            try:
                if yaml_before is not None:
                    yaml_path.write_bytes(yaml_before)
            except Exception:
                logger.error("Failed to roll back model registry YAML", exc_info=True)
            try:
                if alias_path is not None:
                    if alias_existed and alias_before is not None:
                        alias_path.write_bytes(alias_before)
                    elif alias_path.exists():
                        alias_path.unlink()
            except Exception:
                logger.error("Failed to roll back recommended model alias", exc_info=True)
            result = {"ok": False, "gate_failures": [str(exc)]}
            if evidence is not None:
                result["evidence"] = evidence
            return result

        result = {"ok": True, "gate_failures": []}
        if evidence is not None:
            result["evidence"] = evidence
        return result

    def get_model_details(self, version_id: str) -> dict:
        """
        Retrieves complete model version details, including associated YAML config.
        """
        version = self._model_index.get_version(version_id)
        if not version:
            raise ValueError(f"Model version not found: {version_id}")

        payload = version.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        frozen_config = version.get("artifact_config") or payload.get("artifact_config")
        market = str(version.get("market") or "cn").lower()
        config_name = f"{market}_lgbm_workflow.yaml"

        config_content = ""
        resolved_config = None
        if isinstance(frozen_config, dict):
            resolved_config = frozen_config
            config_content = yaml.safe_dump(frozen_config, sort_keys=False)
        return {
            "version": version,
            "config": {
                "name": config_name,
                "content": config_content,
                "resolved": resolved_config,
                "available": resolved_config is not None,
            },
        }
