from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.exact_frame_cache import (
    load_exact_frame_snapshot,
    write_exact_frame_snapshot,
)


def test_exact_frame_snapshot_requires_identity_and_hash_match(tmp_path: Path) -> None:
    identity = {
        "market": "cn",
        "symbol": "000425",
        "start": "2021-01-01",
        "cutoff": "2026-07-31",
        "source_provider": "test_provider",
    }
    write_exact_frame_snapshot(
        tmp_path,
        identity=identity,
        retrieved_at="2026-08-04T00:00:00+00:00",
        frames={
            "disclosures": pd.DataFrame({"公告时间": pd.to_datetime(["2026-04-01"]), "值": [1.0]}),
            "empty_statement": pd.DataFrame(columns=["报告日"]),
        },
    )

    snapshot = load_exact_frame_snapshot(
        tmp_path,
        identity=identity,
        frame_names=["disclosures", "empty_statement"],
    )
    assert snapshot is not None
    assert snapshot.retrieved_at == "2026-08-04T00:00:00+00:00"
    assert list(snapshot.frames["disclosures"]["值"]) == [1.0]
    assert list(snapshot.frames["empty_statement"].columns) == ["报告日"]

    changed = {**identity, "cutoff": "2026-08-01"}
    assert (
        load_exact_frame_snapshot(
            tmp_path,
            identity=changed,
            frame_names=["disclosures", "empty_statement"],
        )
        is None
    )

    (tmp_path / "disclosures.json").write_text("{}", encoding="utf-8")
    assert (
        load_exact_frame_snapshot(
            tmp_path,
            identity=identity,
            frame_names=["disclosures", "empty_statement"],
        )
        is None
    )
