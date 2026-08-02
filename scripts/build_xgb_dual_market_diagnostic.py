#!/usr/bin/env python3
"""Build deterministic diagnostics from the bound dual-market XGBoost identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

import yaml


DEFAULT_IDENTITY = Path(
    "configs/research_paradigms/xgb_dual_market_baseline_identity_v1.yaml"
)
DEFAULT_DIAGNOSTIC = Path(
    "configs/research_paradigms/xgb_dual_market_diagnostic_v1.yaml"
)
DEFAULT_OUTPUT_DIR = Path("artifacts/evidence/xgb_dual_market_diagnostic")


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping and fail closed on other root types."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping at {path}")
    return cast(dict[str, Any], payload)


def _window_name(window: dict[str, Any]) -> str:
    return str(window["window"])


def analyze_market(
    market: str,
    identity: dict[str, Any],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    """Compute bounded cross-window diagnostics for one market."""
    windows = cast(list[dict[str, Any]], identity["window_evidence"][market])
    baseline = cast(
        dict[str, Any], identity["markets"][market]["verified_current_baseline"]
    )
    rules = cast(dict[str, Any], diagnostic["rules"])

    epsilon = float(rules["positive_excess_epsilon"])
    concentration_threshold = float(rules["concentration_share_threshold"])
    mismatch_threshold = int(rules["signal_alignment_mismatch_threshold"])

    positive_windows = [
        window for window in windows if float(window["simple_excess"]) > epsilon
    ]
    positive_excess_total = sum(
        float(window["simple_excess"]) for window in positive_windows
    )
    strongest = max(windows, key=lambda window: float(window["simple_excess"]))
    weakest = min(windows, key=lambda window: float(window["simple_excess"]))
    worst_drawdown = min(windows, key=lambda window: float(window["max_drawdown"]))

    strongest_share = 0.0
    if positive_excess_total > 0.0:
        strongest_share = float(strongest["simple_excess"]) / positive_excess_total

    mismatches: list[dict[str, Any]] = []
    for window in positive_windows:
        non_positive_metrics: list[str] = []
        if float(window["icir"]) <= 0.0:
            non_positive_metrics.append("icir")
        if float(window["rank_ic"]) <= 0.0:
            non_positive_metrics.append("rank_ic")
        if non_positive_metrics:
            mismatches.append(
                {
                    "window": _window_name(window),
                    "simple_excess": float(window["simple_excess"]),
                    "non_positive_signal_metrics": non_positive_metrics,
                }
            )

    classification = "general_stability_diagnosis"
    triggers: list[str] = []
    if market == "us":
        tail_threshold = float(rules["us_tail_drawdown_threshold"])
        if strongest_share >= concentration_threshold:
            triggers.append("strongest_positive_excess_is_concentrated")
        if float(worst_drawdown["max_drawdown"]) <= tail_threshold:
            triggers.append("worst_drawdown_exceeds_tail_threshold")
        if len(triggers) == 2:
            classification = "tail_risk_and_concentration_first"
    elif market == "cn" and len(mismatches) >= mismatch_threshold:
        classification = "ranking_validity_and_exposure_first"
        triggers.append("positive_excess_not_aligned_with_signal_metrics")

    return {
        "market": market,
        "classification": classification,
        "classification_triggers": triggers,
        "baseline": {
            "candidate": baseline["candidate"],
            "compounded_relative_excess_return": float(
                baseline["compounded_relative_excess_return"]
            ),
            "mean_icir": float(baseline["mean_icir"]),
            "mean_rank_ic": float(baseline["mean_rank_ic"]),
            "worst_drawdown": float(baseline["worst_drawdown"]),
            "ready_ratio": float(baseline["ready_ratio"]),
            "promotion_status": baseline["promotion_status"],
        },
        "window_count": len(windows),
        "positive_excess_window_count": len(positive_windows),
        "positive_excess_total_simple": positive_excess_total,
        "strongest_window": {
            "window": _window_name(strongest),
            "simple_excess": float(strongest["simple_excess"]),
            "share_of_positive_simple_excess": strongest_share,
        },
        "weakest_window": {
            "window": _window_name(weakest),
            "simple_excess": float(weakest["simple_excess"]),
        },
        "worst_drawdown_window": {
            "window": _window_name(worst_drawdown),
            "max_drawdown": float(worst_drawdown["max_drawdown"]),
        },
        "positive_excess_signal_mismatches": mismatches,
        "positive_excess_signal_mismatch_count": len(mismatches),
        "variant_search_authorized": False,
        "trade_ready": False,
    }


def build_report(
    identity: dict[str, Any], diagnostic: dict[str, Any]
) -> dict[str, Any]:
    """Build the complete deterministic diagnostic report."""
    markets = {
        market: analyze_market(market, identity, diagnostic)
        for market in ("us", "cn")
    }
    return {
        "schema_version": "1.0",
        "diagnostic_id": diagnostic["diagnostic_id"],
        "status": "diagnosis_completed_no_variant_authorization",
        "baseline_identity_id": identity["identity_id"],
        "research_only": True,
        "trade_ready": False,
        "markets": markets,
        "conclusion": {
            "us": "Prioritize tail-risk and contribution-concentration diagnosis.",
            "cn": "Prioritize ranking-validity and hidden-exposure attribution.",
            "variant_search_authorized": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable diagnostic report."""
    lines = [
        "# XGBoost dual-market diagnostic",
        "",
        "This report is diagnosis-only. It does not authorize parameter search or model promotion.",
        "",
    ]
    markets = cast(dict[str, dict[str, Any]], report["markets"])
    for market in ("us", "cn"):
        result = markets[market]
        baseline = cast(dict[str, Any], result["baseline"])
        strongest = cast(dict[str, Any], result["strongest_window"])
        weakest = cast(dict[str, Any], result["weakest_window"])
        worst = cast(dict[str, Any], result["worst_drawdown_window"])
        lines.extend(
            [
                f"## {market.upper()}",
                "",
                f"- Classification: `{result['classification']}`",
                "- Compounded relative excess: "
                f"{float(baseline['compounded_relative_excess_return']):.2%}",
                f"- Mean ICIR: {float(baseline['mean_icir']):.4f}",
                f"- Mean Rank IC: {float(baseline['mean_rank_ic']):.4f}",
                "- Strongest window: "
                f"{strongest['window']} ({float(strongest['simple_excess']):.2%} simple excess)",
                "- Strongest-window share of positive simple excess: "
                f"{float(strongest['share_of_positive_simple_excess']):.2%}",
                "- Weakest window: "
                f"{weakest['window']} ({float(weakest['simple_excess']):.2%} simple excess)",
                "- Worst drawdown window: "
                f"{worst['window']} ({float(worst['max_drawdown']):.2%})",
                "- Positive-excess signal mismatches: "
                f"{int(result['positive_excess_signal_mismatch_count'])}",
                "",
            ]
        )
        mismatches = cast(
            list[dict[str, Any]], result["positive_excess_signal_mismatches"]
        )
        for mismatch in mismatches:
            metrics = ", ".join(
                cast(list[str], mismatch["non_positive_signal_metrics"])
            )
            lines.append(
                f"  - {mismatch['window']}: positive excess with non-positive {metrics}."
            )
        if mismatches:
            lines.append("")

    lines.extend(
        [
            "## Decision",
            "",
            "US proceeds first through tail-risk, concentration and portfolio-efficiency diagnostics.",
            "CN proceeds first through exposure attribution and ranking-signal validation.",
            "Neither path is authorized to consume the final challenge window.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "xgb_dual_market_diagnostic.json"
    markdown_path = output_dir / "xgb_dual_market_diagnostic.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    identity = load_yaml(args.identity)
    diagnostic = load_yaml(args.diagnostic)
    report = build_report(identity, diagnostic)
    json_path, markdown_path = write_report(report, args.output_dir)
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
