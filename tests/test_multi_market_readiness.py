from __future__ import annotations

import json

import pytest

from src.research.multi_market_readiness import (
    MarketReadinessSpec,
    check_market_data_coverage,
    cn_symbol_candidates,
    default_market_specs,
    load_market_watchlist,
    normalize_market_symbol,
    normalize_market_symbols,
    render_readiness_markdown,
    summarize_multi_market_readiness,
)


def _coverage(symbols: list[str], *, sufficient: bool = True) -> dict[str, dict[str, object]]:
    return {
        symbol: {
            "first_valid_date": "2021-01-04" if sufficient else None,
            "last_valid_date": "2026-06-18" if sufficient else None,
            "observations": 1200 if sufficient else 0,
            "covers_train_start": sufficient,
            "covers_test_end": sufficient,
            "sufficient_coverage": sufficient,
        }
        for symbol in symbols
    }


def test_cn_symbol_candidates_preserve_leading_zeroes_from_int_like_inputs() -> None:
    assert cn_symbol_candidates(1)[0] == "000001"
    assert cn_symbol_candidates(69)[0] == "000069"
    assert cn_symbol_candidates(2493)[0] == "002493"
    assert cn_symbol_candidates("300750")[0] == "300750"


def test_cn_symbol_candidates_include_explicit_exchange_formats() -> None:
    assert cn_symbol_candidates("000001") == ("000001", "000001.SZ", "SZ000001", "sz.000001")
    assert cn_symbol_candidates("600000") == ("600000", "600000.SH", "SH600000", "sh.600000")


def test_normalize_cn_symbol_selects_available_real_format() -> None:
    normalized = normalize_market_symbol("cn", "000001", available_symbols={"000001.SZ"})

    assert normalized.original_symbol == "000001"
    assert normalized.normalized_symbol == "000001.SZ"
    assert "000001" in normalized.candidates
    assert "000001.SZ" in normalized.candidates


def test_normalize_market_symbols_dedupes_after_format_selection() -> None:
    rows = normalize_market_symbols("cn", ["000001", "000001.SZ", 1], available_symbols={"000001.SZ"})

    assert [row.normalized_symbol for row in rows] == ["000001.SZ"]


def test_load_market_watchlist_preserves_cn_codes_from_yaml(tmp_path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "cn:\n"
        "  - '000001'\n"
        "  - 000069\n"
        "  - 002493\n"
        "  - 300750\n",
        encoding="utf-8",
    )

    raw = load_market_watchlist("cn", watchlist_path=path)
    normalized = [row.normalized_symbol for row in normalize_market_symbols("cn", raw)]

    assert "000001" in normalized
    assert "000069" in normalized
    assert "002493" in normalized
    assert "300750" in normalized


def test_default_market_specs_include_us_and_cn_when_watchlist_has_both(tmp_path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "us:\n  - AAPL\n  - MSFT\n  - NVDA\n"
        "cn:\n  - '000001'\n  - 000069\n  - 002493\n  - 300750\n  - 600000\n  - 000300\n"
        "  - 000333\n  - 002594\n  - 300750\n  - 000651\n"
        "  - 000858\n  - 002415\n  - 002230\n  - 300059\n  - 002475\n"
        "  - 002460\n  - 300124\n  - 000725\n  - 000776\n  - 002027\n",
        encoding="utf-8",
    )

    specs = default_market_specs(watchlist_path=path)

    assert {spec.market for spec in specs} == {"us", "cn"}
    cn = next(spec for spec in specs if spec.market == "cn")
    assert "000001" in cn.symbols
    assert "002493" in cn.symbols
    assert cn.benchmark == "000300"


def test_check_market_data_coverage_passes_when_enough_symbols_are_covered() -> None:
    symbols = ("000001", "000002", "000300")
    spec = MarketReadinessSpec(
        market="cn",
        symbols=symbols,
        benchmark="000300",
        train_start="2021-01-01",
        test_end="2026-06-18",
        min_symbols=2,
    )

    report = check_market_data_coverage(spec, date_coverage_data=_coverage(list(symbols)))

    assert report["market"] == "cn"
    assert report["sufficient"] is True
    assert report["skipped"] is False
    assert len(report["retained_symbols"]) == 3
    assert report["normalization"][0]["original_symbol"] == "000001"


def test_check_market_data_coverage_fails_closed_when_coverage_is_insufficient() -> None:
    symbols = ("000001", "000002", "000300")
    spec = MarketReadinessSpec(
        market="cn",
        symbols=symbols,
        benchmark="000300",
        train_start="2021-01-01",
        test_end="2026-06-18",
        min_symbols=2,
    )

    report = check_market_data_coverage(spec, date_coverage_data=_coverage(list(symbols), sufficient=False))

    assert report["sufficient"] is False
    assert report["skipped"] is True
    assert report["retained_symbols"] == []
    assert report["skip_reason"]


def test_summarize_multi_market_readiness_keeps_us_and_cn_status_separate() -> None:
    reports = {
        "us": {"requested_symbols": ["A", "B"], "retained_symbols": [], "coverage_ratio": 0.0, "sufficient": False, "skipped": True, "skip_reason": "us missing coverage"},
        "cn": {"requested_symbols": ["000001", "000002"], "retained_symbols": ["000001", "000002"], "coverage_ratio": 1.0, "sufficient": True, "skipped": False, "skip_reason": None},
    }

    summary = summarize_multi_market_readiness(reports)

    assert summary["ready_markets"] == ["cn"]
    assert summary["skipped_markets"] == ["us"]
    assert summary["n_markets"] == 2


def test_render_readiness_markdown_mentions_fail_closed_and_cn() -> None:
    reports = {
        "cn": {
            "benchmark": "000300",
            "train_start": "2021-01-01",
            "test_end": "2026-06-18",
            "requested_symbols": ["000001", "000002"],
            "retained_symbols": [],
            "coverage_ratio": 0.0,
            "sufficient": False,
            "skipped": True,
            "skip_reason": "cn skipped because Qlib provider is unavailable",
        }
    }
    summary = summarize_multi_market_readiness(reports)

    text = render_readiness_markdown(reports, summary)

    assert "AlphaEngine Multi-Market Data Readiness" in text
    assert "Coverage is fail-closed" in text
    assert "CN symbols" in text
    assert "cn skipped" in text


def test_market_readiness_spec_rejects_min_symbols_larger_than_universe() -> None:
    with pytest.raises(ValueError, match="min_symbols"):
        MarketReadinessSpec(
            market="cn",
            symbols=("000001", "000002"),
            benchmark="000300",
            train_start="2021-01-01",
            test_end="2026-06-18",
            min_symbols=3,
        )


def test_readiness_report_json_roundtrip_keeps_normalization() -> None:
    symbols = ("000001", "000002", "000300")
    spec = MarketReadinessSpec(
        market="cn",
        symbols=symbols,
        benchmark="000300",
        train_start="2021-01-01",
        test_end="2026-06-18",
        min_symbols=2,
    )

    report = check_market_data_coverage(spec, date_coverage_data=_coverage(list(symbols)))
    payload = json.loads(json.dumps(report))

    assert payload["normalization"][0]["normalized_symbol"] == "000001"
    assert payload["market"] == "cn"
