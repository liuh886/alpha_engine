#!/usr/bin/env python3
"""Compatibility wrapper: moved to agents/risk/scripts/force_quality_check.py."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    target = (
        Path(__file__).resolve().parents[1]
        / "agents"
        / "risk"
        / "scripts"
        / "force_quality_check.py"
    )
    runpy.run_path(str(target), run_name="__main__")
