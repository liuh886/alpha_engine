from pathlib import Path

path = Path("scripts/update_data.py")
text = path.read_text(encoding="utf-8")

import_anchor = "import copy\nimport sys\n"
import_replacement = "import copy\nimport shutil\nimport sys\n"
if text.count(import_anchor) != 1:
    raise SystemExit("shutil import anchor not found exactly once")
text = text.replace(import_anchor, import_replacement, 1)

helper_anchor = '''    return start, end


def _validate_quality_report(
'''
helper_replacement = '''    return start, end


_CANONICAL_BENCHMARKS = {
    "cn": {"000300"},
    "us": {"QQQ"},
    "hk": set(),
}


def _benchmark_symbols_for_markets(markets: set[str]) -> set[str]:
    return {
        symbol
        for market in markets
        for symbol in _CANONICAL_BENCHMARKS.get(market, set())
    }


def _prepare_source_dir(data_dir: Path, *, requested_end: str | None) -> Path:
    if requested_end is None:
        source_dir = data_dir / "csv_source"
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    source_dir = data_dir / "csv_source_declared_interval"
    shutil.rmtree(source_dir, ignore_errors=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    return source_dir


def _validate_quality_report(
'''
if text.count(helper_anchor) != 1:
    raise SystemExit("helper insertion anchor not found exactly once")
text = text.replace(helper_anchor, helper_replacement, 1)

source_anchor = '''    watchlist = load_watchlist()
    source_dir = DATA_DIR / "csv_source"
    source_dir.mkdir(parents=True, exist_ok=True)

    policy = load_router_policy()
'''
source_replacement = '''    watchlist = load_watchlist()

    policy = load_router_policy()
'''
if text.count(source_anchor) != 1:
    raise SystemExit("source-dir removal anchor not found exactly once")
text = text.replace(source_anchor, source_replacement, 1)

universe_anchor = '''    selected_markets = {k for k, v in regions.items() if v}
    universe = build_selected_universe(regions)

    accounting = UpdateAccounting(configured=universe)
'''
universe_replacement = '''    selected_markets = {k for k, v in regions.items() if v}
    universe = build_selected_universe(regions)
    source_dir = _prepare_source_dir(DATA_DIR, requested_end=args.end)

    accounting = UpdateAccounting(configured=universe)
'''
if text.count(universe_anchor) != 1:
    raise SystemExit("source-dir preparation anchor not found exactly once")
text = text.replace(universe_anchor, universe_replacement, 1)

quality_anchor = '''        requested_start=args.start if args.full else None,
        requested_end=args.end,
    )
'''
quality_replacement = '''        requested_start=args.start if args.full else None,
        requested_end=args.end,
        benchmark_symbols=_benchmark_symbols_for_markets(selected_markets),
        provider_attempts=provider_diagnostics,
    )
'''
if text.count(quality_anchor) != 1:
    raise SystemExit("quality context anchor not found exactly once")
text = text.replace(quality_anchor, quality_replacement, 1)

path.write_text(text, encoding="utf-8")
