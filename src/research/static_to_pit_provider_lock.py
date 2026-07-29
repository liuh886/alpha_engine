"""Authoritative provider identities for the static-to-PIT decomposition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.data.market_provider import load_provider_manifest


STATIC_REFERENCE_PROVIDER_IDENTITY = (
    "66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8"
)
DECOMPOSITION_PROVIDER_IDENTITY = (
    "6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407"
)


def require_provider_identity(
    provider_uri: str | Path,
    *,
    expected_identity: str,
    role: str,
) -> dict[str, Any]:
    """Load a US provider manifest and require the committed identity."""

    provider = Path(provider_uri).resolve()
    manifest = load_provider_manifest(
        provider,
        expected_market="us",
        required=True,
        verify_files=True,
    )
    if manifest is None:
        raise ValueError(f"{role} provider manifest is required")
    actual = str(manifest.get("provider_identity_sha256", ""))
    if actual != expected_identity:
        raise ValueError(
            f"{role} provider identity mismatch: expected={expected_identity} "
            f"actual={actual} path={provider}"
        )
    return {
        "role": role,
        "provider_uri": str(provider),
        "provider_identity_sha256": actual,
    }


def validate_authoritative_provider_pair(
    static_reference_provider_uri: str | Path,
    decomposition_provider_uri: str | Path,
) -> dict[str, dict[str, Any]]:
    """Require the exact provider pair used by the committed endpoint evidence."""

    static_provider = Path(static_reference_provider_uri).resolve()
    pit_provider = Path(decomposition_provider_uri).resolve()
    if static_provider == pit_provider:
        raise ValueError(
            "static reference and decomposition providers must be different"
        )
    return {
        "static_reference": require_provider_identity(
            static_provider,
            expected_identity=STATIC_REFERENCE_PROVIDER_IDENTITY,
            role="static_reference",
        ),
        "decomposition": require_provider_identity(
            pit_provider,
            expected_identity=DECOMPOSITION_PROVIDER_IDENTITY,
            role="decomposition",
        ),
    }
