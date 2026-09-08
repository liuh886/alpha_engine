from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file

from src.research.cn27_v1_2_evidence import (
    load_cn27_v1_2_final_contract,
    run_cn27_v1_2_evidence,
    select_walk_forward_recipe,
)


SPEC = "configs/research_paradigms/cn_27_v1_2.yaml"


def test_final_contract_reproduces_sealed_stability_recipe() -> None:
    contract = load_cn27_v1_2_final_contract(SPEC)

    assert contract.selected_recipe["id"] == "s1_stable_all7_30_vol_target"
    assert len(contract.selected_recipe["factors"]) == 7
    assert contract.spec["factor_model"]["stability_contract"][
        "stable_selected_factor_share"
    ] == 1.0
    assert contract.spec["research_only"] is True
    assert contract.spec["trade_ready"] is False


def test_walk_forward_selection_does_not_read_future_fold() -> None:
    metrics = {
        "a": {
            "f1": {"sharpe_log_excess": 1.0, "annual_one_way_turnover": 2.0},
            "f2": {"sharpe_log_excess": 0.8, "annual_one_way_turnover": 2.0},
            "f3": {"sharpe_log_excess": -10.0, "annual_one_way_turnover": 2.0},
        },
        "b": {
            "f1": {"sharpe_log_excess": 0.9, "annual_one_way_turnover": 1.0},
            "f2": {"sharpe_log_excess": 0.7, "annual_one_way_turnover": 1.0},
            "f3": {"sharpe_log_excess": 10.0, "annual_one_way_turnover": 1.0},
        },
    }
    selected, _ = select_walk_forward_recipe(metrics, ("f1", "f2"))
    changed = deepcopy(metrics)
    changed["a"]["f3"]["sharpe_log_excess"] = 1000.0
    changed["b"]["f3"]["sharpe_log_excess"] = -1000.0
    selected_after_future_change, _ = select_walk_forward_recipe(changed, ("f1", "f2"))

    assert selected == "a"
    assert selected_after_future_change == selected


def test_complete_v1_2_evidence_is_reproducible(tmp_path) -> None:
    result = run_cn27_v1_2_evidence(SPEC, output_dir=tmp_path)

    assert result["all_support_gates_passed"] is True
    assert result["research_only"] is True
    assert result["trade_ready"] is False
    assert result["walk_forward"]["sharpe_log_excess"] >= 0.5
    # Replays may use different platform newlines; sealed originals retain their bytes.
    sealed = Path("artifacts/evidence/cn_27_v1_2")
    manifest = json.loads((tmp_path / "evidence_manifest.json").read_text(encoding="utf-8"))
    identity = manifest.pop("manifest_identity_sha256")
    assert canonical_sha256(manifest) == identity == result["manifest_identity_sha256"]
    retained = json.loads((sealed / "evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["identity"] == retained["identity"]
    for name, expected_hash in retained["outputs"].items():
        assert sha256_file(sealed / name) == expected_hash
        assert sha256_file(tmp_path / name) == manifest["outputs"][name]
        if name.endswith(".csv"):
            pd.testing.assert_frame_equal(
                pd.read_csv(tmp_path / name), pd.read_csv(sealed / name),
                check_exact=False, rtol=1e-10, atol=1e-12,
            )
