"""Unit tests for provider diagnostics JSON writing.

Tests _write_provider_diagnostics() with one success and one failure,
verifying the output JSON structure and correctness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestWriteProviderDiagnostics:
    """Test _write_provider_diagnostics function."""

    def test_write_provider_diagnostics_success_and_failure(self, tmp_path):
        """Write diagnostics with one success and one failure, verify JSON output."""
        from scripts.update_data import _write_provider_diagnostics

        # Create mock diagnostics with one success and one failure
        diagnostics = [
            {
                "symbol": "000001",
                "market": "cn",
                "ok": True,
                "final_state": "updated",
                "attempts": [
                    {"provider": "baostock", "ok": True, "error": None},
                ],
            },
            {
                "symbol": "600519",
                "market": "cn",
                "ok": False,
                "final_state": "failed",
                "attempts": [
                    {"provider": "yfinance", "ok": False, "error": "timeout"},
                    {"provider": "baostock", "ok": False, "error": "no data"},
                ],
            },
        ]

        # Write diagnostics
        _write_provider_diagnostics(diagnostics, tmp_path)

        # Verify latest_provider_attempts.json exists
        latest_path = tmp_path / "data_update_diagnostics" / "latest_provider_attempts.json"
        assert latest_path.exists(), "latest_provider_attempts.json not created"

        # Verify JSON parses
        content = latest_path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, dict), "JSON should be a dict"

        # Verify total_symbols, succeeded, failed are correct
        assert data["total_symbols"] == 2, f"Expected total_symbols=2, got {data['total_symbols']}"
        assert data["succeeded"] == 1, f"Expected succeeded=1, got {data['succeeded']}"
        assert data["failed"] == 1, f"Expected failed=1, got {data['failed']}"

        # Verify attempts are preserved
        symbols = data["symbols"]
        assert len(symbols) == 2, f"Expected 2 symbols, got {len(symbols)}"

        # Check first symbol (success)
        sym1 = symbols[0]
        assert sym1["symbol"] == "000001"
        assert sym1["ok"] is True
        assert sym1["final_state"] == "updated"
        assert len(sym1["attempts"]) == 1
        assert sym1["attempts"][0]["provider"] == "baostock"
        assert sym1["attempts"][0]["ok"] is True

        # Check second symbol (failure)
        sym2 = symbols[1]
        assert sym2["symbol"] == "600519"
        assert sym2["ok"] is False
        assert sym2["final_state"] == "failed"
        assert len(sym2["attempts"]) == 2
        assert sym2["attempts"][0]["provider"] == "yfinance"
        assert sym2["attempts"][0]["ok"] is False
        assert sym2["attempts"][0]["error"] == "timeout"

    def test_write_provider_diagnostics_creates_timestamped_copy(self, tmp_path):
        """Verify a timestamped copy is also created."""
        from scripts.update_data import _write_provider_diagnostics

        diagnostics = [
            {
                "symbol": "AAPL",
                "market": "us",
                "ok": True,
                "final_state": "updated",
                "attempts": [{"provider": "yfinance", "ok": True, "error": None}],
            },
        ]

        _write_provider_diagnostics(diagnostics, tmp_path)

        diag_dir = tmp_path / "data_update_diagnostics"
        assert diag_dir.exists()

        # Check that at least one timestamped file exists
        timestamped_files = list(diag_dir.glob("provider_attempts_*.json"))
        assert len(timestamped_files) >= 1, "No timestamped provider attempts file found"

    def test_write_provider_diagnostics_empty_list(self, tmp_path):
        """Verify diagnostics with empty list writes correctly."""
        from scripts.update_data import _write_provider_diagnostics

        _write_provider_diagnostics([], tmp_path)

        latest_path = tmp_path / "data_update_diagnostics" / "latest_provider_attempts.json"
        assert latest_path.exists()

        data = json.loads(latest_path.read_text(encoding="utf-8"))
        assert data["total_symbols"] == 0
        assert data["succeeded"] == 0
        assert data["failed"] == 0
        assert data["symbols"] == []

    def test_write_provider_diagnostics_schema_failed(self, tmp_path):
        """Verify schema_failed status is written correctly."""
        from scripts.update_data import _write_provider_diagnostics

        diagnostics = [
            {
                "symbol": "BADSTOCK",
                "market": "cn",
                "ok": False,
                "final_state": "schema_failed",
                "validation_error": "schema validation failed",
                "schema_errors": ["missing close column", "empty dataframe"],
                "attempts": [
                    {"provider": "baostock", "ok": True, "error": None},
                ],
            },
        ]

        _write_provider_diagnostics(diagnostics, tmp_path)

        latest_path = tmp_path / "data_update_diagnostics" / "latest_provider_attempts.json"
        data = json.loads(latest_path.read_text(encoding="utf-8"))

        assert data["total_symbols"] == 1
        assert data["succeeded"] == 0
        assert data["failed"] == 1

        sym = data["symbols"][0]
        assert sym["final_state"] == "schema_failed"
        assert sym["validation_error"] == "schema validation failed"
        assert "missing close column" in sym["schema_errors"]
