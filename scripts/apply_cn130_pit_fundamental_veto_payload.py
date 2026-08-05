from __future__ import annotations

import base64
import hashlib
import tarfile
from pathlib import Path

EXPECTED_SHA256 = "4187663de12248286cd01e17d7647df4b40ac34e35e5522262e079cd0ce73373"

root = Path.cwd()
chunks = sorted((root / ".github").glob("cn130_pit_fundamental_veto_payload.chunk*"))
if not chunks:
    raise RuntimeError("payload chunks not found")
encoded = "".join(path.read_text(encoding="ascii") for path in chunks)
archive_path = root / ".cn130-pit-fundamental-veto-payload.tar.gz"
archive_path.write_bytes(base64.b64decode(encoded))
actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if actual != EXPECTED_SHA256:
    raise RuntimeError(f"payload sha mismatch: {actual}")
with tarfile.open(archive_path, "r:gz") as archive:
    archive.extractall(root)
for path in [
    *chunks,
    archive_path,
    root / "scripts/apply_cn130_pit_fundamental_veto_payload.py",
]:
    path.unlink(missing_ok=True)
