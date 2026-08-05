from __future__ import annotations

import base64
import hashlib
import tarfile
from pathlib import Path

EXPECTED_SHA256 = "f28920ff8de9b18969602f883378f796347cb95f2210479efce791aa91f0440b"

root = Path.cwd()
chunks = sorted((root / ".github").glob("cn130_pit_fundamental_payload.chunk*"))
if not chunks:
    raise RuntimeError("payload chunks not found")
encoded = "".join(path.read_text(encoding="ascii") for path in chunks)
archive_path = root / ".cn130-pit-fundamental-payload.tar.gz"
archive_path.write_bytes(base64.b64decode(encoded))
actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if actual != EXPECTED_SHA256:
    raise RuntimeError(f"payload sha mismatch: {actual}")
with tarfile.open(archive_path, "r:gz") as archive:
    archive.extractall(root)
for path in [*chunks, archive_path, root / "scripts/apply_cn130_pit_fundamental_payload.py"]:
    path.unlink(missing_ok=True)
