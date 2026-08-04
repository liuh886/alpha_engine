from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = sorted((ROOT / ".github").glob("cn130_payload.chunk*"))
EXPECTED_SHA256 = "a50ace21ad8d9f4acdf7df9500a47936b1c34ccdb0f673f80179b71f367ede09"

if len(CHUNKS) != 16:
    raise RuntimeError(f"expected 16 payload chunks, found {len(CHUNKS)}")

encoded = "".join(path.read_text(encoding="utf-8") for path in CHUNKS)
data = base64.b64decode(encoded, validate=True)
observed_sha256 = hashlib.sha256(data).hexdigest()
if observed_sha256 != EXPECTED_SHA256:
    raise RuntimeError(
        f"payload sha256 mismatch: {observed_sha256} != {EXPECTED_SHA256}"
    )

with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    for member in archive.getmembers():
        target = (ROOT / member.name).resolve()
        if ROOT not in target.parents and target != ROOT:
            raise RuntimeError(f"unsafe payload member: {member.name}")
    archive.extractall(ROOT)

remove = [
    ROOT / ".github" / "cn130_payload.tar.gz.b64",
    *(ROOT / ".github").glob("cn130_payload.part*"),
    *CHUNKS,
    ROOT / "scripts" / "apply_cn130_payload.py",
    ROOT / ".github" / "workflows" / "cn130-apply-payload.yml",
]
for path in remove:
    path.unlink(missing_ok=True)
