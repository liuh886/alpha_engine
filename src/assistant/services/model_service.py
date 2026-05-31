from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from src.assistant.model_registry_index import ModelRegistryIndex
from src.common.logging import get_logger
from src.common.paths import MODELS_DIR
from src.governance.service import GovernanceService

logger = get_logger(__name__)

# Minimum thresholds for RECOMMENDED promotion (Criterion C6)
_PROMOTION_GATES = {
    "excess_return_min": 0.0,        # excess return > 0
    "information_ratio_min": 0.5,    # IR > 0.5
    "mdd_benchmark_ratio_max": 1.5,  # MDD not worse than 1.5x benchmark
    "require_positive_net_return": True,  # positive post-turnover return
    "require_walk_forward": True,         # at least one walk-forward validation
}


class ModelService:
    def __init__(self, *, project_root: str | Path, model_index: ModelRegistryIndex):
        self._project_root = Path(project_root)
        self._model_index = model_index
        self._gov = GovernanceService(self._project_root)

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
                logger.warning("Failed to update model_list.yaml after deleting version", version_id=version_id, exc_info=True)

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
                        logger.warning("Failed to delete model file from disk", path=str(abs_path), version_id=version_id, exc_info=True)

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

        # Gate 1: Excess return > 0
        excess_ret = metrics.get("excess_return") or metrics.get("excess_annual_return")
        if excess_ret is not None and excess_ret <= _PROMOTION_GATES["excess_return_min"]:
            failures.append(f"Excess return {excess_ret:.2%} <= 0 (gate: > 0)")

        # Gate 2: Information ratio > 0.5
        ir = metrics.get("information_ratio") or metrics.get("sharpe")
        if ir is not None and ir < _PROMOTION_GATES["information_ratio_min"]:
            failures.append(f"Information ratio {ir:.2f} < 0.5 (gate: >= 0.5)")

        # Gate 3: Max drawdown not worse than 1.5x benchmark
        mdd = metrics.get("max_drawdown")
        bench_mdd = metrics.get("bench_max_drawdown") or metrics.get("benchmark_max_drawdown")
        if mdd is not None and bench_mdd is not None and bench_mdd != 0:
            ratio = abs(mdd) / abs(bench_mdd)
            if ratio > _PROMOTION_GATES["mdd_benchmark_ratio_max"]:
                failures.append(f"Max DD ratio {ratio:.1f}x benchmark > 1.5x (gate: <= 1.5x)")

        # Gate 4: Positive post-turnover return (net of costs)
        net_ret = metrics.get("excess_return_with_cost") or metrics.get("net_return_after_costs")
        if net_ret is not None and net_ret <= 0:
            failures.append(f"Net return after costs {net_ret:.2%} <= 0 (gate: > 0)")

        # Gate 5: Walk-forward validation
        params = version.get("params") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}
        walk_forward = params.get("walk_forward") or metrics.get("walk_forward_validated")
        if not walk_forward:
            failures.append("Walk-forward validation not performed (required for RECOMMENDED)")

        return failures

    def promote_model(self, version_id: str, stage: str = "RECOMMENDED") -> dict:
        """
        Promote a model version to a new stage.
        If stage is RECOMMENDED, enforce promotion gates first.
        Returns {"ok": bool, "gate_failures": list[str]}.
        """
        # Gate check for RECOMMENDED promotion
        if stage.upper() == "RECOMMENDED":
            gate_failures = self._check_promotion_gates(version_id)
            if gate_failures:
                logger.warning(
                    "Promotion gate check failed",
                    version_id=version_id,
                    failures=gate_failures,
                )
                return {"ok": False, "gate_failures": gate_failures}

        # 1. Update SQLite
        ok = self._model_index.update_stage(version_id, stage)
        if not ok:
            return {"ok": False, "gate_failures": []}

        # 2. Update YAML (Source of Truth)
        # We need to find the entry in model_list.yaml and update its stage or description
        # The design doc suggests YAML is SSOT.
        yaml_path = MODELS_DIR / "model_list.yaml"
        if yaml_path.exists():
            try:
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
            except Exception:
                logger.warning("Failed to update model stage in YAML", version_id=version_id, stage=stage, exc_info=True)

        # 3. File System Action for RECOMMENDED
        version = self._model_index.get_version(version_id)
        if stage.upper() == "RECOMMENDED" and version:
            market = str(version.get("market") or "unknown").lower()
            src_path_rel = version.get("path")
            if src_path_rel:
                src_path = self._project_root / src_path_rel
                if src_path.exists():
                    dest_path = MODELS_DIR / f"recommended_{market}_model.pkl"
                    try:
                        shutil.copy(src_path, dest_path)
                    except Exception:
                        logger.warning("Failed to copy model file to recommended path", src=str(src_path), dest=str(dest_path), exc_info=True)

        # 4. Log governance event
        if version:
            self._gov.log_run_event(
                str(version.get("market") or "all"),
                "Model Promotion",
                f"ID: {version_id} -> {stage}",
            )

        return {"ok": True, "gate_failures": []}

    def get_model_details(self, version_id: str) -> dict:
        """
        Retrieves complete model version details, including associated YAML config.
        """
        version = self._model_index.get_version(version_id)
        if not version:
            raise ValueError(f"Model version not found: {version_id}")

        market = str(version.get("market") or "cn").lower()
        config_name = f"{market}_lgbm_workflow.yaml"
        config_path = self._project_root / "configs" / config_name

        config_content = ""
        if config_path.exists():
            try:
                config_content = config_path.read_text(encoding="utf-8")
            except Exception:
                logger.warning("Failed to read model config file", config_path=str(config_path), exc_info=True)
                config_content = "Error reading config file."

        return {
            "version": version,
            "config": {"name": config_name, "content": config_content},
        }
