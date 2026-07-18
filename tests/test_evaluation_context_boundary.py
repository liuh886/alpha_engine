"""Tests for the narrow spec-bound evaluator context boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.research.evaluation_context import (
    SpecBoundEvaluationContext,
    TenDayEvaluationConfig,
)
from src.research.notebook_lab_contracts import (
    CANONICAL_10D_RETURN_EXPR,
    ResearchSessionConfig,
)


def test_legacy_notebook_config_remains_structurally_compatible() -> None:
    legacy = ResearchSessionConfig(
        market="us",
        symbols=["AAPL", "MSFT"],
        benchmark="QQQ",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-06-30",
        experiment_id="legacy-notebook",
    )

    assert isinstance(legacy, TenDayEvaluationConfig)


def test_spec_bound_context_serializes_only_evaluator_window_fields() -> None:
    context = SpecBoundEvaluationContext(
        market="cn",
        symbols=("SH600000", "SZ000001"),
        benchmark="000300",
        train_start="2022-01-01",
        train_end="2023-12-31",
        test_start="2024-01-01",
        test_end="2024-06-30",
        holding_days=10,
        rebalance_days=10,
        topk=1,
        model_type="spec_bound_cn_daily_ranker",
        factor_expressions=("$close/Ref($close,10)-1",),
        return_expression=CANONICAL_10D_RETURN_EXPR,
        experiment_id="cn-window",
    )
    payload = context.to_dict()

    assert isinstance(context, TenDayEvaluationConfig)
    assert payload["semantic_source"] == "spec_bound_execution"
    assert payload["symbols"] == ["SH600000", "SZ000001"]
    assert payload["factor_expressions"] == ["$close/Ref($close,10)-1"]
    assert "factor_selection_path" not in payload
    assert "label_type" not in payload


def test_spec_bound_context_rejects_noncanonical_return_semantics() -> None:
    with pytest.raises(ValueError, match="canonical raw 10D return"):
        SpecBoundEvaluationContext(
            market="us",
            symbols=("AAPL", "MSFT"),
            benchmark="QQQ",
            train_start="2022-01-01",
            train_end="2023-12-31",
            test_start="2024-01-01",
            test_end="2024-06-30",
            holding_days=10,
            rebalance_days=10,
            topk=1,
            model_type="spec_bound_us_daily_ranker",
            factor_expressions=("$close",),
            return_expression="Ref($close, -5) / $close - 1",
            experiment_id="invalid-window",
        )


def test_spec_bound_adapters_do_not_import_notebook_session_config() -> None:
    # Thin market adapters delegate to the shared engine; they must not
    # import the legacy notebook session config.
    for path in (
        Path("src/research/cn_qlib_execution_adapter.py"),
        Path("src/research/us_qlib_execution_adapter.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "ResearchSessionConfig" not in source
        assert "notebook_lab_contracts" not in source

    # The shared engine (qlib_execution_common.py) owns SpecBoundEvaluationContext.
    common_source = Path(
        "src/research/qlib_execution_common.py"
    ).read_text(encoding="utf-8")
    assert "SpecBoundEvaluationContext" in common_source
