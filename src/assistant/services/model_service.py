from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from src.assistant.model_registry_index import ModelRegistryIndex
from src.assistant.services.governance_service import GovernanceService
from src.common.paths import MODELS_DIR


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
                pass

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
                        pass

            # Log deletion event
            self._gov.log_run_event(
                str(version.get("market") or "all"), "Model Deletion", f"ID: {version_id}"
            )

        return True

    def promote_model(self, version_id: str, stage: str = "RECOMMENDED") -> bool:
        """
        Promote a model version to a new stage.
        If stage is RECOMMENDED, copy the model file to recommended_<market>_model.pkl.
        """
        # 1. Update SQLite
        ok = self._model_index.update_stage(version_id, stage)
        if not ok:
            return False

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
                pass

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
                        pass

        # 4. Log governance event
        if version:
            self._gov.log_run_event(
                str(version.get("market") or "all"),
                "Model Promotion",
                f"ID: {version_id} -> {stage}",
            )

        return True

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
                config_content = "Error reading config file."

        return {
            "version": version,
            "config": {"name": config_name, "content": config_content},
        }
