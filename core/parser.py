import importlib
import re
import sys
from pathlib import Path

import yaml


def load_strategy_unit(strategy_name: str):
    strategy_dir = Path(f"strategies/{strategy_name}")
    readme_path = strategy_dir / "README.md"

    if not readme_path.exists():
        raise FileNotFoundError(f"Strategy unit {strategy_name} missing README.md")

    with open(readme_path, encoding="utf-8") as f:
        content = f.read()

    # Extract YAML Frontmatter (--- ... ---)
    match = re.search(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    config = yaml.safe_load(match.group(1)) if match else {}

    # Check if strategy.py exists
    strategy_script = strategy_dir / "strategy.py"
    if not strategy_script.exists():
        raise FileNotFoundError(f"Strategy unit {strategy_name} missing strategy.py")

    return config, strategy_dir


def import_strategy_class(strategy_dir: Path, class_name: str):
    sys.path.insert(0, str(strategy_dir.resolve()))
    module = importlib.import_module("strategy")
    strategy_class = getattr(module, class_name)
    return strategy_class
