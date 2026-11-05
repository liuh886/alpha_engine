"""Isolated v5 root staging: no overwrite, exact source bytes and tamper detection."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.research.cloud_exchange import ExchangeError
from src.research.v5_isolated_staging import stage, verify_stage


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class V5StagingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.archive = self.root / "history.zip"
        self.manifest = self.root / "bundle-manifest.json"
        self.manifest.write_bytes(b"test-manifest")
        self.files = {
            "configs/research_universes/us_selected_equities_v2.yaml": b"pool_id: us_selected_equities_v2\nsymbols: [AAPL]\n",
            "data/research/market_evidence/us/catalog.json": b'{"pool_id":"us_selected_equities_v2"}',
        }
        entries = [{"path": k, "size": len(v), "sha256": sha(v)}
                   for k, v in self.files.items()]
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({"files": entries}))
            for path, data in self.files.items():
                z.writestr("files/" + path, data)
        self.output = self.root / "isolated"
        self.pinned_manifest = sha(self.manifest.read_bytes())
        self.pinned_archive = sha(self.archive.read_bytes())
        self.verified = {
            "data_status": "VERIFIED_US87_COMPLETE_RETAINED_PRICE_DOMAIN",
            "source_producer_revision": "1" * 40,
            "data_cutoff": "2026-11-03",
        }

    def _stage(self) -> dict:
        with patch("src.research.v5_isolated_staging.inspect_price",
                   return_value=self.verified):
            return stage(manifest=self.manifest, archive=self.archive,
                         expected_manifest_sha=self.pinned_manifest,
                         expected_archive_sha=self.pinned_archive,
                         output_root=self.output)

    def test_stage_verified_source_and_declared_limitations(self) -> None:
        r = self._stage()
        self.assertEqual(r["files"], 2)
        self.assertFalse(r["cloud_processing_rights_granted"])
        doc = verify_stage(self.output)
        self.assertEqual(doc["history_archive_sha256"], self.pinned_archive)
        self.assertTrue(doc["research_only"])
        self.assertFalse(doc["trade_ready"])

    def test_no_overwrite(self) -> None:
        self._stage()
        with self.assertRaisesRegex(ExchangeError, "new and outside"):
            self._stage()

    def test_detect_tamper(self) -> None:
        self._stage()
        p = self.output / "data/research/market_evidence/us/catalog.json"
        p.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ExchangeError, "altered"):
            verify_stage(self.output)

    def test_detect_unlisted_file(self) -> None:
        self._stage()
        (self.output / "bad.json").write_text("unexpected", encoding="utf-8")
        with self.assertRaisesRegex(ExchangeError, "unexpected"):
            verify_stage(self.output)

    def test_reject_path_escape(self) -> None:
        with zipfile.ZipFile(self.archive, "w") as z:
            data = b"danger"
            z.writestr("manifest.json", json.dumps({
                "files": [{"path": "../escape.json", "size": len(data),
                           "sha256": sha(data)}]}))
            z.writestr("files/../escape.json", data)
        with self.assertRaisesRegex(ExchangeError, "invalid staged path"):
            self._stage()


if __name__ == "__main__":
    unittest.main()
