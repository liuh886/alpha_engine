"""Add the preregistered buyback progress title variant."""

from __future__ import annotations

import py_compile
from pathlib import Path

TARGET = Path("src/data/company_events/ashare_primary_announcements.py")


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    old = '            "回购公司股份的进展",\n'
    new = old + '            "回购公司股份进展",\n'
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one buyback progress anchor, found {text.count(old)}")
    if "回购公司股份进展" in text:
        raise RuntimeError("buyback progress title variant already exists")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
