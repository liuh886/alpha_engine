from __future__ import annotations

from pathlib import Path

import yaml


def load_watchlist(config_path: str | Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)
