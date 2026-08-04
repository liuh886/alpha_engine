from __future__ import annotations

import base64
import hashlib
import shutil
import tarfile
from pathlib import Path

EXPECTED_SHA256 = "393a1cca34a0d1899356de827f9f59ff64d3edbd79b7dec693501d8c5cdec02e"

root = Path.cwd()
payload_path = root / ".github/cn130_regime_payload.b64"
archive_path = root / ".research-cn130-regime-payload.tar.gz"
archive_path.write_bytes(base64.b64decode(payload_path.read_text(encoding="ascii")))
actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if actual != EXPECTED_SHA256:
    raise RuntimeError(f"payload sha mismatch: {actual}")
with tarfile.open(archive_path, "r:gz") as archive:
    archive.extractall(root)
for path in (
    payload_path,
    archive_path,
    root / "scripts/apply_cn130_regime_payload.py",
    root / ".github/workflows/cn130-regime-payload-apply.yml",
):
    path.unlink(missing_ok=True)
