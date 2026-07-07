"""Check US/CN data readiness before running 10D model evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.market_data_alignment import build_aligned_market_readiness
from src.research.multi_market_readiness import (
    default_market_specs,
    render_readiness_markdown,
    summarize_multi_market_readiness,
)


def _try_init_market(root: Path, market: str) -> str | None:
    try:
        safe_qlib_init(
            build_qlib_init_cfg(
                None,
                market=market,
                provider_uri_default=str(root / "data" / "watchlist"),
            )
        )
        return None
    except Exception as exc:
        return f"{market} skipped because Qlib init failed: {exc}"


def run(root: Path, *, train_start: str, test_end: str, alignment_mode: str = "strict") -> dict[str, Any]:
    specs = default_market_specs(train_start=train_start, test_end=test_end, watchlist_path=root / "configs" / "watchlist.yaml")
    reports: dict[str, dict[str, Any]] = {}

    # Init Qlib for each market so date coverage can be loaded
    for spec in specs:
        _try_init_market(root, spec.market)

    # Use alignment-aware readiness check
    aligned_reports = build_aligned_market_readiness(specs, alignment_mode=alignment_mode)

    for spec in specs:
        market = spec.market
        if market in aligned_reports:
            reports[market] = aligned_reports[market]
        else:
            reports[market] = {
                "market": market,
                "benchmark": spec.benchmark,
                "requested_train_start": spec.train_start,
                "aligned_train_start": spec.train_start,
                "alignment_mode": alignment_mode,
                "requested_symbols": list(spec.symbols),
                "retained_symbols": [],
                "dropped_symbols": list(spec.symbols),
                "coverage_ratio": 0.0,
                "sufficient": False,
                "skipped": True,
                "skip_reason": f"{market} alignment not produced",
                "normalization": [],
            }

    summary = summarize_multi_market_readiness(reports)
    out_dir = root / "artifacts" / "evidence" / "multi_market_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "readiness_report.json"
    md_path = out_dir / "readiness_report.md"
    payload = {"schema_version": "1.0", "summary": summary, "markets": reports}
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_readiness_markdown(reports, summary), encoding="utf-8")
    return {"report_path": str(report_path), "markdown_path": str(md_path), "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--train-start", default="2021-01-01")
    parser.add_argument("--test-end", default="2026-06-18")
    parser.add_argument("--alignment-mode", choices=["strict", "auto"], default="strict",
                        help="Train-start alignment mode (default: strict)")
    args = parser.parse_args()
    print(json.dumps(run(args.root, train_start=args.train_start, test_end=args.test_end, alignment_mode=args.alignment_mode), indent=2))


if __name__ == "__main__":
    main()
