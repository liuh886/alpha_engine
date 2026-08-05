"""Apply the verified CN130 PIT event Phase 1 builder payload."""

from __future__ import annotations

import base64
import hashlib
import py_compile
from pathlib import Path

EXPECTED_SHA256 = "28aa5fc763d49283983f2c2ff991eb53881013581abe4ee427074e638f9199a9"
PAYLOAD_GLOB = ".github/cn130_event_phase1_payload.chunk*"
TARGET = Path("scripts/data/build_cn130_pit_event_families.py")


def main() -> int:
    chunks = sorted(Path(".").glob(PAYLOAD_GLOB))
    if len(chunks) != 5:
        raise RuntimeError(f"expected five payload chunks, found {len(chunks)}")
    encoded = "".join(path.read_text(encoding="utf-8").strip() for path in chunks)
    decoded = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(decoded).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"payload SHA mismatch: {digest}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(decoded)
    py_compile.compile(str(TARGET), doraise=True)
    for path in chunks:
        path.unlink()
    Path(__file__).unlink()
    Path(".github/workflows/cn130-pit-event-families-phase1-bootstrap.yml").unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
