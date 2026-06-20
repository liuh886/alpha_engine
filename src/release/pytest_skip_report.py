"""Pytest plugin that records every runtime and collection skip by node id."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_SKIPS: dict[str, str] = {}


def pytest_configure() -> None:
    _SKIPS.clear()


def pytest_runtest_logreport(report: Any) -> None:
    if report.skipped:
        _SKIPS[report.nodeid] = _skip_reason(report.longrepr)


def pytest_collectreport(report: Any) -> None:
    if report.skipped:
        _SKIPS[report.nodeid] = _skip_reason(report.longrepr)


def pytest_sessionfinish() -> None:
    output = os.environ.get("ALPHA_SKIP_REPORT")
    if not output:
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"nodeid": nodeid, "reason": _SKIPS[nodeid]} for nodeid in sorted(_SKIPS)]
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def _skip_reason(longrepr: Any) -> str:
    if isinstance(longrepr, tuple) and len(longrepr) >= 3:
        return str(longrepr[2]).removeprefix("Skipped: ").strip()
    return str(longrepr).strip()

