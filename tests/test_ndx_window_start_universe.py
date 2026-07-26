"""Focused contract tests for the NDX window-start universe module."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.ndx_window_start_universe import (
    DEFAULT_SNAPSHOT_PATH,
    NdxSnapshotDate,
    NdxWindowStartSnapshot,
    SOURCE_URL_TEMPLATE,
    compute_membership_hash,
    filter_training_by_asof_membership,
    get_snapshot_by_date,
    intersect_with_provider,
    load_snapshot,
    resolve_latest_snapshot_on_or_before,
    validate_snapshot_hash,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def snapshot() -> NdxWindowStartSnapshot:
    """Load the committed NDX membership snapshot."""
    return load_snapshot(DEFAULT_SNAPSHOT_PATH, validate_hashes=True, validate_source=True)


# ══════════════════════════════════════════════════════════════════════════════
# Snapshot loading
# ══════════════════════════════════════════════════════════════════════════════


def test_loads_valid_snapshot(snapshot: NdxWindowStartSnapshot) -> None:
    """Committed snapshot loads with correct schema identity."""
    assert snapshot.source_url_template == SOURCE_URL_TEMPLATE
    assert len(snapshot.snapshot_dates) == 10
    for entry in snapshot.snapshot_dates:
        assert entry.date
        assert entry.count > 0
        assert len(entry.symbols) == entry.count
        assert entry.sha256_membership_hash


def test_snapshot_dates_are_correct(snapshot: NdxWindowStartSnapshot) -> None:
    """Required snapshot dates span 2021-01-04 through 2025-07-01."""
    expected = {
        "2021-01-04", "2021-07-01",
        "2022-01-03", "2022-07-01",
        "2023-01-03", "2023-07-03",
        "2024-01-02", "2024-07-01",
        "2025-01-02", "2025-07-01",
    }
    actual = {d.date for d in snapshot.snapshot_dates}
    assert actual == expected


def test_committed_snapshots_have_expected_counts_and_hashes(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """Each committed snapshot has the exact expected count and SHA-256 hash.

    2021-01-04 and 2021-07-01 legitimately share the same hash (the index
    membership was identical across both dates), so we assert per-date hashes
    rather than requiring all distinct.
    """
    counts = {entry.date: entry.count for entry in snapshot.snapshot_dates}
    assert counts == {
        "2021-01-04": 102,
        "2021-07-01": 102,
        "2022-01-03": 101,
        "2022-07-01": 102,
        "2023-01-03": 101,
        "2023-07-03": 101,
        "2024-01-02": 101,
        "2024-07-01": 102,
        "2025-01-02": 101,
        "2025-07-01": 101,
    }
    hashes = {
        entry.date: entry.sha256_membership_hash
        for entry in snapshot.snapshot_dates
    }
    assert hashes == {
        "2021-01-04": (
            "dfdb48d07e05b133c4973e6fab386901275603df261210fe101d75590e631899"
        ),
        "2021-07-01": (
            "dfdb48d07e05b133c4973e6fab386901275603df261210fe101d75590e631899"
        ),
        "2022-01-03": (
            "28d33393c66440f8f5ce870a0495d1c8110778f069e42281932e88dd7d1cc321"
        ),
        "2022-07-01": (
            "e71e4763c3976c1c2e7c2c9707d1a5a00096908e65ba4cc5644e643cd5d321e4"
        ),
        "2023-01-03": (
            "a35d2f40ba65a63951673f6fd1b944e43b9198ec870952409cbbca1c32dc5586"
        ),
        "2023-07-03": (
            "5e35ad847bc39b41c21089d12eda48bf55926ef7681c129d04be52db7598c283"
        ),
        "2024-01-02": (
            "1cc0ce082fcce3ac2380835b068606b7f0501e3d5a01fce4d13f34eecad82642"
        ),
        "2024-07-01": (
            "9284a786dbef1f27e050c6602203631a05dc87f6e3e3e9ddf5947b8777d282ab"
        ),
        "2025-01-02": (
            "d725cff131e339127623d2536788b7813b414fda9453d7e3a7e7da62827d162e"
        ),
        "2025-07-01": (
            "785b04f69a405eed1daf7b2c5cdc260ee8808d723de1cc41038d0f1b080495af"
        ),
    }


def test_2021_snapshots_share_hash_legitimately(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """2021-01-04 and 2021-07-01 have the same hash — membership was identical."""
    h1 = get_snapshot_by_date(snapshot, "2021-01-04").sha256_membership_hash
    h2 = get_snapshot_by_date(snapshot, "2021-07-01").sha256_membership_hash
    assert h1 == h2
    # Dates and symbols are distinct entries even though hash matches
    s1 = get_snapshot_by_date(snapshot, "2021-01-04")
    s2 = get_snapshot_by_date(snapshot, "2021-07-01")
    assert s1.date != s2.date
    assert s1.symbols == s2.symbols  # same set, same order


def test_symbols_are_sorted_unique_nonempty(snapshot: NdxWindowStartSnapshot) -> None:
    """Every snapshot date has sorted, unique, non-empty symbols."""
    for entry in snapshot.snapshot_dates:
        assert all(isinstance(s, str) and s.strip() for s in entry.symbols)
        assert entry.symbols == tuple(sorted(entry.symbols))
        assert len(set(entry.symbols)) == entry.count


def test_snapshot_source_url_matches_expected(snapshot: NdxWindowStartSnapshot) -> None:
    """Source URL template matches the official Nasdaq endpoint."""
    assert "NasdaqOMX" in snapshot.source_url_template or "ndx" in snapshot.source_url_template.lower()
    assert "{date}" in snapshot.source_url_template


# ══════════════════════════════════════════════════════════════════════════════
# Hash validation
# ══════════════════════════════════════════════════════════════════════════════


def test_all_hashes_are_valid(snapshot: NdxWindowStartSnapshot) -> None:
    """Every snapshot date has a valid SHA-256 hash."""
    for entry in snapshot.snapshot_dates:
        assert validate_snapshot_hash(entry) is True


def test_hash_is_deterministic() -> None:
    """Same symbols produce same hash every time."""
    symbols = ["AAPL", "MSFT", "GOOGL"]
    h1 = compute_membership_hash(symbols)
    h2 = compute_membership_hash(symbols)
    h3 = compute_membership_hash(list(reversed(symbols)))
    assert h1 == h2
    assert h1 == h3  # order-independent


def test_hash_format() -> None:
    """Hash is a 64-char lowercase hex string."""
    h = compute_membership_hash(["AAPL", "MSFT"])
    assert len(h) == 64
    int(h, 16)  # should not raise


def test_hash_mismatch_raises() -> None:
    """Hash mismatch raises ValueError."""
    entry = NdxSnapshotDate(
        date="2024-01-02",
        symbols=("AAPL", "MSFT"),
        count=2,
        sha256_membership_hash="0000" + "0" * 60,  # wrong
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_snapshot_hash(entry)


# ══════════════════════════════════════════════════════════════════════════════
# get_snapshot_by_date
# ══════════════════════════════════════════════════════════════════════════════


def test_get_snapshot_by_date_found(snapshot: NdxWindowStartSnapshot) -> None:
    """Lookup by date returns the correct entry."""
    entry = get_snapshot_by_date(snapshot, "2024-01-02")
    assert entry.date == "2024-01-02"
    assert entry.count > 90  # NDX-100 should have ~100 symbols


def test_get_snapshot_by_date_missing_raises(snapshot: NdxWindowStartSnapshot) -> None:
    """Missing date raises KeyError."""
    with pytest.raises(KeyError, match="not found"):
        get_snapshot_by_date(snapshot, "2023-01-01")


# ══════════════════════════════════════════════════════════════════════════════
# Provider intersection
# ══════════════════════════════════════════════════════════════════════════════


def test_intersect_complete() -> None:
    """When all symbols are in provider, intersection is complete."""
    date_entry = NdxSnapshotDate(
        date="2024-01-02",
        symbols=("AAPL", "MSFT", "GOOGL"),
        count=3,
        sha256_membership_hash=compute_membership_hash(["AAPL", "MSFT", "GOOGL"]),
    )
    provider = {"AAPL", "MSFT", "GOOGL", "NVDA"}
    result = intersect_with_provider(date_entry, provider)
    assert result["complete"] is True
    assert result["coverage_ratio"] == 1.0
    assert result["n_retained"] == 3
    assert result["n_missing"] == 0


def test_intersect_partial() -> None:
    """Missing symbols produce incomplete coverage."""
    date_entry = NdxSnapshotDate(
        date="2024-01-02",
        symbols=("AAPL", "MISSING1", "MISSING2"),
        count=3,
        sha256_membership_hash=compute_membership_hash(["AAPL", "MISSING1", "MISSING2"]),
    )
    provider = {"AAPL", "MSFT"}
    result = intersect_with_provider(date_entry, provider)
    assert result["complete"] is False
    assert result["coverage_ratio"] == pytest.approx(1 / 3, abs=0.01)
    assert result["n_retained"] == 1
    assert result["n_missing"] == 2
    assert "MISSING1" in result["missing"]
    assert "MISSING2" in result["missing"]


def test_intersect_fail_closed_empty_provider() -> None:
    """Empty provider set produces zero coverage."""
    date_entry = NdxSnapshotDate(
        date="2024-01-02",
        symbols=("AAPL", "MSFT"),
        count=2,
        sha256_membership_hash=compute_membership_hash(["AAPL", "MSFT"]),
    )
    result = intersect_with_provider(date_entry, set())
    assert result["complete"] is False
    assert result["coverage_ratio"] == 0.0
    assert result["n_retained"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Load validation
# ══════════════════════════════════════════════════════════════════════════════


def test_load_missing_file_raises(tmp_path: Path) -> None:
    """Loading a non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_snapshot(tmp_path / "nonexistent.json")


def test_load_triggers_hash_validation(snapshot: NdxWindowStartSnapshot) -> None:
    """Default load validates all hashes."""
    for entry in snapshot.snapshot_dates:
        validate_snapshot_hash(entry)  # no error


def test_load_skip_validation(tmp_path: Path) -> None:
    """When validate_hashes=False, hash errors are not raised at load time."""
    # Create a snapshot with wrong hash
    data = {
        "schema_version": "1.0",
        "index": "NDX",
        "source_url_template": SOURCE_URL_TEMPLATE,
        "snapshot_dates": [
            {
                "date": "2024-01-02",
                "symbols": ["AAPL", "MSFT"],
                "count": 2,
                "sha256_membership_hash": "bad" + "0" * 61,
            }
        ],
    }
    p = tmp_path / "bad_snapshot.json"
    p.write_text(json.dumps(data), encoding="utf-8")

    # Should load without hash validation error
    snap = load_snapshot(p, validate_hashes=False, validate_source=True)
    assert len(snap.snapshot_dates) == 1


def test_source_validation_rejects_wrong_url(tmp_path: Path) -> None:
    """Wrong source URL template raises ValueError when validate_source=True."""
    data = {
        "schema_version": "1.0",
        "index": "NDX",
        "source_url_template": "https://example.com/wrong",
        "snapshot_dates": [
            {
                "date": "2024-01-02",
                "symbols": ["AAPL"],
                "count": 1,
                "sha256_membership_hash": compute_membership_hash(["AAPL"]),
            }
        ],
    }
    p = tmp_path / "wrong_source.json"
    p.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="source URL template mismatch"):
        load_snapshot(p, validate_hashes=True, validate_source=True)


# ══════════════════════════════════════════════════════════════════════════════
# Round-trip
# ══════════════════════════════════════════════════════════════════════════════


def test_to_dict_round_trip(snapshot: NdxWindowStartSnapshot) -> None:
    """to_dict produces a JSON-serializable dict with all fields."""
    d = snapshot.to_dict()
    assert d["source_url_template"] == SOURCE_URL_TEMPLATE
    assert len(d["snapshot_dates"]) == 10
    for entry in d["snapshot_dates"]:
        assert "date" in entry
        assert "symbols" in entry
        assert "count" in entry
        assert "sha256_membership_hash" in entry


# ══════════════════════════════════════════════════════════════════════════════
# resolve_latest_snapshot_on_or_before
# ══════════════════════════════════════════════════════════════════════════════


def test_resolve_latest_on_or_before_finds_match(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """Resolves the latest snapshot on or before a given date."""
    result = resolve_latest_snapshot_on_or_before(snapshot, "2023-06-15")
    # Latest ≤ 2023-06-15 should be 2023-01-03
    assert result.date == "2023-01-03"


def test_resolve_latest_returns_exact_match(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """When date exactly matches a snapshot, that snapshot is returned."""
    result = resolve_latest_snapshot_on_or_before(snapshot, "2022-07-01")
    assert result.date == "2022-07-01"


def test_resolve_before_earliest_snapshot_raises(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """Requesting a date before the earliest snapshot raises (fail-closed)."""
    with pytest.raises(ValueError, match="No NDX snapshot on or before"):
        resolve_latest_snapshot_on_or_before(snapshot, "2020-12-31")


def test_resolve_never_uses_future_snapshot(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """A date between snapshots resolves to the prior snapshot, never a future one."""
    # 2023-05-15 is between 2023-01-03 and 2023-07-03
    result = resolve_latest_snapshot_on_or_before(snapshot, "2023-05-15")
    assert result.date == "2023-01-03"
    # 2023-01-03 < 2023-07-03, proving we didn't use the future snapshot
    assert pd.Timestamp(result.date) < pd.Timestamp("2023-07-03")


# ══════════════════════════════════════════════════════════════════════════════
# filter_training_by_asof_membership
# ══════════════════════════════════════════════════════════════════════════════


def test_asof_filter_retains_members_at_snapshot_date(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """Rows at a snapshot date retain only instruments in that snapshot."""
    symbols_in_2021 = get_snapshot_by_date(snapshot, "2021-01-04").symbols
    provider = set(symbols_in_2021)
    # Build a frame with one date and mixed instruments
    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2021-03-15"), "AAPL"),
            (pd.Timestamp("2021-03-15"), "MSFT"),
            (pd.Timestamp("2021-03-15"), "ZZZZ_NOT_MEMBER"),
        ],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"value": [1.0, 2.0, 3.0]}, index=idx)
    filtered = filter_training_by_asof_membership(frame, snapshot, provider)
    assert "ZZZZ_NOT_MEMBER" not in filtered.index.get_level_values("instrument")
    assert "AAPL" in filtered.index.get_level_values("instrument")
    assert "MSFT" in filtered.index.get_level_values("instrument")


def test_asof_filter_drops_before_earliest_snapshot(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """Dates before the earliest snapshot have all rows dropped."""
    provider = set(get_snapshot_by_date(snapshot, "2021-01-04").symbols)
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2020-12-15"), "AAPL")],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"value": [1.0]}, index=idx)
    filtered = filter_training_by_asof_membership(frame, snapshot, provider)
    assert filtered.empty


def test_asof_filter_never_uses_future_snapshot(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """At date 2023-05-15, membership should be from 2023-01-03, not 2023-07-03."""
    snap_202301 = get_snapshot_by_date(snapshot, "2023-01-03")
    snap_202307 = get_snapshot_by_date(snapshot, "2023-07-03")
    # Find a symbol that is in 2023-07-03 but NOT in 2023-01-03
    sym_202301 = set(snap_202301.symbols)
    sym_202307 = set(snap_202307.symbols)
    new_in_jul = sym_202307 - sym_202301
    if not new_in_jul:
        pytest.skip("No symbol differs between 2023H1 and 2023H2 snapshots")
    new_sym = sorted(new_in_jul)[0]
    provider = sym_202301 | sym_202307

    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2023-05-15"), new_sym)],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"value": [1.0]}, index=idx)
    filtered = filter_training_by_asof_membership(frame, snapshot, provider)
    # The symbol joined in 2023H2 — at 2023-05-15 it was NOT yet a member
    assert filtered.empty, (
        f"{new_sym} was in 2023H2 but not 2023H1; it should be filtered at "
        f"2023-05-15 (as-of snapshot is 2023-01-03, not the future 2023-07-03)"
    )


def test_asof_filter_provider_excludes_unknown_symbols(
    snapshot: NdxWindowStartSnapshot,
) -> None:
    """Symbols not in provider are excluded even if in snapshot."""
    # Use a restricted provider that only has AAPL
    tiny_provider = {"AAPL"}

    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2021-03-15"), "AAPL"),
            (pd.Timestamp("2021-03-15"), "MSFT"),  # in snapshot but not provider
        ],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"value": [1.0, 2.0]}, index=idx)
    filtered = filter_training_by_asof_membership(frame, snapshot, tiny_provider)
    instruments = set(filtered.index.get_level_values("instrument"))
    assert instruments == {"AAPL"}


# ══════════════════════════════════════════════════════════════════════════════
# Refresh script: fetch_ndx_symbols parser contract
# ══════════════════════════════════════════════════════════════════════════════


class TestFetchNdxSymbols:
    """Mock-based contract tests for fetch_ndx_symbols."""

    def test_parses_aaData_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parser extracts Symbol field from aaData rows."""
        import scripts.refresh_ndx_window_start_membership as refresh_mod

        mock_response = {
            "aaData": [
                {"Symbol": "AAPL", "Name": "Apple Inc.", "Weight": 0.08},
                {"Symbol": "MSFT", "Name": "Microsoft", "Weight": 0.07},
                {"Symbol": "GOOGL", "Name": "Alphabet", "Weight": 0.05},
            ]
        }

        def _mock_post(url, **_kw):
            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return mock_response

            return _Resp()

        monkeypatch.setattr(refresh_mod.requests, "post", _mock_post)
        symbols = refresh_mod.fetch_ndx_symbols("2024-01-02")
        assert symbols == ["AAPL", "GOOGL", "MSFT"]

    def test_skips_rows_without_symbol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rows missing the Symbol key are silently skipped."""
        import scripts.refresh_ndx_window_start_membership as refresh_mod

        mock_response = {
            "aaData": [
                {"Symbol": "AAPL"},
                {"Ticker": "MSFT"},  # wrong key, should be skipped
                {"Symbol": ""},       # empty string, should be skipped
                {"Symbol": None},     # None, should be skipped
                {},                   # no keys at all
            ]
        }

        def _mock_post(url, **_kw):
            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return mock_response

            return _Resp()

        monkeypatch.setattr(refresh_mod.requests, "post", _mock_post)
        symbols = refresh_mod.fetch_ndx_symbols("2024-01-02")
        assert symbols == ["AAPL"]

    def test_raises_on_non_dict_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Response that is not a dict with aaData raises ValueError."""
        import scripts.refresh_ndx_window_start_membership as refresh_mod

        def _mock_post(url, **_kw):
            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return [{"Symbol": "AAPL"}]  # list, not dict

            return _Resp()

        monkeypatch.setattr(refresh_mod.requests, "post", _mock_post)
        with pytest.raises(ValueError, match="aaData"):
            refresh_mod.fetch_ndx_symbols("2024-01-02")

    def test_raises_on_empty_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty aaData or no valid symbols raises ValueError."""
        import scripts.refresh_ndx_window_start_membership as refresh_mod

        def _mock_post(url, **_kw):
            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"aaData": []}

            return _Resp()

        monkeypatch.setattr(refresh_mod.requests, "post", _mock_post)
        with pytest.raises(ValueError, match="no tickers"):
            refresh_mod.fetch_ndx_symbols("2024-01-02")


def test_refresh_defaults_cover_full_training_and_oos_history() -> None:
    """A default refresh cannot silently discard the six training snapshots."""
    import scripts.refresh_ndx_window_start_membership as refresh_mod

    args = refresh_mod.build_parser().parse_args([])
    assert args.dates == refresh_mod.DEFAULT_SNAPSHOT_DATES
    assert len(args.dates) == 10
    assert args.dates[0] == "2021-01-04"
    assert args.dates[-1] == "2025-07-01"
