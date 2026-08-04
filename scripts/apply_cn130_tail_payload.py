from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = sorted((ROOT / ".github").glob("cn130_tail_payload.part*"))
EXPECTED_SHA256 = "5f3977fa77b76db7379420a5b8fe6e7411270710af4f30178855b7a9f802a6ca"

if len(CHUNKS) != 10:
    raise RuntimeError(f"expected 10 payload chunks, found {len(CHUNKS)}")

encoded = "".join(path.read_text(encoding="utf-8") for path in CHUNKS)
data = base64.b64decode(encoded, validate=True)
observed = hashlib.sha256(data).hexdigest()
if observed != EXPECTED_SHA256:
    raise RuntimeError(f"payload sha256 mismatch: {observed} != {EXPECTED_SHA256}")

with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
    members = archive.getmembers()
    for member in members:
        target = (ROOT / member.name).resolve()
        if target != ROOT and ROOT not in target.parents:
            raise RuntimeError(f"unsafe payload member: {member.name}")
    archive.extractall(ROOT, members=members, filter="data")

for path in [*CHUNKS, ROOT / "scripts" / "apply_cn130_tail_payload.py"]:
    path.unlink(missing_ok=True)
