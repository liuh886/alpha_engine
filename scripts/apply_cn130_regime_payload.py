from __future__ import annotations

import base64
import hashlib
import tarfile
from pathlib import Path

EXPECTED_SHA256 = "393a1cca34a0d1899356de827f9f59ff64d3edbd79b7dec693501d8c5cdec02e"

root = Path.cwd()
part_paths = sorted((root / ".github").glob("cn130_regime_payload.part*"))
if not part_paths:
    raise RuntimeError("payload parts not found")
encoded = "".join(path.read_text(encoding="ascii") for path in part_paths)
archive_path = root / ".research-cn130-regime-payload.tar.gz"
archive_path.write_bytes(base64.b64decode(encoded))
actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
if actual != EXPECTED_SHA256:
    raise RuntimeError(f"payload sha mismatch: {actual}")
with tarfile.open(archive_path, "r:gz") as archive:
    archive.extractall(root)
for path in (
    *part_paths,
    archive_path,
    root / "scripts/apply_cn130_regime_payload.py",
    root / ".github/workflows/cn130-regime-payload-apply.yml",
):
    path.unlink(missing_ok=True)
