"""Tiingo free-tier wiring follows the internal-use / no-redistribution boundary.

Strategy and signal jobs compute private archives and derived evidence, so the
secret may be passed. The public provider rebuild and professional price
validation republish raw vendor bars, so the internal-use free tier must stay
unwired there.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SECRET_REF = "${{ secrets.TIINGO_API_TOKEN }}"


def _job_env(relative: str, job: str) -> dict[str, object]:
    document = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    return document["jobs"][job].get("env", {}) or {}


def test_strategy_job_receives_the_tiingo_secret() -> None:
    env = _job_env(".github/workflows/formal-backtest-refresh.yml", "strategy")
    assert env["TIINGO_API_TOKEN"] == SECRET_REF


def test_signal_evaluation_job_receives_the_tiingo_secret() -> None:
    env = _job_env(".github/workflows/qqq-v4-3-signal-alert.yml", "evaluate")
    assert env["TIINGO_API_TOKEN"] == SECRET_REF


def test_public_provider_rebuild_keeps_the_internal_use_token_unwired() -> None:
    env = _job_env(".github/workflows/formal-provider-reseed.yml", "reseed")
    assert env["TIINGO_API_TOKEN"] == ""


def test_professional_price_validation_keeps_the_token_unwired() -> None:
    text = (ROOT / ".github/workflows/us87-professional-prices-ci.yml").read_text(
        encoding="utf-8"
    )
    assert 'TIINGO_API_TOKEN: ""' in text
    assert SECRET_REF not in text


def test_no_workflow_inlines_a_tiingo_token_literal() -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "TIINGO_API_TOKEN" not in line:
                continue
            value = (
                line.split("TIINGO_API_TOKEN", 1)[1]
                .lstrip(": ")
                .split("#", 1)[0]
                .strip()
                .strip('"')
                .strip("'")
            )
            assert value in {"", SECRET_REF}, line
