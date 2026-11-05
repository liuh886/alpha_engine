"""E1-A v5 preflight fails closed: immutable data, cloud rights separated."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src.research.cloud_exchange import ExchangeError
from src.research.e1a_price_preflight import inspect


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class E1APricePreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.archive = self.root / "us_market_history.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr(
                "files/data/research/model_data_bundle_v1/components/us-selected-pool-prices.json",
                json.dumps({"selected_providers": {"AAPL": "synthetic_test"}}))
        self.source_revision = "3" * 40
        self.bundle = self.root / "bundle-manifest.json"
        self.summary = {
            "schema_version": "p2_local_research_bundle_v2",
            "status": "PARTIAL",
            "research_only": True,
            "trade_ready": False,
            "pit_certified": False,
            "colab_executed": False,
            "transfer_scope": "local_only",
            "owner_approved_private_cloud_copy": False,
            "repo_revision": self.source_revision,
            "files": [{"path": "us_market_history.zip",
                       "sha256": digest(self.archive),
                       "size_bytes": self.archive.stat().st_size}],
        }
        self.bundle.write_text(json.dumps(self.summary), encoding="utf-8")
        self.history = {
            "schema_version": "p2_local_market_history_v1", "market": "us",
            "pool_id": "us_selected_equities_v2", "candidate_count": 87,
            "repo_revision": self.source_revision,
            "data_cutoff": "2026-11-03",
            "research_only": True, "trade_ready": False, "pit_certified": False,
            "reference_symbols": ["QQQ"],
        }

    def _check(self, rights: Path | None = None) -> dict:
        with patch("src.research.e1a_price_preflight.verify_local_history",
                   return_value=self.history):
            return inspect(manifest_path=self.bundle, archive_path=self.archive,
                           expected_manifest_sha256=digest(self.bundle),
                           expected_archive_sha256=digest(self.archive), rights_record=rights)

    def _approved(self) -> Path:
        path = self.root / "rights.json"
        path.write_text(json.dumps({
            "schema_version": "e1a_price_cloud_rights_v1",
            "market": "us",
            "bundle_manifest_sha256": digest(self.bundle),
            "history_archive_sha256": digest(self.archive),
            "cloud_processing_purpose": "private_colab_daily_price_research",
            "owner_approved_private_cloud_processing": True,
            "reviewed_at": "2026-11-06",
            "provider_rights": [{
                "provider": "synthetic_test",
                "terms_url": "https://example.invalid/terms",
                "private_cloud_compute_permitted": True,
                "review_basis": "Synthetic permission fixture; not a real-world license.",
            }],
        }), encoding="utf-8")
        return path

    def test_pinned_real_source_contract_preflight_is_not_model_approval(self) -> None:
        output = self._check()
        self.assertEqual(output["candidate_count"], 87)
        self.assertEqual(output["cloud_execution_rights"]["status"],
                         "BLOCKED_NO_PER_SOURCE_CLOUD_RIGHTS_RECORD")
        self.assertFalse(output["model_execution_authorized"])
        self.assertTrue(output["source_frozen_local_only"])

    def test_explicit_owner_rights_record_is_not_vendor_certification(self) -> None:
        output = self._check(self._approved())
        self.assertEqual(output["cloud_execution_rights"]["status"],
                         "OWNER_ATTESTATION_RECORDED_NOT_VENDOR_CERTIFIED")
        self.assertFalse(output["model_execution_authorized"])

    def test_wrong_manifest_hash_is_rejected(self) -> None:
        with patch("src.research.e1a_price_preflight.verify_local_history",
                   return_value=self.history):
            with self.assertRaisesRegex(ExchangeError, "SHA differs"):
                inspect(manifest_path=self.bundle, archive_path=self.archive,
                        expected_manifest_sha256="f" * 64,
                        expected_archive_sha256=digest(self.archive))

    def test_wrong_archive_binding_is_rejected(self) -> None:
        self.summary["files"][0]["sha256"] = "0" * 64
        self.bundle.write_text(json.dumps(self.summary), encoding="utf-8")
        with self.assertRaisesRegex(ExchangeError, "not bound"):
            self._check()

    def test_approval_for_different_bundle_is_rejected(self) -> None:
        rights = self._approved()
        j = json.loads(rights.read_text())
        j["bundle_manifest_sha256"] = "b" * 64
        rights.write_text(json.dumps(j))
        with self.assertRaisesRegex(ExchangeError, "data bindings"):
            self._check(rights)

    def test_provider_license_not_attested_is_rejected(self) -> None:
        rights = self._approved()
        j = json.loads(rights.read_text())
        j["provider_rights"][0]["private_cloud_compute_permitted"] = False
        rights.write_text(json.dumps(j))
        with self.assertRaisesRegex(ExchangeError, "explicit checked"):
            self._check(rights)

    def test_approval_for_unrelated_provider_cannot_approve_actual_source(self) -> None:
        rights = self._approved()
        doc = json.loads(rights.read_text())
        doc["provider_rights"][0]["provider"] = "unrelated_provider"
        rights.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ExchangeError, "actual source providers"):
            self._check(rights)

    def test_wrong_producer_revision_is_rejected(self) -> None:
        self.history["repo_revision"] = "4" * 40
        with self.assertRaisesRegex(ExchangeError, "producer identity"):
            self._check()

    def test_cannot_expand_scope_to_cn_without_new_study(self) -> None:
        with self.assertRaisesRegex(ExchangeError, "US87 price only"):
            inspect(manifest_path=self.bundle, archive_path=self.archive,
                    expected_manifest_sha256=digest(self.bundle),
                    expected_archive_sha256=digest(self.archive), market="cn")


if __name__ == "__main__":
    unittest.main()
