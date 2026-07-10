"""Tests for the deprecated rolling-ranker compatibility wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_rolling_daily_ranker_evidence as legacy_runner


def test_rolling_runner_delegates_only_spec_bound_inputs(monkeypatch) -> None:
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
        return {"status": "passed", "source": "canonical-us"}

    monkeypatch.setattr(legacy_runner, "_run_canonical", fake_run)
    result = legacy_runner.run(
        Path("/repo"),
        spec_path=Path("us-custom.yaml"),
        output_dir=Path("artifacts"),
        provider_uri=Path("provider"),
    )

    assert result == {"status": "passed", "source": "canonical-us"}
    assert captured == {
        "root": Path("/repo"),
        "spec_path": Path("us-custom.yaml"),
        "output_dir": Path("artifacts"),
        "provider_uri": Path("provider"),
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [("first_test_year", 2025), ("last_test_year", 2027)],
)
def test_legacy_window_overrides_fail_closed(name: str, value: int) -> None:
    with pytest.raises(ValueError, match="Legacy rolling-runner window overrides"):
        legacy_runner.run(Path.cwd(), **{name: value})
