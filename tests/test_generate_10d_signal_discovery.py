from __future__ import annotations

import pandas as pd
import pytest

from scripts.generate_10d_signal_discovery import _load_predictions, _normalise_panel


def test_load_predictions_requires_explicit_score_contract(tmp_path):
    path = tmp_path / "predictions.csv"
    pd.DataFrame(
        {"datetime": ["2026-01-02"], "instrument": ["AAPL"], "label": [1.0]}
    ).to_csv(path, index=False)

    with pytest.raises(ValueError, match="score"):
        _load_predictions(path)


def test_normalise_panel_names_raw_economic_return():
    index = pd.MultiIndex.from_tuples(
        [("AAPL", pd.Timestamp("2026-01-02"))],
        names=["instrument", "datetime"],
    )
    panel = pd.DataFrame({"Ref($close, -10) / $close - 1": [0.12]}, index=index)

    result = _normalise_panel(panel, "return")

    assert result.index.names == ["datetime", "instrument"]
    assert list(result.columns) == ["return"]
    assert result.iloc[0, 0] == pytest.approx(0.12)
