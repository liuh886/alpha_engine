"""Evidence portability: identical logic must hash identically everywhere.

Phase 3 locks the known cross-platform nondeterminism in the active
refresh path (provider text calendars/instruments) and documents the
deliberately frozen divergences (sealed CRLF evidence, per-module JSON
canonical forms, pandas float repr under a locked dependency set).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from scripts.dump_bin import dump_all


def _csv(path: Path, symbol: str) -> None:
    path.write_text(
        "date,open,high,low,close,volume\n"
        "2021-01-04,10.5,11.0,10.0,10.75,100\n"
        "2021-01-05,10.75,11.5,10.25,11.125,200\n",
        encoding="utf-8",
    )


def _dump(csv_dir: Path, out_dir: Path, **kwargs) -> None:
    dump_all(str(csv_dir), str(out_dir), include_fields="open,high,low,close,volume", **kwargs)


def _text_bytes(out_dir: Path) -> dict[str, bytes]:
    blobs = {}
    for path in sorted((out_dir / "calendars").glob("*.txt")):
        blobs[f"calendars/{path.name}"] = path.read_bytes()
    for path in sorted((out_dir / "instruments").glob("*.txt")):
        blobs[f"instruments/{path.name}"] = path.read_bytes()
    return blobs


def test_dump_text_outputs_use_lf_on_all_platforms(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _csv(csv_dir / "AAA.csv", "AAA")
    out_dir = tmp_path / "provider"
    _dump(csv_dir, out_dir)

    blobs = _text_bytes(out_dir)
    assert blobs, "dump must produce calendar/instrument text files"
    for name, blob in blobs.items():
        assert b"\r" not in blob, f"{name} contains CR bytes"


def test_dump_is_byte_deterministic(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    _csv(csv_dir / "AAA.csv", "AAA")
    first = tmp_path / "first"
    second = tmp_path / "second"
    _dump(csv_dir, first)
    _dump(csv_dir, second)

    assert _text_bytes(first) == _text_bytes(second)
    for name, blob in _text_bytes(first).items():
        digest = hashlib.sha256(blob).hexdigest()
        assert digest == hashlib.sha256(_text_bytes(second)[name]).hexdigest()


def test_refresh_csv_writer_uses_lf(tmp_path: Path) -> None:
    import scripts.data.refresh_selected_pool_prices as module

    frame = pd.DataFrame(
        {
            "date": ["2021-01-04", "2021-01-05"],
            "open": [10.5, 10.75],
            "high": [11.0, 11.5],
            "low": [10.0, 10.25],
            "close": [10.75, 11.125],
            "volume": [100, 200],
            "amount": [1000, 2000],
            "factor": [1.0, 1.0],
        }
    )
    path = tmp_path / "out.csv"
    module._write_csv(path, frame)
    assert b"\r" not in path.read_bytes()


def test_json_canonical_forms_are_deterministic() -> None:
    from src.artifacts.formal_provider_cache import _canonical_json

    payload = {"b": [1, "x"], "a": {"y": 2}}
    assert _canonical_json(payload) == _canonical_json(payload)
    assert _canonical_json(payload).endswith(b"\n")
