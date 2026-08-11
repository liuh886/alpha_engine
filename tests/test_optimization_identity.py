"""Tests for src.optimization.identity."""
import json, tempfile
from pathlib import Path
from src.optimization.identity import (
    load_provider_identity,
    verify_universe_membership,
    ProviderIdentity,
    UniverseMembership,
)


class TestLoadProviderIdentity:
    def test_valid_manifest(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "provider_identity_sha256": "abc123def456",
                "market": "us",
                "instruments": {"count": 87, "path": "us.txt", "sha256": "x"},
                "calendar": {"first_day": "2020-01-02", "last_day": "2026-06-24", "session_count": 1627, "path": "day.txt", "sha256": "y"},
            }, f)
            path = f.name
        try:
            pid = load_provider_identity(path)
            assert pid.market == "us"
            assert pid.identity_sha256 == "abc123def456"
            assert pid.instrument_count == 87
            assert pid.session_count == 1627
            assert pid.matches("abc123def456")
            assert not pid.matches("different_hash")
        finally:
            Path(path).unlink()

    def test_missing_file(self):
        import pytest
        with pytest.raises(FileNotFoundError):
            load_provider_identity("/nonexistent/path.json")

    def test_malformed_manifest(self):
        import pytest
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"market": "us"}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="missing fields"):
                load_provider_identity(path)
        finally:
            Path(path).unlink()


class TestUniverseMembership:
    def test_exact_match(self):
        u = verify_universe_membership(["A", "B", "C"], {"A", "B", "C"}, "test")
        assert u.is_exact_match
        assert u.missing_count == 0
        assert u.extra_count == 0
        assert u.declared_count == 3
        assert u.available_count == 3

    def test_missing_symbols(self):
        u = verify_universe_membership(["A", "B", "C", "D"], {"A", "B", "C"}, "test")
        assert not u.is_exact_match
        assert u.missing_symbols == ("D",)
        assert u.available_count == 3

    def test_extra_symbols(self):
        u = verify_universe_membership(["A", "B"], {"A", "B", "C", "D"}, "test")
        assert not u.is_exact_match
        assert u.extra_symbols == ("C", "D")
        assert u.available_count == 2

    def test_no_common(self):
        u = verify_universe_membership(["A", "B"], {"C", "D"}, "test")
        assert u.available_count == 0
        assert len(u.missing_symbols) == 2
