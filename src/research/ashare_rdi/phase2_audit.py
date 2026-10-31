"""Research entrypoint: fail closed when archived event coverage is absent.

This command never calls providers, trains a model or creates a trading signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

STUDY_HORIZONS = (7, 14, 28)


def source_readiness(price_path: Path) -> dict[str, object]:
    from src.research.ashare_rdi.phase2 import CSI300_INCEPTION, read_price_csv

    bars = read_price_csv(price_path, min_session=CSI300_INCEPTION)
    digest = hashlib.sha256(price_path.read_bytes()).hexdigest()
    return {
        "status": "blocked_event_pit_coverage",
        "benchmark": "CSI300 / 000300.SH",
        "benchmark_type": "nontraded_equity_index",
        "benchmark_source": price_path.as_posix(),
        "price_file_sha256": digest,
        "price_history_rows": len(bars),
        "first_observed_session": bars[0].session.isoformat(),
        "last_observed_session": bars[-1].session.isoformat(),
        "event_history_ready": False,
        "why_no_rdi_score": (
            "No verified PIT coverage-by-session archive for required event families. "
            "Missing events must not be scored as zero."
        ),
        "horizons_trading_sessions": list(STUDY_HORIZONS),
        "research_only": True,
        "trade_ready": False,
        "predictive_claim": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RDI phase2 governed input readiness audit")
    parser.add_argument("--benchmark-csv", default="data/csv_source/000300.csv")
    parser.add_argument("--output", default="", help="optional JSON output path")
    parser.add_argument("--product-briefing", action="store_true", help="project reviewed evidence only")
    parser.add_argument("--price-renewal-audit", action="store_true", help="read-only splice preflight")
    parser.add_argument("--as-of", help="completed CN cutoff for renewal preflight")
    parser.add_argument("--price-reconstruction-contract", help="frozen versioned price-only repair contract")
    parser.add_argument("--write-reconstructed-prices", help="optional disposable CSV under artifacts/")
    args = parser.parse_args()
    if args.price_reconstruction_contract:
        from src.research.market_session_clock import completed_market_date

        from .price_reconstruction import recompute, repo_file

        if args.product_briefing or args.price_renewal_audit or not args.as_of:
            parser.error("price reconstruction requires --as-of and excludes other modes")
        root = Path(__file__).resolve().parents[3]
        prices, result = recompute(
            root, repo_file(root, args.price_reconstruction_contract),
            completed_cutoff=date.fromisoformat(completed_market_date("cn", args.as_of)),
        )
        if args.write_reconstructed_prices:
            destination = repo_file(root, args.write_reconstructed_prices)
            destination.relative_to((root / "artifacts").resolve())
            if destination.exists() and destination.read_bytes() != prices:
                raise ValueError("refusing to overwrite a different reconstructed artifact")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(prices)
    elif args.write_reconstructed_prices:
        parser.error("--write-reconstructed-prices requires a reconstruction contract")
    elif args.price_renewal_audit:
        from src.research.market_session_clock import completed_market_date

        from .price_renewal import audit_price_renewal

        if args.product_briefing or not args.as_of:
            parser.error("renewal audit requires --as-of and excludes --product-briefing")
        root = Path(__file__).resolve().parents[3]
        # This mode reproduces the original failed append-only preflight;
        # product review rebinding must not change its historical input.
        readiness_bytes = (root / "docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json").read_bytes()
        reviewed = json.loads(readiness_bytes)
        blob = reviewed["source_git_blob_sha1"]
        if len(blob) != 40 or any(c not in "0123456789abcdef" for c in blob):
            raise ValueError("invalid retained source Git blob")
        legacy = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=root)
        market = root / "data/research/market_evidence/cn"
        result = audit_price_renewal(
            legacy, (market / "catalog.json").read_bytes(),
            (market / "symbols/000300.json").read_bytes(),
            completed_cutoff=date.fromisoformat(completed_market_date("cn", args.as_of)),
        )
        result.update({
            "source_git_blob_sha1": blob,
            "reviewed_readiness_sha256": hashlib.sha256(readiness_bytes).hexdigest(),
            "repository_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            ).strip(),
            "implementation_sha256": hashlib.sha256(
                (root / "src/research/ashare_rdi/price_renewal.py").read_bytes(),
            ).hexdigest(),
            "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
            "reference_registry_sha256": hashlib.sha256(
                (root / "configs/pools/reference_instrument_registry_v1.yaml").read_bytes(),
            ).hexdigest(),
        })
    elif args.product_briefing:
        from .briefing import build_research_briefing

        result = build_research_briefing(Path(__file__).resolve().parents[3])
    else:
        result = source_readiness(Path(args.benchmark_csv))
    formatted = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(formatted + "\n", encoding="utf-8")
    print(formatted)


if __name__ == "__main__":
    main()
