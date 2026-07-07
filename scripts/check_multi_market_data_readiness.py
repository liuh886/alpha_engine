"""Check US/CN data readiness before running 10D model evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.multi_market_readiness import (
    check_market_data_coverage,
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


def run(root: Path, *, train_start: str, test_end: str) -> dict[str, Any]:
    specs = default_market_specs(train_start=train_start, test_end=test_end, watchlist_path=root / "configs" / "watchlist.yaml")
    reports: dict[str, dict[str, Any]] = {}
    for spec in specs:
        init_error = _try_init_market(root, spec.market)
        if init_error:
            reports[spec.market] = {
                "market": spec.market,
                "benchmark": spec.benchmark,
                "train_start": spec.train_start,
                "test_end": spec.test_end,
                "requested_symbols": list(spec.symbols),
                "retained_symbols": [],
                "dropped_symbols": list(spec.symbols),
                "coverage_ratio": 0.0,
                "sufficient": False,
                "skipped": True,
                "skip_reason": init_error,
                "normalization": [],
            }
            continue
        reports[spec.market] = check_market_data_coverage(spec)

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
    args = parser.parse_args()
    print(json.dumps(run(args.root, train_start=args.train_start, test_end=args.test_end), indent=2))


if __name__ == "__main__":
    main()
