from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from src.data.canonical_vwap import (
    CanonicalVwapError,
    derive_adjusted_vwap,
    write_source_role_manifest,
)
from scripts.data.build_canonical_vwap_provider import _cached_cn_pair, _us_feed
from scripts.data import build_canonical_vwap_provider as builder


def test_us_feed_policy_keeps_otc_adrs_explicit() -> None:
    policy = {
        "feed": "sip",
        "symbol_feed_overrides": {"ABBNY": "otc", "SBGSY": "otc"},
    }

    assert _us_feed("AAPL", policy) == "sip"
    assert _us_feed("ABBNY", policy) == "otc"
    assert _us_feed("sbGsy", policy) == "otc"


def _pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-02", periods=3)
    raw = pd.DataFrame(
        {
            "date": dates,
            "open": [9.8, 10.8, 11.8],
            "high": [10.5, 11.5, 12.5],
            "low": [9.5, 10.5, 11.5],
            "close": [10.0, 11.0, 12.0],
            "volume": [100.0, 200.0, 400.0],
            "amount": [1010.0, 2220.0, 4800.0],
        }
    )
    adjusted = raw.drop(columns="amount").copy()
    for column in ("open", "high", "low", "close"):
        adjusted[column] = adjusted[column] * 0.5
    return raw, adjusted


def test_reported_turnover_is_moved_to_adjusted_price_basis() -> None:
    raw, adjusted = _pair()
    result, evidence = derive_adjusted_vwap(
        raw,
        adjusted,
        symbol="000001",
        amount_is_reported=True,
        volume_unit="shares",
        amount_unit="CNY",
    )
    assert result["vwap"].tolist() == pytest.approx([5.05, 5.55, 6.0])
    assert result["factor"].tolist() == pytest.approx([0.5, 0.5, 0.5])
    assert evidence["vwap_semantics"] == (
        "reported_turnover_divided_by_reported_volume"
    )
    assert evidence["envelope_violations"] == 0


def test_synthetic_amount_is_rejected() -> None:
    raw, adjusted = _pair()
    with pytest.raises(CanonicalVwapError, match="synthetic"):
        derive_adjusted_vwap(
            raw,
            adjusted,
            symbol="000001",
            amount_is_reported=False,
            volume_unit="shares",
            amount_unit="CNY",
        )


def test_raw_and_adjusted_volume_must_match_exactly() -> None:
    raw, adjusted = _pair()
    adjusted.loc[1, "volume"] = 201.0
    with pytest.raises(CanonicalVwapError, match="volume differ"):
        derive_adjusted_vwap(
            raw,
            adjusted,
            symbol="000001",
            amount_is_reported=True,
            volume_unit="shares",
            amount_unit="CNY",
        )


def test_raw_and_adjusted_calendars_must_match() -> None:
    raw, adjusted = _pair()
    adjusted = adjusted.iloc[:-1].copy()
    with pytest.raises(CanonicalVwapError, match="calendars must match"):
        derive_adjusted_vwap(
            raw,
            adjusted,
            symbol="000001",
            amount_is_reported=True,
            volume_unit="shares",
            amount_unit="CNY",
        )


def test_half_tick_rounding_is_recorded_but_larger_violation_is_rejected() -> None:
    raw, adjusted = _pair()
    raw.loc[0, "amount"] = 949.6
    result, evidence = derive_adjusted_vwap(
        raw,
        adjusted,
        symbol="000001",
        amount_is_reported=True,
        volume_unit="shares",
        amount_unit="CNY",
    )
    assert result.loc[0, "vwap"] == pytest.approx(4.748)
    assert evidence["rounded_envelope_tolerance_sessions"] == 1
    assert evidence["max_envelope_rounding_distance"] == pytest.approx(0.002)
    assert evidence["maximum_rounding_tolerance"] == pytest.approx(0.005)

    raw.loc[0, "amount"] = 948.0
    with pytest.raises(CanonicalVwapError, match="half_tick"):
        derive_adjusted_vwap(
            raw,
            adjusted,
            symbol="000001",
            amount_is_reported=True,
            volume_unit="shares",
            amount_unit="CNY",
        )


@pytest.mark.parametrize("session_gaps", [False, True])
def test_source_pair_cache_requires_exact_cutoff_identity(tmp_path: Path, session_gaps: bool) -> None:
    raw, adjusted = _pair()
    raw_path = tmp_path / "raw.csv"
    qfq_path = tmp_path / "qfq.csv"
    metadata_path = tmp_path / "metadata.json"
    raw.to_csv(raw_path, index=False)
    adjusted.to_csv(qfq_path, index=False)
    start = raw["date"].min().date().isoformat()
    cutoff = raw["date"].max().date().isoformat()
    if session_gaps:
        start = (pd.Timestamp(start) - pd.Timedelta(days=3)).date().isoformat()
        cutoff = (pd.Timestamp(cutoff) + pd.Timedelta(days=2)).date().isoformat()
    metadata_path.write_text(
        json.dumps(
            {
                "symbol": "000001",
                "start": start,
                "cutoff": cutoff,
                "source_provider": "akshare_sina",
                "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                "qfq_sha256": hashlib.sha256(qfq_path.read_bytes()).hexdigest(),
                "research_only": True,
                "trade_ready": False,
                "semantic_validation": "passed",
            }
        ),
        encoding="utf-8",
    )

    assert _cached_cn_pair(
        symbol="000001",
        start=start,
        end=cutoff,
        raw_path=raw_path,
        qfq_path=qfq_path,
        metadata_path=metadata_path,
    ) is not None
    assert _cached_cn_pair(
        symbol="000001",
        start=start,
        end="2026-01-31",
        raw_path=raw_path,
        qfq_path=qfq_path,
        metadata_path=metadata_path,
    ) is None

    for path in (raw_path, qfq_path):
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        assert _cached_cn_pair(
            symbol="000001", start=start, end=cutoff,
            raw_path=raw_path, qfq_path=qfq_path, metadata_path=metadata_path,
        ) is None
        path.write_bytes(original)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    del metadata["raw_sha256"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    assert _cached_cn_pair(
        symbol="000001", start=start, end=cutoff,
        raw_path=raw_path, qfq_path=qfq_path, metadata_path=metadata_path,
    ) is None


def test_source_role_manifest_binds_provider_identity(tmp_path: Path) -> None:
    provider = tmp_path / "provider"
    provider.mkdir()
    provider_manifest_path = provider / "provider_manifest.json"
    provider_manifest_path.write_text(
        json.dumps({"provider_identity_sha256": "a" * 64}) + "\n",
        encoding="utf-8",
    )
    payload = write_source_role_manifest(
        provider,
        provider_manifest={"provider_identity_sha256": "a" * 64},
        provider_manifest_path=provider_manifest_path,
        source_providers=["akshare_sina"],
        market="cn",
        vwap_ready=True,
    )
    assert payload["role"] == "canonical"
    assert payload["canonical_training_eligible"] is True
    assert payload["provider_identity_sha256"] == "a" * 64
    assert len(payload["provider_manifest_sha256"]) == 64
    assert payload["field_semantics"]["vwap"] == (
        "reported_turnover_divided_by_reported_volume"
    )


def test_cn_build_reuses_verified_request_without_fetch_or_rewriting_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, qfq = _pair()
    originals = {}
    for folder, frame in (("raw", raw), ("qfq", qfq)):
        path = tmp_path / folder / "000001.csv"
        path.parent.mkdir()
        path.write_text(frame.to_csv(index=False) + "\n", encoding="utf-8")
        originals[path] = path.read_bytes()
    metadata = tmp_path / "cache_metadata" / "000001.json"
    metadata.parent.mkdir()
    metadata.write_text(json.dumps({
        "symbol": "000001", "start": "2026-01-01", "cutoff": "2026-01-10",
        "source_provider": "akshare_sina", "research_only": True, "trade_ready": False,
        "semantic_validation": "passed",
        "raw_sha256": hashlib.sha256(originals[tmp_path / "raw" / "000001.csv"]).hexdigest(),
        "qfq_sha256": hashlib.sha256(originals[tmp_path / "qfq" / "000001.csv"]).hexdigest(),
    }), encoding="utf-8")
    originals[metadata] = metadata.read_bytes()
    monkeypatch.setattr(builder, "_pool_symbols", lambda *args: ("fixture-cn", ["000001"]))

    def unexpected_fetch(*args: object, **kwargs: object) -> None:
        pytest.fail("Exact verified source request must not fetch again")

    def stop_before_materialization(*args: object, **kwargs: object) -> None:
        raise CanonicalVwapError("source acceptance completed")

    monkeypatch.setattr(builder, "_fetch_cn_pair", unexpected_fetch)
    monkeypatch.setattr(builder, "build_market_provider", stop_before_materialization)
    with pytest.raises(CanonicalVwapError, match="source acceptance completed"):
        builder.build_cn(pool_path=tmp_path / "unused.yaml", start="2026-01-01",
                         cutoff="2026-01-10", output_root=tmp_path, fixture_dir=None)
    assert all(path.read_bytes() == data for path, data in originals.items())
    audit = json.loads((tmp_path / "vwap_audit.json").read_text(encoding="utf-8"))
    assert audit["failed_symbol_count"] == 0
    assert audit["symbols"][0]["cache_mode"] == "exact_cutoff_reuse"


def test_cn_failed_semantic_source_is_retained_but_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, qfq = _pair()
    bad = raw.copy()
    bad.loc[0, "amount"] = 5000.0
    fetches: list[int] = []
    monkeypatch.setattr(builder, "_pool_symbols", lambda *args: ("fixture-cn", ["000001"]))

    def fetch(*args: object, **kwargs: object) -> tuple[pd.DataFrame, pd.DataFrame]:
        fetches.append(1)
        return (bad if len(fetches) == 1 else raw).copy(), qfq.copy()

    def stop(*args: object, **kwargs: object) -> None:
        raise CanonicalVwapError("source acceptance completed")

    monkeypatch.setattr(builder, "_fetch_cn_pair", fetch)
    monkeypatch.setattr(builder, "build_market_provider", stop)
    arguments = dict(pool_path=tmp_path / "unused.yaml", start="2026-01-01",
                     cutoff="2026-01-10", output_root=tmp_path, fixture_dir=None)
    with pytest.raises(CanonicalVwapError, match="incomplete"):
        builder.build_cn(**arguments)
    metadata_path = tmp_path / "cache_metadata" / "000001.json"
    assert json.loads(metadata_path.read_text())["semantic_validation"] == "pending"
    assert pd.read_csv(tmp_path / "raw" / "000001.csv")["amount"].iloc[0] == 5000.0
    failure = json.loads((tmp_path / "vwap_audit.json").read_text())
    assert failure["failed_symbol_count"] == 1

    for _ in range(2):
        with pytest.raises(CanonicalVwapError, match="source acceptance completed"):
            builder.build_cn(**arguments)
    assert len(fetches) == 2
    assert json.loads(metadata_path.read_text())["semantic_validation"] == "passed"
    assert json.loads((tmp_path / "vwap_audit.json").read_text())["symbols"][0]["cache_mode"] == "exact_cutoff_reuse"
