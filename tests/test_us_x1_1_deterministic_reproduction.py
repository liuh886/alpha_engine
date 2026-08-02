from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.run_us_x1_1_deterministic_reproduction import (
    _canonical_json_hash,
    _ledger_bytes,
    _rank_ledger,
    _score_ledger,
    _selection_ledger,
    _write_ledger,
)


def _scores() -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2025-01-02"), "BBB"),
            (pd.Timestamp("2025-01-02"), "AAA"),
            (pd.Timestamp("2025-01-03"), "AAA"),
            (pd.Timestamp("2025-01-03"), "BBB"),
        ],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame({"score": [0.2, 0.2, 0.1, 0.3]}, index=index)


def test_score_ledger_is_sorted_and_stable() -> None:
    ledger = _score_ledger(_scores())
    assert ledger["instrument"].tolist() == ["AAA", "BBB", "AAA", "BBB"]
    assert _ledger_bytes(ledger) == _ledger_bytes(_score_ledger(_scores()))


def test_rank_ledger_uses_instrument_tie_break() -> None:
    ranks = _rank_ledger(_score_ledger(_scores()))
    first = ranks.loc[ranks["datetime"] == pd.Timestamp("2025-01-02")]
    assert first["instrument"].tolist() == ["AAA", "BBB"]
    assert first["rank"].tolist() == [1, 2]
    second = ranks.loc[ranks["datetime"] == pd.Timestamp("2025-01-03")]
    assert second["instrument"].tolist() == ["BBB", "AAA"]


def test_selection_ledger_is_deterministic() -> None:
    ranks = _rank_ledger(_score_ledger(_scores()))
    selected = _selection_ledger(ranks, topk=1)
    assert selected["instrument"].tolist() == ["AAA", "BBB"]
    assert selected["target_weight"].tolist() == [1.0, 1.0]


def test_ledger_hash_detects_score_change(tmp_path: Path) -> None:
    ledger = _score_ledger(_scores())
    hash_a = _write_ledger(tmp_path / "a.csv", ledger)
    hash_b = _write_ledger(tmp_path / "b.csv", ledger.copy())
    assert hash_a == hash_b
    changed = ledger.copy()
    changed.loc[0, "score"] += 1e-12
    hash_c = _write_ledger(tmp_path / "c.csv", changed)
    assert hash_c != hash_a


def test_canonical_json_hash_ignores_mapping_order() -> None:
    assert _canonical_json_hash({"a": 1, "b": [2, 3]}) == _canonical_json_hash(
        {"b": [2, 3], "a": 1}
    )
