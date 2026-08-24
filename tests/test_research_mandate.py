"""Governed research mandates must compose and verify by content."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.governance.research_mandate import (
    DEFAULT_MANDATE_PATH,
    ResearchMandateError,
    expected_sha256,
    load_research_mandate,
)


def test_default_cn_mandate_loads_with_verified_bindings() -> None:
    mandate = load_research_mandate()

    assert mandate.mandate_id == "cn_training_mandate_v1"
    assert mandate.market == "cn"
    assert mandate.benchmark_symbol == "000300"
    assert mandate.rebalance_cadence == "biweekly"
    roles = {binding.role: binding for binding in mandate.bindings}
    assert set(roles) == {"candidate_pool", "reference_instruments", "pool_governance"}
    pool = roles["candidate_pool"]
    assert pool.ref.endswith("cn_selected_equities_v3.yaml")
    assert len(pool.sha256) == 64


def test_tampered_binding_fails_closed(tmp_path: Path) -> None:
    document = yaml.safe_load(
        (PROJECT_ROOT / DEFAULT_MANDATE_PATH).read_text(encoding="utf-8")
    )
    document["bindings"]["candidate_pool"]["sha256"] = "0" * 64
    tampered = tmp_path / "mandate.yaml"
    tampered.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ResearchMandateError, match="binding drifted"):
        load_research_mandate(tampered)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("research_only", False),
        ("trade_ready", True),
        ("automatic_promotion", True),
    ],
)
def test_research_boundary_cannot_be_flipped(tmp_path: Path, field: str, value: object) -> None:
    document = yaml.safe_load(
        (PROJECT_ROOT / DEFAULT_MANDATE_PATH).read_text(encoding="utf-8")
    )
    document["evidence_boundaries"][field] = value
    tampered = tmp_path / "mandate.yaml"
    tampered.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ResearchMandateError, match=field):
        load_research_mandate(tampered)


def test_missing_referenced_file_is_reported(tmp_path: Path) -> None:
    document = yaml.safe_load(
        (PROJECT_ROOT / DEFAULT_MANDATE_PATH).read_text(encoding="utf-8")
    )
    document["bindings"]["candidate_pool"]["ref"] = "configs/research_universes/absent.yaml"
    tampered = tmp_path / "mandate.yaml"
    tampered.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ResearchMandateError, match="missing"):
        load_research_mandate(tampered)


def test_expected_sha256_matches_file_bytes() -> None:
    digest = expected_sha256("configs/mandates/cn_research_mandate_v1.yaml")
    import hashlib

    raw = hashlib.sha256(
        (PROJECT_ROOT / "configs/mandates/cn_research_mandate_v1.yaml").read_bytes()
    ).hexdigest()
    assert digest == raw


def test_unsafe_or_absolute_refs_are_rejected(tmp_path: Path) -> None:
    document = yaml.safe_load(
        (PROJECT_ROOT / DEFAULT_MANDATE_PATH).read_text(encoding="utf-8")
    )
    document["bindings"]["candidate_pool"]["ref"] = "../../etc/passwd"
    tampered = tmp_path / "mandate.yaml"
    tampered.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ResearchMandateError, match="unsafe"):
        load_research_mandate(tampered)
