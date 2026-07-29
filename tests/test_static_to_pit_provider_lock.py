"""Provider-identity lock tests for authoritative decomposition runs."""

from __future__ import annotations

from pathlib import Path

import pytest

import src.research.static_to_pit_provider_lock as provider_lock


def test_authoritative_identities_match_committed_evidence() -> None:
    assert provider_lock.STATIC_REFERENCE_PROVIDER_IDENTITY == (
        "66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8"
    )
    assert provider_lock.DECOMPOSITION_PROVIDER_IDENTITY == (
        "6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407"
    )


def test_provider_identity_lock_accepts_exact_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        provider_lock,
        "load_provider_manifest",
        lambda *_args, **_kwargs: {
            "provider_identity_sha256": provider_lock.STATIC_REFERENCE_PROVIDER_IDENTITY
        },
    )
    result = provider_lock.require_provider_identity(
        tmp_path / "static",
        expected_identity=provider_lock.STATIC_REFERENCE_PROVIDER_IDENTITY,
        role="static_reference",
    )
    assert result["provider_identity_sha256"] == (
        provider_lock.STATIC_REFERENCE_PROVIDER_IDENTITY
    )


def test_provider_identity_lock_rejects_different_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        provider_lock,
        "load_provider_manifest",
        lambda *_args, **_kwargs: {"provider_identity_sha256": "wrong"},
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        provider_lock.require_provider_identity(
            tmp_path / "static",
            expected_identity=provider_lock.STATIC_REFERENCE_PROVIDER_IDENTITY,
            role="static_reference",
        )


def test_provider_pair_must_use_distinct_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be different"):
        provider_lock.validate_authoritative_provider_pair(
            tmp_path / "same",
            tmp_path / "same",
        )
