from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd
from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file

from src.research.cn27_v1_1 import (
    contribution_attribution,
    load_cn27_v1_1_contract,
    run_cn27_v1_1_evidence,
)


SPEC = Path("configs/research_paradigms/cn_27_v1_1.yaml")


def test_v1_1_contract_reproduces_the_sealed_selected_recipe() -> None:
    contract = load_cn27_v1_1_contract(SPEC)

    assert contract.selected_recipe["id"] == "c2_risk_adjusted_momentum"
    assert contract.selected_recipe["rebalance_sessions"] == 10
    assert contract.selected_recipe["top_k"] == 8
    assert contract.spec["research_only"] is True
    assert contract.spec["trade_ready"] is False


def test_contribution_attribution_reconciles_open_returns() -> None:
    contract = load_cn27_v1_1_contract(SPEC)
    dates = pd.bdate_range("2025-01-02", periods=3)
    stock = contract.discovery.candidate_symbols[0]
    bars = pd.DataFrame(
        [
            {
                "date": date,
                "symbol": symbol,
                "open": opens[index],
                "high": opens[index] + 0.1,
                "low": opens[index] - 0.1,
                "close": opens[index],
                "volume": 1_000_000,
            }
            for symbol, opens in [(stock, [10.0, 11.0, 11.0]), ("515180", [10.0, 10.0, 10.0])]
            for index, date in enumerate(dates)
        ]
    )
    daily = pd.DataFrame(
        {
            "gross_return": [0.0, 0.05, 0.0],
            "return_weights": [
                '{"515180": 1.0}',
                f'{{"{stock}": 0.5, "515180": 0.5}}',
                f'{{"{stock}": 0.5, "515180": 0.5}}',
            ],
        },
        index=dates,
    )

    attribution, summary = contribution_attribution(daily, bars, contract)

    assert np.isclose(attribution["gross_contribution"].sum(), 0.05)
    assert summary["maximum_daily_reconciliation_error"] < 1e-12
    assert summary["largest_positive_name"] == stock


def test_v1_1_complete_evidence_is_reproducible(tmp_path: Path) -> None:
    result = run_cn27_v1_1_evidence(SPEC, output_dir=tmp_path)

    assert result["all_support_gates_passed"] is True
    assert result["research_only"] is True
    assert result["trade_ready"] is False
    assert result["full_window"]["sharpe_log_excess"] >= 1.0
    assert result["full_window"]["annual_one_way_turnover"] <= 8.0
    # Replays may use different platform newlines; sealed originals retain their bytes.
    sealed = Path("artifacts/evidence/cn_27_v1_1")
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
