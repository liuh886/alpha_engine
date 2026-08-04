from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / ".github" / "cn130_payload.tar.gz.b64"
REMOVE = [
    PAYLOAD,
    ROOT / "scripts" / "apply_cn130_payload.py",
    ROOT / ".github" / "workflows" / "cn130-apply-payload.yml",
]

encoded = PAYLOAD.read_text(encoding="utf-8").strip()
data = base64.b64decode(encoded, validate=True)
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    for member in archive.getmembers():
        target = (ROOT / member.name).resolve()
        if ROOT not in target.parents and target != ROOT:
            raise RuntimeError(f"unsafe payload member: {member.name}")
    archive.extractall(ROOT)

for path in REMOVE:
    path.unlink(missing_ok=True)
