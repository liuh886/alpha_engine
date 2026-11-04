"""Pinned source archive recovery: verify authoritative locator, bytes and file rights."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.research.cloud_exchange import ExchangeError
from src.research.source_archive_recovery import _source_plan, verify_archive


class SourceRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.manifest_dir = (self.root / "data/research/model_data_bundle_v1/sources")
        self.manifest_dir.mkdir(parents=True)
        self.path = self.root / "archive.zip"
        with zipfile.ZipFile(self.path, "w") as z:
            z.writestr("events.jsonl", "{\"date\": \"2026-09-30\"}\n")
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        sources = []
        for name in ("us_events", "qqq_reference"):
            sources.append({
                "source_id": name,
                "source_kind": "test",
                "market": "us",
                "evidence_cutoff": "2026-09-30",
                "artifact_digest": "sha256:" + self.sha,
                "durable_git": {
                    "repository": "liuh886/alpha-engine-data-archive",
                    "commit": "a" * 40,
                    "path": f"archives/{name}.zip",
                    "sha256": self.sha,
                    "size_bytes": self.path.stat().st_size,
                },
                "durable_release": None,
            })
        for name in ("cn_events", "cn_alpha158"):
            sources.append({
                "source_id": name,
                "source_kind": "test",
                "market": "cn",
                "evidence_cutoff": "2026-09-04",
                "artifact_digest": "sha256:" + self.sha,
                "durable_git": None,
                "durable_release": {
                    "tag": f"model-data-source-{name}",
                    "asset_name": f"{name}.zip",
                    "sha256": self.sha,
                    "size_bytes": self.path.stat().st_size,
                },
            })
        self.data = {"sources": sources}
        self._write()

    def _write(self) -> None:
        (self.manifest_dir / "governed-source-receipt.json").write_text(
            json.dumps(self.data), encoding="utf-8"
        )

    def test_list_has_all_four_authoritative_archives(self) -> None:
        results = _source_plan(self.root)
        self.assertEqual(set(results), {"us_events", "cn_events", "cn_alpha158",
                                       "qqq_reference"})
        self.assertEqual(results["us_events"]["sha256"], self.sha)
        self.assertIn("releases/download/", results["cn_events"]["url"])

    def test_verify_accepts_real_zip_matching_source_receipt(self) -> None:
        record = _source_plan(self.root)["us_events"]
        self.assertEqual(verify_archive(self.path, record)["status"], "VERIFIED")

    def test_verify_denies_tampered_bytes(self) -> None:
        record = _source_plan(self.root)["us_events"]
        self.path.write_bytes(b"not zip data")
        with self.assertRaisesRegex(ExchangeError, "length mismatch"):
            verify_archive(self.path, record)

    def test_hash_change_in_receipt_fails_source_plan(self) -> None:
        self.data["sources"][0]["artifact_digest"] = "sha256:" + "0" * 64
        self._write()
        with self.assertRaisesRegex(ExchangeError, "differs"):
            _source_plan(self.root)

    def test_unexpected_repository_is_denied(self) -> None:
        self.data["sources"][0]["durable_git"]["repository"] = "attacker/fake"
        self._write()
        with self.assertRaisesRegex(ExchangeError, "unexpected"):
            _source_plan(self.root)


if __name__ == "__main__":
    unittest.main()
