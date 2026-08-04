"""Material quality interpretation for the 515180 canonical bundle."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.data.byd_canonical_bundle import (
    CanonicalBundle,
    audit_adjustment_events,
)
from src.data.etf_515180_canonical import ETFCanonicalQuality

MATERIAL_FACTOR_JUMP_TOLERANCE = 1e-6


def _manifest_sha(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def apply_material_factor_quality(
    bundle: CanonicalBundle,
    quality: ETFCanonicalQuality,
) -> tuple[CanonicalBundle, ETFCanonicalQuality]:
    """Ignore provider floating jitter while retaining all economic jumps.

    The same-provider adjusted/raw ratio varies by roughly 1e-7 on otherwise
    constant-factor sessions. Economic dividend transitions in this history
    are above 3%. A fixed 1e-6 threshold cleanly separates numerical jitter
    from material action-linked transitions and matches the prior BYD audit.
    """

    event_audit = audit_adjustment_events(
        bundle.adjustment_factors,
        bundle.corporate_actions,
        jump_tolerance=MATERIAL_FACTOR_JUMP_TOLERANCE,
    )
    material_jumps = int(event_audit["factor_jump"].sum())
    unexplained = int(event_audit["unexplained_jump"].sum())

    manifest = dict(bundle.manifest)
    gates = dict(quality.gates)
    gates["no_unexplained_factor_jumps"] = unexplained == 0
    passed = all(gates.values())
    manifest.update(
        {
            "factor_jump_tolerance": MATERIAL_FACTOR_JUMP_TOLERANCE,
            "material_factor_jumps": material_jumps,
            "unexplained_factor_jumps": unexplained,
            "quality_gates": gates,
            "data_quality_status": (
                "canonical_v1_pass" if passed else "canonical_v1_blocked"
            ),
        }
    )
    manifest["manifest_sha256"] = _manifest_sha(manifest)
    governed = CanonicalBundle(
        raw_bars=bundle.raw_bars,
        adjustment_factors=bundle.adjustment_factors,
        adjusted_bars=bundle.adjusted_bars,
        corporate_actions=bundle.corporate_actions,
        session_audit=bundle.session_audit,
        provider_comparison=bundle.provider_comparison,
        manifest=manifest,
    )
    return governed, ETFCanonicalQuality(passed=passed, gates=gates)
