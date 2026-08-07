from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.append_only_store import (
    AppendOnlyStoreError,
    validate_append_only_store_prefix,
)


def _write_store(root: Path, *, rows: list[tuple[str, str]]) -> None:
    observations = root / "observations"
    observations.mkdir(parents=True, exist_ok=True)
    ledger_lines = ["signal_date,observation_sha256"]
    digests: dict[str, str] = {}
    for date, digest in rows:
        payload = {"signal_date": date, "value": digest}
        (observations / f"{date}.json").write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        ledger_lines.append(f"{date},{digest}")
        digests[date] = digest
    (root / "ledger.csv").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "append_only": True,
                "research_only": True,
                "trade_ready": False,
                "observation_count": len(rows),
                "outcome_count": 0,
                "observation_sha256": digests,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_accepts_new_tail_observation(tmp_path: Path) -> None:
    current = tmp_path / "current"
    candidate = tmp_path / "candidate"
    _write_store(current, rows=[("2026-08-05", "a" * 64)])
    _write_store(
        candidate,
        rows=[("2026-08-05", "a" * 64), ("2026-08-06", "b" * 64)],
    )

    validate_append_only_store_prefix(current, candidate)


def test_rejects_historical_record_rewrite(tmp_path: Path) -> None:
    current = tmp_path / "current"
    candidate = tmp_path / "candidate"
    _write_store(current, rows=[("2026-08-05", "a" * 64)])
    _write_store(candidate, rows=[("2026-08-05", "a" * 64)])
    (candidate / "observations" / "2026-08-05.json").write_text(
        '{"signal_date":"2026-08-05","value":"changed"}\n',
        encoding="utf-8",
    )

    with pytest.raises(AppendOnlyStoreError, match="record drifted"):
        validate_append_only_store_prefix(current, candidate)


def test_rejects_ledger_prefix_rewrite(tmp_path: Path) -> None:
    current = tmp_path / "current"
    candidate = tmp_path / "candidate"
    _write_store(current, rows=[("2026-08-05", "a" * 64)])
    _write_store(candidate, rows=[("2026-08-05", "a" * 64)])
    (candidate / "ledger.csv").write_text(
        "signal_date,observation_sha256\n2026-08-05,wrong\n",
        encoding="utf-8",
    )

    with pytest.raises(AppendOnlyStoreError, match="ledger rewrites"):
        validate_append_only_store_prefix(current, candidate)
