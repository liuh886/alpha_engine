"""Tests for the deprecated CN runner's spec-bound compatibility wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_cn_10d_validation as legacy_runner


def test_legacy_cn_runner_delegates_only_spec_bound_inputs(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(root, *, spec_path, output_dir, provider_uri):
        captured.update(
            {
                "root": root,
                "spec_path": spec_path,
                "output_dir": output_dir,
                "provider_uri": provider_uri,
            }
        )
        return {"status": "passed", "source": "canonical"}

    monkeypatch.setattr(legacy_runner, "_run_canonical", fake_run)
    result = legacy_runner.run(
        Path("/repo"),
        spec_path=Path("custom.yaml"),
        output_dir=Path("artifacts"),
        provider_uri=Path("provider"),
    )

    assert result == {"status": "passed", "source": "canonical"}
    assert captured == {
        "root": Path("/repo"),
        "spec_path": Path("custom.yaml"),
        "output_dir": Path("artifacts"),
        "provider_uri": Path("provider"),
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("first_test_year", 2025),
        ("last_test_year", 2027),
        ("train_start", "2022-01-01"),
        ("test_end", "2025-12-31"),
        ("alignment_mode", "strict"),
    ],
)
def test_legacy_semantic_overrides_fail_closed(name: str, value: object) -> None:
    kwargs = {name: value}
    with pytest.raises(ValueError, match="Legacy CN runner overrides"):
        legacy_runner.run(Path.cwd(), **kwargs)
