"""Add the preregistered buyback progress title variant."""

from __future__ import annotations

import py_compile
from pathlib import Path

TARGET = Path("src/data/company_events/ashare_primary_announcements.py")


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    old = '            "回购公司股份的进展",\n'
    token_line = '            "回购公司股份进展",\n'
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one buyback progress anchor, found {text.count(old)}")
    if token_line in text:
        return 0
    TARGET.write_text(text.replace(old, old + token_line, 1), encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
