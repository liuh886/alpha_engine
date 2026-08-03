from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.run_us_x1_1_sector_style_attribution import (
    _decision,
    _negative_loss_share,
)
from src.research.us87_sector_style import (
    cap_sector_weights,
    compute_style_snapshot,
    load_sector_classification,
)


def _classification_file(tmp_path: Path) -> Path:
    import hashlib

    records = {
        "AAA": {
            "entity": "AAA Corp",
            "sector": "Technology",
            "industry": "Software",
            "confidence": "high",
        },
        "TIGO": {
            "entity": "Millicom International Cellular S.A.",
            "sector": "Communication Services",
            "industry": "Wireless Telecommunications",
            "confidence": "high",
            "manual_override": "Explicit Millicom binding",
        },
        "TYGO": {
            "entity": "Tigo Energy Inc.",
            "sector": "Industrials",
            "industry": "Electrical Equipment",
            "confidence": "high",
        },
    }
    canonical = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload = {
        "candidate_count": 3,
        "classification_standard": "test_v1",
        "source_provider": "review",
        "source_effective_date": "2026-08-03",
        "retrieval_date": "2026-08-03",
        "records_sha256": hashlib.sha256(canonical).hexdigest(),
        "records": records,
    }
    path = tmp_path / "map.yaml"
    import yaml

    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_sector_classification_requires_exact_pool_and_tigo_binding(
    tmp_path: Path,
) -> None:
    path = _classification_file(tmp_path)
    frame, _ = load_sector_classification(
        path,
        ["AAA", "TIGO", "TYGO"],
    )
    assert list(frame["symbol"]) == ["AAA", "TIGO", "TYGO"]
    assert frame.loc[
        frame["symbol"] == "TIGO", "canonical_entity_name"
    ].iloc[0].startswith("Millicom")


def test_style_snapshot_uses_only_completed_sessions() -> None:
    dates = pd.bdate_range("2024-08-01", periods=90)
    base = np.arange(len(dates), dtype=float)
    closes = pd.DataFrame(
        {
            "AAA": 100 + base,
            "BBB": 100 + base * 0.5,
            "CCC": 100 - base * 0.1,
            "QQQ": 200 + base * 0.8,
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "AAA": np.full(len(dates), 1000.0),
            "BBB": np.full(len(dates), 2000.0),
            "CCC": np.full(len(dates), 3000.0),
            "QQQ": np.full(len(dates), 4000.0),
        },
        index=dates,
    )
    signal_date = dates[80]
    before = compute_style_snapshot(
        closes,
        volumes,
        signal_date,
        ["AAA", "BBB", "CCC"],
    )
    changed = closes.copy()
    changed.loc[changed.index >= signal_date, "AAA"] = 1_000_000.0
    after = compute_style_snapshot(
        changed,
        volumes,
        signal_date,
        ["AAA", "BBB", "CCC"],
    )
    pd.testing.assert_frame_equal(before, after)
    assert set(before["beta60_bucket"]) == {"low_beta", "mid_beta", "high_beta"}
    assert before["median_dollar_volume20"].notna().all()


def test_sector_cap_redistributes_and_preserves_sum() -> None:
    weights = pd.Series(
        {
            "A": 0.20,
            "B": 0.20,
            "C": 0.20,
            "D": 0.20,
            "E": 0.20,
        }
    )
    sectors = {
        "A": "Technology",
        "B": "Technology",
        "C": "Technology",
        "D": "Industrials",
        "E": "Health Care",
    }
    capped = cap_sector_weights(weights, sectors, 0.40)
    grouped = capped.groupby(pd.Series(sectors)).sum()
    assert abs(float(capped.sum()) - 1.0) < 1e-10
    assert float(grouped.max()) <= 0.40 + 1e-9


def test_negative_loss_share_uses_negative_rows() -> None:
    frame = pd.DataFrame(
        {
            "sector": ["Technology", "Technology", "Industrials", "Health Care"],
            "net_contribution": [-0.20, 0.10, -0.10, 0.05],
        }
    )
    result = _negative_loss_share(frame, "sector")
    assert result["top_bucket"] == "Technology"
    assert abs(float(result["top_loss_share"]) - 2 / 3) < 1e-12


def test_decision_identifies_broad_shock() -> None:
    rows = []
    sectors = ["Technology", "Industrials", "Health Care"]
    for index, sector in enumerate(sectors):
        rows.append(
            {
                "sector": sector,
                "net_contribution": -0.10,
                "beta60_bucket": ["low_beta", "mid_beta", "high_beta"][index],
                "vol60_bucket": ["low_vol", "mid_vol", "high_vol"][index],
                "momentum20_bucket": [
                    "laggard_20d",
                    "neutral_20d",
                    "leader_20d",
                ][index],
                "momentum60_bucket": [
                    "laggard_60d",
                    "neutral_60d",
                    "leader_60d",
                ][index],
                "liquidity20_bucket": [
                    "low_liquidity",
                    "mid_liquidity",
                    "high_liquidity",
                ][index],
                "qqq_trend_state": ["negative", "non_negative", "negative"][index],
            }
        )
    drawdown = pd.DataFrame(rows)
    leave_one_sector = pd.DataFrame(
        [
            {
                "excluded_sector": "Technology",
                "drawdown_improvement": 0.01,
            }
        ]
    )
    sector_cap = {"max_drawdown": -0.29, "excess_return": 0.09}
    baseline = {"max_drawdown": -0.30, "excess_return": 0.10}
    result = _decision(drawdown, leave_one_sector, sector_cap, baseline)
    assert result["decision"] == "broad_cross_sector_style_shock"
    assert result["automatic_model_update"] is False
