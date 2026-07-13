"""Apply the Issue #147 canonical factor identity patch.

Deleted before merge.
"""

from __future__ import annotations

from pathlib import Path

DIAGNOSTICS = Path("src/research/spec_bound_factor_diagnostics.py")
PIPELINE = Path("src/research/real_market_research_pipeline.py")
TESTS = Path("tests/test_spec_bound_factor_diagnostics.py")
PIPELINE_TESTS = Path("tests/test_real_market_research_pipeline.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_diagnostics() -> None:
    text = DIAGNOSTICS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.1"',
        'FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.2"',
        "diagnostic schema",
    )
    import_anchor = "from src.research.factor_library import FactorSpec, load_factor_library\n"
    import_block = import_anchor + """from src.research.factor_identity import (
    build_canonical_factor_row,
    expand_alias_rows,
    factor_identity_metadata,
    group_factor_specs_by_expression,
    validate_alias_metric_consistency,
)
"""
    if "from src.research.factor_identity import" not in text:
        text = replace_once(text, import_anchor, import_block, "factor identity import")

    text = replace_once(
        text,
        """    factor_specs = _selected_factor_specs(spec)
    expressions = list(dict.fromkeys(factor.expression for _, factor in factor_specs))
""",
        """    factor_specs = _selected_factor_specs(spec)
    canonical_specs = group_factor_specs_by_expression(factor_specs)
    expressions = [item.evaluation_expression for item in canonical_specs]
""",
        "canonical factor selection",
    )

    start = text.index("    diagnostics = [\n        _factor_diagnostic(")
    end = text.index("\n\n    acceptance_sha256 =", start)
    replacement = """    canonical_diagnostics: list[dict[str, Any]] = []
    for canonical_spec in canonical_specs:
        representative = canonical_spec.aliases[0]
        diagnostic = _factor_diagnostic(
            representative.group_name,
            representative.factor,
            features[canonical_spec.evaluation_expression],
            returns_series,
            date_map=date_map,
            requested_symbol_count=len(requested_symbols),
            top_n=top_n,
            bottom_n=bottom_n,
        )
        canonical_diagnostics.append(
            build_canonical_factor_row(canonical_spec, diagnostic)
        )

    canonical_diagnostics.sort(
        key=lambda row: (
            abs(float(row["oriented_rank_icir"] or 0.0)),
            abs(float(row["oriented_mean_rank_ic"] or 0.0)),
            float(row["coverage_ratio"] or 0.0),
        ),
        reverse=True,
    )
    for canonical_rank, row in enumerate(canonical_diagnostics, start=1):
        row["canonical_rank"] = canonical_rank

    diagnostics = [
        alias_row
        for canonical_row in canonical_diagnostics
        for alias_row in expand_alias_rows(canonical_row)
    ]
    validate_alias_metric_consistency(diagnostics)
    factor_alias_map = {
        str(row["id"]): str(row["canonical_expression_id"])
        for row in diagnostics
    }
"""
    text = text[:start] + replacement + text[end:]

    text = replace_once(
        text,
        """        "factor_count": len(diagnostics),
        "ranking_basis": [
            "absolute_oriented_rank_icir",
            "absolute_oriented_mean_rank_ic",
            "coverage_ratio",
        ],
        "factors": diagnostics,
""",
        """        "factor_count": len(diagnostics),
        "factor_id_count": len(diagnostics),
        "unique_expression_count": len(canonical_diagnostics),
        "canonical_factor_count": len(canonical_diagnostics),
        "factor_identity": factor_identity_metadata(),
        "ranking_subject": "canonical_expression",
        "ranking_basis": [
            "absolute_oriented_rank_icir",
            "absolute_oriented_mean_rank_ic",
            "coverage_ratio",
        ],
        "canonical_factors": canonical_diagnostics,
        "factor_alias_map": factor_alias_map,
        "factors": diagnostics,
""",
        "diagnostic output counts",
    )
    DIAGNOSTICS.write_text(text, encoding="utf-8")


def patch_pipeline() -> None:
    text = PIPELINE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'PIPELINE_SCHEMA_VERSION = "1.0"',
        'PIPELINE_SCHEMA_VERSION = "1.1"',
        "pipeline schema",
    )
    text = replace_once(
        text,
        '    manifest["factor_count"] = diagnostics.get("factor_count")\n',
        """    manifest["factor_count"] = diagnostics.get("factor_count")
    manifest["factor_id_count"] = diagnostics.get(
        "factor_id_count", diagnostics.get("factor_count")
    )
    manifest["unique_expression_count"] = diagnostics.get(
        "unique_expression_count"
    )
    manifest["canonical_factor_count"] = diagnostics.get(
        "canonical_factor_count", diagnostics.get("unique_expression_count")
    )
""",
        "pipeline factor counts",
    )
    PIPELINE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    identity_import = """from src.research.factor_identity import (
    canonical_expression_identity,
    validate_alias_metric_consistency,
)
"""
    paradigm_anchor = "from src.research.paradigm import load_research_paradigm_spec\n"
    if "from src.research.factor_identity import" not in text:
        text = replace_once(
            text,
            paradigm_anchor,
            identity_import + paradigm_anchor,
            "test identity import",
        )
    text = replace_once(
        text,
        """from src.research.spec_bound_factor_diagnostics import (
    _window_date_map,
""",
        """from src.research.spec_bound_factor_diagnostics import (
    _selected_factor_specs,
    _window_date_map,
""",
        "test selected factor import",
    )

    positive_anchor = """                            {
                                "id": "test:positive",
                                "expression": "POSITIVE_SIGNAL",
                                "family": "signal",
                            },
"""
    positive_with_alias = positive_anchor + """                            {
                                "id": "test:positive_alias",
                                "expression": " POSITIVE_SIGNAL ",
                                "family": "alias",
                            },
"""
    if '"id": "test:positive_alias"' not in text:
        text = replace_once(
            text, positive_anchor, positive_with_alias, "positive alias fixture"
        )

    text = replace_once(
        text,
        '    assert report["factor_count"] == 4\n',
        """    assert report["schema_version"] == "1.2"
    assert report["factor_count"] == 5
    assert report["factor_id_count"] == 5
    assert report["unique_expression_count"] == 4
    assert report["canonical_factor_count"] == 4
    assert len(report["canonical_factors"]) == 4
    assert report["ranking_subject"] == "canonical_expression"
    assert report["factor_identity"]["scheme"] == "qlib_expression_text_v1"
    assert (
        report["factor_alias_map"]["test:positive"]
        == report["factor_alias_map"]["test:positive_alias"]
    )
""",
        "diagnostic count assertions",
    )
    text = replace_once(
        text,
        '    assert factors["test:positive"]["oriented_mean_rank_ic"] > 0.8\n',
        """    assert factors["test:positive"]["oriented_mean_rank_ic"] > 0.8
    assert (
        factors["test:positive"]["canonical_expression_id"]
        == factors["test:positive_alias"]["canonical_expression_id"]
    )
    assert (
        factors["test:positive"]["oriented_rank_icir"]
        == factors["test:positive_alias"]["oriented_rank_icir"]
    )
""",
        "alias metric assertions",
    )

    marker = "\ndef test_factor_diagnostics_fail_closed_on_rejected_or_stale_acceptance(\n"
    addition = r'''

def test_factor_expression_identity_is_deterministic_and_conservative() -> None:
    compact = canonical_expression_identity("POSITIVE_SIGNAL")
    spaced = canonical_expression_identity("  POSITIVE_SIGNAL\n")
    parenthesized = canonical_expression_identity("(POSITIVE_SIGNAL)")

    assert compact == spaced
    assert compact["scheme"] == "qlib_expression_text_v1"
    assert compact["normalized_expression"] == "POSITIVE_SIGNAL"
    assert compact["canonical_expression_id"].startswith("qlib-expression:")
    assert compact != parenthesized


def test_alias_metric_divergence_fails_closed(tmp_path: Path) -> None:
    spec_path, symbols = _write_spec(tmp_path)
    report = run_factor_diagnostics(
        load_research_paradigm_spec(spec_path),
        _acceptance(tmp_path, spec_path),
        repository_root=tmp_path,
        runtime=FakeFactorRuntime(symbols),
    )
    factors = _by_id(report)
    rows = [dict(factors["test:positive"]), dict(factors["test:positive_alias"])]
    rows[1]["oriented_rank_icir"] = float(rows[1]["oriented_rank_icir"]) + 0.01

    with pytest.raises(ValueError, match="alias metrics diverged"):
        validate_alias_metric_consistency(rows)


@pytest.mark.parametrize(
    ("spec_name", "factor_id_count", "unique_expression_count"),
    [
        ("cn_10d_csi300_baseline.yaml", 47, 23),
        ("us_10d_qqq_baseline.yaml", 24, 9),
    ],
)
def test_production_factor_libraries_have_expected_alias_counts(
    spec_name: str,
    factor_id_count: int,
    unique_expression_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(repository_root)
    spec = load_research_paradigm_spec(
        repository_root / "configs" / "research_paradigms" / spec_name
    )
    factor_specs = _selected_factor_specs(spec)
    canonical = {
        canonical_expression_identity(factor.expression)["canonical_expression_id"]
        for _, factor in factor_specs
    }

    assert len(factor_specs) == factor_id_count
    assert len(canonical) == unique_expression_count
'''
    if "test_factor_expression_identity_is_deterministic_and_conservative" not in text:
        if marker not in text:
            raise RuntimeError("test insertion marker not found")
        text = text.replace(marker, addition + marker, 1)
    TESTS.write_text(text, encoding="utf-8")


def patch_pipeline_tests() -> None:
    text = PIPELINE_TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """            "factor_count": 4,
            "sampled_rebalance_dates": 60,
""",
        """            "factor_count": 4,
            "factor_id_count": 4,
            "unique_expression_count": 2,
            "canonical_factor_count": 2,
            "sampled_rebalance_dates": 60,
""",
        "pipeline diagnostic fixture counts",
    )
    text = replace_once(
        text,
        '    assert manifest["factor_count"] == 4\n',
        """    assert manifest["schema_version"] == "1.1"
    assert manifest["factor_count"] == 4
    assert manifest["factor_id_count"] == 4
    assert manifest["unique_expression_count"] == 2
    assert manifest["canonical_factor_count"] == 2
""",
        "pipeline count assertions",
    )
    PIPELINE_TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_diagnostics()
    patch_pipeline()
    patch_tests()
    patch_pipeline_tests()


if __name__ == "__main__":
    main()
