"""Data-first P2 exchange: a complete market-history roster or an explicit BLOCKED gate."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.research.cloud_exchange import ExchangeError, verify
from src.research.comprehensive_dataset import approved_pack, plan


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True,
                                   stderr=subprocess.DEVNULL).strip()


class FullMarketHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.root = self.home / "alpha"
        self.root.mkdir()
        self.members = [f"U{x:03}" for x in range(87)]
        write(self.root, "configs/pools/selected_pool_registry_v1.yaml",
              'markets:\n  us:\n    active_pool_id: us_selected_equities_v2\n'
              '    pool_spec: configs/research_universes/us_selected_equities_v2.yaml\n'
              '    candidate_count: 87\n')
        write(self.root, "configs/pools/reference_instrument_registry_v1.yaml",
              "reference_symbols: [QQQ]\n")
        write(self.root, "configs/research_universes/us_selected_equities_v2.yaml",
              "pool_id: us_selected_equities_v2\nsymbols:\n" +
              "".join(f"  - {symbol}\n" for symbol in self.members))
        component_path = (
            "data/research/model_data_bundle_v1/components/us-selected-pool-prices.json"
        )
        write(self.root, component_path, '{"pool_id": "us_selected_equities_v2"}\n')
        component_hash = sha(self.root / component_path)
        components = [{
            "component_id": "prices.us_selected_equities_v2",
            "market": "us", "pool_id": "us_selected_equities_v2",
            "ready_symbol_count": 87, "status": "ready",
            "manifest_path": "components/us-selected-pool-prices.json",
            "manifest_sha256": component_hash,
        }]
        write(self.root, "data/research/model_data_bundle_v1/data-components.json",
              json.dumps(components))
        for name in ("model-data-readiness.json", "model-data-bundle.json",
                     "training-profiles.json", "sources/governed-source-receipt.json"):
            write(self.root, f"data/research/model_data_bundle_v1/{name}", "{}\n")
        records = []
        for symbol in [*self.members, "QQQ"]:
            rel = f"data/research/market_evidence/us/symbols/{symbol}.json"
            write(self.root, rel, json.dumps({
                "symbol": symbol, "bars": [{"date": "2026-11-03", "close": 1}],
            }) + "\n")
            records.append({
                "symbol": symbol, "path": f"symbols/{symbol}.json",
                "roles": ["benchmark" if symbol == "QQQ" else "selected_pool_candidate"],
                "sha256": sha(self.root / rel), "start": "2021-01-04",
                "factor_series_available": True,
            })
        diag = "data/research/market_evidence/us/factor-diagnostics.json"
        write(self.root, diag, '{"status":"synthetic"}\n')
        market = {
            "market": "us", "pool_id": "us_selected_equities_v2",
            "candidate_count": 87, "benchmark": "QQQ", "auxiliary_symbols": [],
            "research_only": True, "cutoff": "2026-11-03", "start": "2021-01-01",
            "provider_manifest_sha256": component_hash,
            "factor_diagnostics_path": "factor-diagnostics.json",
            "factor_diagnostics_sha256": sha(self.root / diag),
            "symbols": records,
        }
        self.catalog_path = "data/research/market_evidence/us/catalog.json"
        write(self.root, self.catalog_path, json.dumps(market))
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Alpha Test")
        git(self.root, "config", "user.email", "alpha@example.invalid")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "synthetic 87-stock fixture")
        self.approval = self.home / "rights_approval.json"
        self.archive = self.home / "us87_all.zip"

    def _rights(self, yes: bool = True) -> None:
        self.approval.write_text(json.dumps({
            "market": "us",
            "source_manifest_sha256": sha(self.root / self.catalog_path),
            "rights_class": "private_cloud_research_allowed" if yes else "unknown",
            "owner_approved_private_cloud_copy": yes,
        }), encoding="utf-8")

    def test_full_history_catalog_without_fundamentals_is_not_full_research(self) -> None:
        report = plan(self.root, "us")
        self.assertEqual(report["readiness"]["market_history"], "READY_FOR_RIGHTS_REVIEW")
        self.assertEqual(report["readiness"]["full_research"], "BLOCKED")
        row = report["markets"][0]
        self.assertEqual(row["candidate_symbol_count"], 87)
        self.assertEqual(row["reference_symbols"], ["QQQ"])
        self.assertEqual(row["candidate_factor_series"], 87)
        self.assertFalse(row["market_history_failures"])
        self.assertEqual(row["full_research_status"], "BLOCKED_INCOMPLETE_SOURCE_PAYLOAD")

    def test_complete_roster_exports_a_verified_archive(self) -> None:
        self._rights(True)
        result = approved_pack(self.root, "us", self.approval, self.archive)
        manifest = verify(self.archive)
        self.assertEqual(result["tier"], "complete_market_history_only")
        self.assertEqual(result["sha256"], sha(self.archive))
        self.assertEqual(result["input_count"], len(manifest["files"]))
        self.assertEqual(sum(x["path"].endswith(".json") and
                             "/symbols/" in x["path"] for x in manifest["files"]), 88)

    def test_missing_data_blocks_complete_export(self) -> None:
        self._rights(True)
        (self.root / "data/research/market_evidence/us/symbols/U000.json").unlink()
        with self.assertRaisesRegex(ExchangeError, "market-history"):
            approved_pack(self.root, "us", self.approval, self.archive)
        self.assertFalse(self.archive.exists())

    def test_catalog_tampering_blocks_export(self) -> None:
        self._rights(True)
        file = self.root / "data/research/market_evidence/us/symbols/U000.json"
        file.write_text('{"symbol":"U000", "bars":[]}', encoding="utf-8")
        result = plan(self.root, "us")
        self.assertEqual(result["readiness"]["market_history"], "BLOCKED")

    def test_rights_not_approved_blocks_export(self) -> None:
        self._rights(False)
        with self.assertRaisesRegex(ExchangeError, "provider-rights"):
            approved_pack(self.root, "us", self.approval, self.archive)

    def test_partial_candidate_catalog_is_not_complete(self) -> None:
        cat = self.root / self.catalog_path
        value = json.loads(cat.read_text(encoding="utf-8"))
        value["symbols"] = value["symbols"][1:]
        cat.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ExchangeError, "candidates differ"):
            plan(self.root, "us")


if __name__ == "__main__":
    unittest.main()
