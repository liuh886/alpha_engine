from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.factor_feature_quality import evaluate_factor_feature_quality
from src.research.paradigm import load_research_paradigm_spec


class FakeFeatureQualityRuntime:
    def __init__(self, *, future_sessions: int = 0, inject_inf: bool = False) -> None:
        self.future_sessions = future_sessions
        self.inject_inf = inject_inf
        self.initialized = False

    def initialize(self, repository_root: Path) -> None:
        assert repository_root.is_dir()
        self.initialized = True

    def features(
        self,
        symbols: list[str],
        expressions: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        assert self.initialized
        dates = pd.bdate_range(start, end)
        index = pd.MultiIndex.from_product(
            [dates, symbols], names=["datetime", "instrument"]
        )
        rows: dict[str, np.ndarray] = {}
        for expression in expressions:
            values: list[float] = []
            for day_index, _date in enumerate(dates):
                for symbol in symbols:
                    if day_index < 10:
                        values.append(float("nan"))
                        continue
                    seed = sum(ord(character) for character in symbol) / 100.0
                    value = float(np.sin(day_index / 11.0 + seed) + day_index / 10_000.0)
                    if self.inject_inf and day_index == 20 and symbol == symbols[0]:
                        value = float("inf")
                    values.append(value)
            rows[expression] = np.asarray(values, dtype=float)
        return pd.DataFrame(rows, index=index)

    def expression_window(self, expression: str) -> tuple[int, int]:
        assert expression
        return 10, self.future_sessions

    def metadata(self) -> dict[str, Any]:
        return {"provider": "fake", "market": "us"}


def _us_phase1_spec() -> tuple[Path, Any]:
    root = Path(__file__).resolve().parents[1]
    spec = load_research_paradigm_spec(
        root / "configs" / "research_paradigms" / "us_issue966_phase1_feature_quality_v1.yaml"
    )
    return root, spec


def test_phase1_feature_quality_passes_warmup_determinism_and_symbol_isolation() -> None:
    root, spec = _us_phase1_spec()
    report = evaluate_factor_feature_quality(
        spec,
        repository_root=root,
        runtime=FakeFeatureQualityRuntime(),
        provider_identity={"provider_identity_sha256": "f" * 64, "cutoff": "2026-06-30"},
    )

    assert report["gate1_pass"] is True
    assert report["quality_scope"] == "feature_mechanics_only_no_forward_label"
    assert report["universe"]["requested_symbol_count"] == 87
    assert report["determinism"]["pass"] is True
    assert report["determinism"]["first_sha256"] == report["determinism"]["second_sha256"]

    factor = report["factors"][0]
    assert factor["factor_id"] == "volume_stat_research.signed_volume_balance_10d"
    assert factor["expression_window"] == {"past_sessions": 10, "future_sessions": 0}
    assert factor["checks"] == {
        "finite_and_coverage": True,
        "no_inf": True,
        "not_near_constant": True,
        "no_future_data": True,
        "symbol_isolation": True,
    }
    assert all(
        row["observed_warmup_sessions"] == 10
        for row in factor["symbol_quality"].values()
    )
    assert all(
        row["post_warmup_coverage"] == 1.0
        for row in factor["symbol_quality"].values()
    )


def test_phase1_feature_quality_rejects_qllib_future_window() -> None:
    root, spec = _us_phase1_spec()
    report = evaluate_factor_feature_quality(
        spec,
        repository_root=root,
        runtime=FakeFeatureQualityRuntime(future_sessions=1),
        provider_identity={"provider_identity_sha256": "f" * 64, "cutoff": "2026-06-30"},
    )

    assert report["gate1_pass"] is False
    factor = report["factors"][0]
    assert factor["checks"]["no_future_data"] is False
    assert factor["expression_window"]["future_sessions"] == 1


def test_phase1_feature_quality_rejects_infinite_factor_values() -> None:
    root, spec = _us_phase1_spec()
    report = evaluate_factor_feature_quality(
        spec,
        repository_root=root,
        runtime=FakeFeatureQualityRuntime(inject_inf=True),
        provider_identity={"provider_identity_sha256": "f" * 64, "cutoff": "2026-06-30"},
    )

    assert report["gate1_pass"] is False
    factor = report["factors"][0]
    assert factor["inf_count"] > 0
    assert factor["checks"]["no_inf"] is False
