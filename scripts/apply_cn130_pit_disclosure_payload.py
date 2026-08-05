from __future__ import annotations

import base64
import hashlib
import py_compile
from pathlib import Path

EXPECTED_SHA256 = "f32d693c10bc5df339729f74d75630b0b3429508a66072c720284c8f143ecd49"
TARGET = Path("scripts/run_cn130_pit_disclosure_reaction.py")

root = Path.cwd()
chunks = sorted((root / ".github").glob("cn130_pit_disclosure_payload.chunk*"))
if not chunks:
    print("No disclosure payload chunks remain; bootstrap is already complete.")
    raise SystemExit(0)

encoded = "".join(path.read_text(encoding="ascii") for path in chunks)
payload = base64.b64decode(encoded, validate=True)
actual = hashlib.sha256(payload).hexdigest()
if actual != EXPECTED_SHA256:
    raise RuntimeError(f"payload sha mismatch: {actual}")

TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.write_bytes(payload)
py_compile.compile(str(TARGET), doraise=True)

for path in chunks:
    path.unlink()
Path(__file__).unlink()
print(f"Applied {TARGET} with sha256={actual}")
