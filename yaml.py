"""Temporary bootstrap bridge; deleted before merge."""
from __future__ import annotations

import json
import subprocess


def _run(code: str, payload: str) -> str:
    result = subprocess.run(
        [".venv/bin/python", "-I", "-c", code],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def safe_load(text: str):
    output = _run(
        "import json,sys,yaml; print(json.dumps(yaml.safe_load(sys.stdin.read())))",
        text,
    )
    return json.loads(output)


def safe_dump(value, sort_keys: bool = False) -> str:
    payload = json.dumps(value)
    return _run(
        "import json,sys,yaml; print(yaml.safe_dump(json.loads(sys.stdin.read()), sort_keys="
        + ("True" if sort_keys else "False")
        + "), end='')",
        payload,
    )
