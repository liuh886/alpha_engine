from __future__ import annotations

import pytest

from src.research.backtest_execution_policy import (
    build_execution_receipt,
    require_authoritative_execution,
)


def test_fast_array_receipt_is_explicitly_non_authoritative() -> None:
    receipt = build_execution_receipt("fast_array_research")

    assert receipt.research_only is True
    assert receipt.trade_ready is False
    assert receipt.authoritative_execution is False
    with pytest.raises(ValueError, match="cannot satisfy"):
        require_authoritative_execution(receipt)


def test_qlib_receipt_can_satisfy_authoritative_gate() -> None:
    receipt = build_execution_receipt(
        "authoritative_qlib", precompute_status="complete"
    )

    require_authoritative_execution(receipt)
    assert receipt.to_dict()["engine"] == "qlib_port_analysis"


@pytest.mark.parametrize("status", ["failed", "skipped", "fallback"])
def test_qlib_receipt_rejects_missing_precompute_evidence(status: str) -> None:
    with pytest.raises(ValueError, match="cannot be claimed"):
        build_execution_receipt("authoritative_qlib", precompute_status=status)
