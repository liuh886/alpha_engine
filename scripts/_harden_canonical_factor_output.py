"""Harden the Issue #147 output contract after focused review.

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
        """    diagnostics = [
        alias_row
        for canonical_row in canonical_diagnostics
        for alias_row in expand_alias_rows(canonical_row)
    ]
    validate_alias_metric_consistency(diagnostics)
    factor_alias_map = {
        str(row["id"]): str(row["canonical_expression_id"])
        for row in diagnostics
    }
""",
        """    factor_alias_rows = [
        alias_row
        for canonical_row in canonical_diagnostics
        for alias_row in expand_alias_rows(canonical_row)
    ]
    validate_alias_metric_consistency(factor_alias_rows)
    factor_alias_map = {
        str(row["id"]): str(row["canonical_expression_id"])
        for row in factor_alias_rows
    }
""",
        "alias row variable",
    )
    text = replace_once(
        text,
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
        """        "factor_count": len(canonical_diagnostics),
        "factor_id_count": len(factor_alias_rows),
        "unique_expression_count": len(canonical_diagnostics),
        "factor_identity": factor_identity_metadata(),
        "ranking_subject": "canonical_expression",
        "ranking_basis": [
            "absolute_oriented_rank_icir",
            "absolute_oriented_mean_rank_ic",
            "coverage_ratio",
        ],
        "factors": canonical_diagnostics,
        "factor_alias_rows": factor_alias_rows,
        "factor_alias_map": factor_alias_map,
""",
        "canonical output contract",
    )
    DIAGNOSTICS.write_text(text, encoding="utf-8")


def patch_pipeline() -> None:
    text = PIPELINE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """    manifest["unique_expression_count"] = diagnostics.get(
        "unique_expression_count"
    )
    manifest["canonical_factor_count"] = diagnostics.get(
        "canonical_factor_count", diagnostics.get("unique_expression_count")
    )
""",
        """    manifest["unique_expression_count"] = diagnostics.get(
        "unique_expression_count"
    )
""",
        "remove redundant canonical count",
    )
    PIPELINE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    return {row["id"]: row for row in report["factors"]}\n',
        '    return {row["id"]: row for row in report["factor_alias_rows"]}\n',
        "alias lookup helper",
    )
    text = replace_once(
        text,
        """    assert report["factor_count"] == 5
    assert report["factor_id_count"] == 5
    assert report["unique_expression_count"] == 4
    assert report["canonical_factor_count"] == 4
    assert len(report["canonical_factors"]) == 4
""",
        """    assert report["factor_count"] == 4
    assert report["factor_id_count"] == 5
    assert report["unique_expression_count"] == 4
    assert len(report["factors"]) == 4
    assert len(report["factor_alias_rows"]) == 5
""",
        "test canonical counts",
    )
    text = replace_once(
        text,
        '    assert compact != parenthesized\n',
        """    assert compact != parenthesized
    quoted = canonical_expression_identity('Func( "a b" )')
    assert quoted == canonical_expression_identity('Func("a b")')
    assert quoted != canonical_expression_identity('Func("ab")')
""",
        "quoted literal identity test",
    )
    text = replace_once(
        text,
        """    assert (
        factors["test:positive"]["oriented_rank_icir"]
        == factors["test:positive_alias"]["oriented_rank_icir"]
    )
""",
        """    assert (
        factors["test:positive"]["oriented_rank_icir"]
        == factors["test:positive_alias"]["oriented_rank_icir"]
    )
    assert factors["test:positive_alias"]["expression"] == " POSITIVE_SIGNAL "
""",
        "raw alias expression assertion",
    )
    TESTS.write_text(text, encoding="utf-8")


def patch_pipeline_tests() -> None:
    text = PIPELINE_TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """            "factor_count": 4,
            "factor_id_count": 4,
            "unique_expression_count": 2,
            "canonical_factor_count": 2,
""",
        """            "factor_count": 2,
            "factor_id_count": 4,
            "unique_expression_count": 2,
""",
        "pipeline fixture semantics",
    )
    text = replace_once(
        text,
        """    assert manifest["factor_count"] == 4
    assert manifest["factor_id_count"] == 4
    assert manifest["unique_expression_count"] == 2
    assert manifest["canonical_factor_count"] == 2
""",
        """    assert manifest["factor_count"] == 2
    assert manifest["factor_id_count"] == 4
    assert manifest["unique_expression_count"] == 2
""",
        "pipeline count semantics",
    )
    PIPELINE_TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_diagnostics()
    patch_pipeline()
    patch_tests()
    patch_pipeline_tests()


if __name__ == "__main__":
    main()
