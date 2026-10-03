from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.corporate_actions.adjustment import reanchor_additive_qfq

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "data/research/source_reconciliations/cn27/price-basis-v1.json"
FROZEN_SHA = "1e7713e8c2387ac70d4ff9346fc0f553453318dd2fd0fd8ee76e25c52fb26e35"


def _reanchor(frame: pd.DataFrame, **kwargs):
    return reanchor_additive_qfq(
        frame, symbol="300274", cutoff="2026-09-30",
        bridge_path=kwargs.get("bridge_path", BRIDGE),
        repository_root=ROOT, frozen_source_sha256=kwargs.get("frozen_source_sha256", FROZEN_SHA),
    )


def test_issuer_reference_cash_preserves_fixed_basis_for_old_and_new_rows() -> None:
    frame = pd.DataFrame({"open": [74.627, 80.0], "high": [76.0, 81.0],
                          "low": [74.0, 79.0], "close": [75.0, 80.5], "volume": [10, 20]})
    converted, receipt = _reanchor(frame)
    assert converted.open.tolist() == pytest.approx([75.262145, 80.635145])
    assert receipt["reference_cash_offset"] == 0.635145
    assert converted.volume.equals(frame.volume)
    assert frame.open.iloc[0] == 74.627
    assert receipt["events"][0]["distributed_cash_amount"] == 0.64


def test_bridge_cannot_be_reused_for_another_frozen_source() -> None:
    with pytest.raises(ValueError, match="identity"):
        _reanchor(pd.DataFrame(), frozen_source_sha256="0" * 64)


@pytest.mark.parametrize("field,value", [("reference_cash_amount", 0.7), ("source_sha256", "0" * 64)])
def test_unverified_adjustment_fails_closed(tmp_path: Path, field, value) -> None:
    payload = json.loads(BRIDGE.read_text())
    payload["events"][0][field] = value
    candidate = tmp_path / "bridge.json"
    candidate.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unverified"):
        _reanchor(pd.DataFrame(), bridge_path=candidate)
