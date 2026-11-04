"""Contract tests for the Colab exchange transport; no Drive access or real data."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.research.cloud_exchange import ExchangeError, pack, stage, verify


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


class TestCloudExchange(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        git("init", "-q", cwd=self.repo)
        git("config", "user.name", "Alpha Test", cwd=self.repo)
        git("config", "user.email", "alpha@example.invalid", cwd=self.repo)
        self.pool = "configs/research_universes/us_selected_equities_v2.yaml"
        self.source = "data/research/model_data_bundle_v1/data-components.json"
        self.data = "data/csv_clean/FAKE.csv"
        for name, content in (
            (self.pool, "pool: us_selected_equities_v2\n"),
            (self.source, '{"status": "synthetic_fixture"}\n'),
        ):
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        git("add", ".", cwd=self.repo)
        git("commit", "-qm", "synthetic fixture", cwd=self.repo)
        self.commit = git("rev-parse", "HEAD", cwd=self.repo)
        target = self.repo / self.data
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("session,close\n2026-11-03,10\n", encoding="utf-8")
        self.recipe = {
            "schema_version": "alpha_research_exchange_v1",
            "study_id": "pilot_us87",
            "market": "us",
            "pool_id": "us_selected_equities_v2",
            "data_cutoff": "2026-11-03",
            "repo_revision": self.commit,
            "source_manifest_path": self.source,
            "source_manifest_sha256": sha(self.repo / self.source),
            "owner_approved_private_cloud_copy": True,
            "rights_class": "private_cloud_research_allowed",
            "inputs": [
                {"path": self.pool, "sha256": sha(self.repo / self.pool), "role": "pool_spec"},
                {"path": self.source, "sha256": sha(self.repo / self.source),
                 "role": "source_manifest"},
                {"path": self.data, "sha256": sha(self.repo / self.data), "role": "data"},
            ],
        }
        self.spec = self.base / "recipe.json"
        self._save_recipe()
        self.archive = self.base / "exchange.zip"

    def _save_recipe(self) -> None:
        self.spec.write_text(json.dumps(self.recipe), encoding="utf-8")

    def _pack(self) -> dict:
        self._save_recipe()
        return pack(self.repo, self.spec, self.archive)

    def _clone(self) -> Path:
        clone = self.base / "clone"
        git("clone", "-q", str(self.repo), str(clone), cwd=self.base)
        self.assertEqual(git("rev-parse", "HEAD", cwd=clone), self.commit)
        return clone

    def test_private_immutable_archive_and_isolated_stage(self) -> None:
        built = self._pack()
        self.assertEqual(built["sha256"], sha(self.archive))
        manifest = verify(self.archive)
        self.assertEqual(manifest["repo_revision"], self.commit)
        self.assertFalse(manifest["pit_certified"])
        self.assertFalse(manifest["trade_ready"])
        clone = self._clone()
        result = stage(self.archive, clone)
        self.assertEqual(result["staged_new_files"], 1)
        self.assertEqual(sha(clone / self.data), sha(self.repo / self.data))
        self.assertEqual(stage(self.archive, clone)["staged_new_files"], 0)

    def test_bytes_are_deterministic_for_same_frozen_inputs(self) -> None:
        first = self._pack()
        second = pack(self.repo, self.spec, self.base / "exchange_again.zip")
        self.assertEqual(first["sha256"], second["sha256"])

    def test_existing_archive_is_not_overwritten_or_deleted(self) -> None:
        self.archive.write_bytes(b"existing owner file")
        with self.assertRaises(ExchangeError):
            self._pack()
        self.assertEqual(self.archive.read_bytes(), b"existing owner file")

    def test_rights_must_be_explicitly_approved(self) -> None:
        self.recipe["owner_approved_private_cloud_copy"] = False
        with self.assertRaisesRegex(ExchangeError, "manual approval"):
            self._pack()

    def test_unknown_source_rights_fail_closed(self) -> None:
        self.recipe["rights_class"] = "unknown"
        with self.assertRaisesRegex(ExchangeError, "rights"):
            self._pack()

    def test_pinned_data_mismatch_refuses_pack(self) -> None:
        self.recipe["inputs"][-1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ExchangeError, "hash mismatch"):
            self._pack()

    def test_pinned_canonical_manifest_mismatch_refuses_pack(self) -> None:
        self.recipe["source_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ExchangeError, "source"):
            self._pack()

    def test_revision_mismatch_refuses_pack(self) -> None:
        self.recipe["repo_revision"] = "0" * 40
        with self.assertRaisesRegex(ExchangeError, "revision"):
            self._pack()

    def test_sensitive_path_prefix_is_rejected(self) -> None:
        self.recipe["inputs"][-1]["path"] = (
            "data/research/strategy_signal_ledgers/private.json"
        )
        with self.assertRaises(ExchangeError):
            self._pack()

    def test_traversal_is_rejected(self) -> None:
        self.recipe["inputs"][-1]["path"] = "data/csv_clean/../../.env"
        with self.assertRaises(ExchangeError):
            self._pack()

    def test_tampered_archive_refuses_verify_and_stage(self) -> None:
        self._pack()
        tampered = self.base / "tampered.zip"
        with zipfile.ZipFile(self.archive, "r") as src, zipfile.ZipFile(tampered, "w") as dst:
            for member in src.infolist():
                content = src.read(member)
                if member.filename == f"files/{self.data}":
                    content = b"session,close\n2026-11-03,90\n"
                dst.writestr(member, content)
        with self.assertRaisesRegex(ExchangeError, "content mismatch"):
            verify(tampered)
        clone = self._clone()
        with self.assertRaises(ExchangeError):
            stage(tampered, clone)
        self.assertFalse((clone / self.data).exists())

    def test_conflicting_checkout_file_is_never_replaced(self) -> None:
        self._pack()
        clone = self._clone()
        local_data = clone / self.data
        local_data.parent.mkdir(parents=True, exist_ok=True)
        local_data.write_text("do not overwrite\n", encoding="utf-8")
        with self.assertRaisesRegex(ExchangeError, "refusing to overwrite"):
            stage(self.archive, clone)
        self.assertEqual(local_data.read_text(), "do not overwrite\n")

    def test_wrong_target_commit_is_rejected(self) -> None:
        self._pack()
        clone = self._clone()
        (clone / "another.txt").write_text("new revision", encoding="utf-8")
        git("add", ".", cwd=clone)
        git("config", "user.name", "Alpha Test", cwd=clone)
        git("config", "user.email", "alpha@example.invalid", cwd=clone)
        git("commit", "-qm", "different commit", cwd=clone)
        with self.assertRaisesRegex(ExchangeError, "exact pinned"):
            stage(self.archive, clone)

    def test_frontend_output_is_forbidden(self) -> None:
        self._save_recipe()
        with self.assertRaisesRegex(ExchangeError, "frontend"):
            pack(self.repo, self.spec, self.repo / "qlib-dashboard" / "public" / "data.zip")


if __name__ == "__main__":
    unittest.main()
