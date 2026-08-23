from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.data.selected_pool_price_publication import (
    SelectedPoolPricePublicationError,
    build_selected_pool_price_publication_manifest,
    load_selected_pool_price_publication_manifest,
    verify_selected_pool_price_publication_manifest,
    write_selected_pool_price_publication_manifest,
)


def _source(market: str = "cn") -> dict[str, object]:
    path = Path(
        f"data/research/model_data_bundle_v1/components/{market}-selected-pool-prices.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_transient_attempt_error_does_not_change_publication_identity() -> None:
    source = _source()
    changed = copy.deepcopy(source)
    attempts = changed["records"][-1]["attempts"]
    attempts[0]["error"] = "a different transient transport failure"

    first = build_selected_pool_price_publication_manifest(source)
    second = build_selected_pool_price_publication_manifest(changed)

    assert first == second
    assert "error" not in first["records"][-1]["attempt_outcomes"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    (("output_sha256", "0" * 64), ("provider", "different_provider")),
)
def test_governed_record_change_changes_publication_identity(
    field: str, value: str
) -> None:
    source = _source()
    changed = copy.deepcopy(source)
    changed["records"][0][field] = value

    first = build_selected_pool_price_publication_manifest(source)
    second = build_selected_pool_price_publication_manifest(changed)

    assert first["publication_identity_sha256"] != second["publication_identity_sha256"]


def test_unknown_source_field_fails_closed() -> None:
    source = _source()
    source["new_unclassified_field"] = True

    with pytest.raises(SelectedPoolPricePublicationError, match="unsupported source"):
        build_selected_pool_price_publication_manifest(source)


def test_publication_manifest_is_smaller_self_verified_evidence(tmp_path: Path) -> None:
    for market in ("us", "cn"):
        source = _source(market)
        target = tmp_path / market / "publication.json"
        projected = write_selected_pool_price_publication_manifest(target, source)

        assert load_selected_pool_price_publication_manifest(target) == projected
        assert verify_selected_pool_price_publication_manifest(target, source) == projected
        assert target.stat().st_size < len(json.dumps(source).encode("utf-8")) // 2

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["records"][0]["output_sha256"] = "0" * 64
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SelectedPoolPricePublicationError, match="identity mismatch"):
        load_selected_pool_price_publication_manifest(target)
