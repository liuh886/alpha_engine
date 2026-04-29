#!/usr/bin/env python3
"""Compatibility wrapper: moved to agents/governance/scripts/sync_governance.py."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    target = (
        Path(__file__).resolve().parents[1]
        / "agents"
        / "governance"
        / "scripts"
        / "sync_governance.py"
    )
    runpy.run_path(str(target), run_name="__main__")
