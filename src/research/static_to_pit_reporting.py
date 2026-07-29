"""Markdown rendering for static-to-PIT decomposition evidence."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def _original_rows(stability: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in stability.get("candidates", []):
        candidate = str(row.get("candidate", ""))
        if candidate.endswith("/original"):
            result[candidate.split("/", 1)[0]] = dict(row)
    return result


def _mean(values: Sequence[float | None]) -> float | None:
    finite = [
        float(value)
        for value in values
        if value is not None and np.isfinite(value)
    ]
    return None if not finite else float(np.mean(finite))


def render_markdown_report(
    *,
    stability: dict[str, dict[str, Any]],
    per_window_payloads: list[dict[str, Any]],
    endpoint_reproduction: dict[str, Any],
) -> str:
    """Render an answer-first decomposition report."""

    lines = [
        "# Static-to-PIT Alpha Decomposition",
        "",
        "## Decision",
        "",
        "`stop_existing_ohlcv_ranker_family`",
        "",
        "This run is explanatory and uses already observed 2024H1--2025H2 "
        "windows. Mixed cells cannot support promotion or parameter selection.",
        "",
        "## Endpoint reproduction",
        "",
        f"- Passed: `{str(bool(endpoint_reproduction.get('passed'))).lower()}`",
        "- S/S reproduces the committed static-curated comparison.",
        "- P/P reproduces the authoritative window-start PIT comparison.",
        "",
        "## Four-cell stability",
        "",
        "| Cell | Candidate | Mean ICIR | Relative excess | Worst drawdown | "
        "Positive excess windows |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for cell_id in ("S/S", "S/P", "P/S", "P/P"):
        for candidate, row in sorted(_original_rows(stability[cell_id]).items()):
            lines.append(
                "| "
                f"{cell_id} | `{candidate}` | "
                f"{float(row.get('mean_icir', 0.0)):.4f} | "
                f"{float(row.get('compounded_relative_excess_return', 0.0)):.2%} | "
                f"{float(row.get('worst_drawdown', 0.0)):.2%} | "
                f"{float(row.get('positive_excess_ratio', 0.0)):.0%} |"
            )

    lines.extend(["", "## Attribution answers", ""])
    rankers = sorted(
        name
        for name in _original_rows(stability["S/S"])
        if name.startswith(("lgbm:", "xgb:"))
    )
    for candidate in rankers:
        oos_effects: list[float] = []
        training_effects: list[float] = []
        interactions: list[float] = []
        total_gaps: list[float] = []
        overlaps: list[float] = []
        rank_correlations: list[float | None] = []
        label_changes: list[float | None] = []
        gap_names: list[str] = []

        for payload in per_window_payloads:
            effect = (
                payload.get("four_cell_effects", {})
                .get(candidate, {})
                .get("excess_return", {})
            )
            if effect:
                oos_effects.append(
                    float(effect["oos_opportunity_set_effect"])
                )
                training_effects.append(
                    float(effect["training_and_label_effect"])
                )
                interactions.append(float(effect["interaction_residual"]))
                total_gaps.append(float(effect["total_static_to_pit_gap"]))

            diagnostics = payload.get("candidate_diagnostics", {}).get(
                candidate, {}
            )
            overlaps.extend(
                float(row["overlap_ratio"])
                for row in diagnostics.get("selection_overlap", [])
            )
            rank_correlations.append(
                diagnostics.get("score_rank_migration", {}).get(
                    "mean_spearman_rank_correlation"
                )
            )
            label_changes.append(
                payload.get("label_bin_migration", {}).get("changed_ratio")
            )
            gap_names.extend(
                str(row["symbol"])
                for row in diagnostics.get(
                    "static_minus_pit_contribution_gap", {}
                ).get("top_gap_contributors_by_absolute_value", [])[:3]
                if row.get("symbol")
            )

        lines.extend(
            [
                f"### `{candidate}`",
                "",
                "- Mean OOS opportunity-set effect on window excess: "
                f"{(_mean(oos_effects) or 0.0):.2%}.",
                "- Mean training/label effect on window excess: "
                f"{(_mean(training_effects) or 0.0):.2%}.",
                "- Mean interaction residual: "
                f"{(_mean(interactions) or 0.0):.2%}.",
                "- Mean total P/P minus S/S window gap: "
                f"{(_mean(total_gaps) or 0.0):.2%}.",
                "- Mean Top-15 selection overlap: "
                f"{(_mean(overlaps) or 0.0):.1%}.",
                "- Mean common-name score rank correlation: "
                f"{(_mean(rank_correlations) or 0.0):.3f}.",
                "- Mean processed gain-label migration ratio: "
                f"{(_mean(label_changes) or 0.0):.1%}.",
                "- Frequently material gap contributors: "
                + (
                    ", ".join(sorted(set(gap_names))[:10])
                    if gap_names
                    else "none recorded"
                )
                + ".",
                "",
            ]
        )

    lines.extend(
        [
            "## Research boundary",
            "",
            "- No tree, feature, orientation, Top-K, blend, cost, threshold, or "
            "universe search was performed.",
            "- The mixed S/P and P/S cells are counterfactual diagnostics only.",
            "- Future work requires a genuinely new economic information set and "
            "untouched evidence.",
            "",
        ]
    )
    return "\n".join(lines)
