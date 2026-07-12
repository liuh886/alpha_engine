"""One-time mechanical migration for issue #128. Deleted before merge."""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"migration anchor not found: {label}")
    return text.replace(old, new, 1)


def patch_snapshot() -> None:
    path = Path("src/data/snapshot.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        if snapshot.manifest.quality_verdict != "pass":
            raise ValueError(
                f"Cannot publish snapshot {snapshot_id}: "
                f"quality_verdict={snapshot.manifest.quality_verdict!r}"
            )
''',
        '''        publishable_verdicts = {"pass", "pass_with_warnings"}
        if snapshot.manifest.quality_verdict not in publishable_verdicts:
            raise ValueError(
                f"Cannot publish snapshot {snapshot_id}: "
                f"quality_verdict={snapshot.manifest.quality_verdict!r}"
            )
''',
        "snapshot warning verdict",
    )
    path.write_text(text, encoding="utf-8")


def patch_update_data() -> None:
    path = Path("scripts/update_data.py")
    text = path.read_text(encoding="utf-8")
    import_anchor = "from src.data.quality import generate_data_quality_summary\n"
    import_line = '''from src.data.provider_evidence import (
    build_universe_evidence,
    provider_attempts_evidence,
    read_effective_provider_universe,
)
'''
    text = replace_once(text, import_anchor, import_anchor + import_line, "provider evidence import")

    old_quality = '''def _validate_quality_report(
    quality_report: dict, *, universe: dict[str, list[str]], quality_policy: dict
) -> None:
    if not isinstance(quality_report, dict) or not quality_report.get("ok"):
        raise DataUpdateFailure(
            str((quality_report or {}).get("error") or "quality validation failed")
        )
    warnings = quality_report.get("warnings") or []
    if warnings and not quality_policy.get("allow_warnings", False):
        raise DataUpdateFailure(f"quality warnings are not allowed: {warnings}")
    markets = quality_report.get("markets")
    if not isinstance(markets, dict):
        raise DataUpdateFailure("quality report markets are missing")
    for market, symbols in universe.items():
        report = markets.get(market)
        if not isinstance(report, dict) or report.get("error"):
            raise DataUpdateFailure(f"quality report missing for market={market}")
        if int(report.get("instruments", -1)) != len(symbols):
            raise DataUpdateFailure(
                f"quality coverage mismatch for market={market}: "
                f"expected={len(symbols)} actual={report.get('instruments')}"
            )
        for field_name in (
            "stale_instruments",
            "csv_missing",
            "csv_parse_errors",
            "csv_stale",
        ):
            if int(report.get(field_name, 0) or 0) != 0:
                raise DataUpdateFailure(
                    f"quality failure for market={market}: {field_name}={report.get(field_name)}"
                )
'''
    new_quality = '''def _validate_quality_report(
    quality_report: dict,
    *,
    configured_universe: dict[str, list[str]],
    effective_universe: dict[str, list[str]],
    quality_policy: dict,
) -> None:
    """Validate quality against actual provider membership, not configured intent."""

    if not isinstance(quality_report, dict) or not quality_report.get("ok"):
        raise DataUpdateFailure(
            str((quality_report or {}).get("error") or "quality validation failed")
        )
    warnings = quality_report.get("warnings") or []
    if warnings and not quality_policy.get("allow_warnings", False):
        raise DataUpdateFailure(f"quality warnings are not allowed: {warnings}")
    markets = quality_report.get("markets")
    if not isinstance(markets, dict):
        raise DataUpdateFailure("quality report markets are missing")

    for market, configured_symbols in configured_universe.items():
        report = markets.get(market)
        if not isinstance(report, dict) or report.get("error"):
            raise DataUpdateFailure(f"quality report missing for market={market}")
        effective_symbols = effective_universe.get(market, [])
        if int(report.get("instruments", -1)) != len(effective_symbols):
            raise DataUpdateFailure(
                f"quality/provider mismatch for market={market}: "
                f"effective={len(effective_symbols)} reported={report.get('instruments')}"
            )
        extra = sorted(set(effective_symbols) - set(configured_symbols))
        if extra:
            raise DataUpdateFailure(
                f"provider contains unconfigured symbols for market={market}: {extra[:20]}"
            )
        for field_name in (
            "stale_instruments",
            "csv_missing",
            "csv_parse_errors",
            "csv_stale",
        ):
            if int(report.get(field_name, 0) or 0) != 0:
                raise DataUpdateFailure(
                    f"quality failure for market={market}: {field_name}={report.get(field_name)}"
                )
'''
    text = replace_once(text, old_quality, new_quality, "quality validation")

    text = replace_once(
        text,
        '''    max_missing_pct: float = 0.05,
    max_missing_count: int = 20,
) -> DataSnapshot:
''',
        '''    max_missing_pct: float = 0.05,
    max_missing_count: int = 20,
    provider_attempts_path: str | Path | None = None,
) -> DataSnapshot:
''',
        "publish signature",
    )

    old_publish_prelude = '''    if warnings:
        quality_report.setdefault("warnings", []).extend(warnings)
    _validate_quality_report(quality_report, universe=universe, quality_policy=quality_policy)
    provider_dir = Path(provider_dir)
    calendar_path = provider_dir / "calendars" / f"{frequency}.txt"
'''
    new_publish_prelude = '''    if warnings:
        quality_report.setdefault("warnings", []).extend(warnings)
    provider_dir = Path(provider_dir)
    effective_universe = read_effective_provider_universe(
        provider_dir,
        list(universe),
    )
    universe_evidence = build_universe_evidence(
        configured=universe,
        effective=effective_universe,
    )
    attempts_evidence = provider_attempts_evidence(provider_attempts_path)
    quality_report["universe"] = universe_evidence
    quality_report["provider_attempts"] = attempts_evidence
    _validate_quality_report(
        quality_report,
        configured_universe=universe,
        effective_universe=effective_universe,
        quality_policy=quality_policy,
    )
    has_missing = any(
        universe_evidence["missing"].get(market)
        for market in selected_markets
    )
    quality_verdict = (
        "pass_with_warnings"
        if has_missing or bool(quality_report.get("warnings"))
        else "pass"
    )
    update_summary = accounting.to_dict()
    update_summary["provider_attempts"] = attempts_evidence
    update_summary["universe_identity"] = {
        "configured_sha256": universe_evidence["configured_sha256"],
        "effective_sha256": universe_evidence["effective_sha256"],
    }
    calendar_path = provider_dir / "calendars" / f"{frequency}.txt"
'''
    text = replace_once(text, old_publish_prelude, new_publish_prelude, "publish prelude")
    text = replace_once(text, "        universe=universe,\n", "        universe=universe_evidence,\n", "snapshot universe")
    text = replace_once(
        text,
        '''        update_summary=accounting.to_dict(),
        quality_verdict="pass",
''',
        '''        update_summary=update_summary,
        quality_verdict=quality_verdict,
''',
        "snapshot verdict",
    )

    start = text.index("def _write_provider_diagnostics(")
    end = text.index("\n\ndef run_data_update", start)
    diagnostics_function = '''def _write_provider_diagnostics(diagnostics: list[dict], artifacts_dir: Path) -> Path:
    """Write immutable and latest per-symbol provider attempt evidence."""

    import json
    from datetime import datetime, timezone

    diag_dir = artifacts_dir / "data_update_diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc)
    output = {
        "schema_version": "2.0",
        "generated_at": generated_at.isoformat(),
        "total_symbols": len(diagnostics),
        "succeeded": sum(1 for item in diagnostics if item["ok"]),
        "failed": sum(1 for item in diagnostics if not item["ok"]),
        "symbols": diagnostics,
    }
    encoded = json.dumps(output, indent=2, ensure_ascii=False)
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S_%f")
    immutable_path = diag_dir / f"provider_attempts_{timestamp}.json"
    immutable_path.write_text(encoded, encoding="utf-8")
    latest_path = diag_dir / "latest_provider_attempts.json"
    latest_path.write_text(encoded, encoding="utf-8")
    print(f"\\n[diagnostic] Provider attempts written to {immutable_path}")
    return immutable_path
'''
    text = text[:start] + diagnostics_function + text[end:]

    old_diag = '''                symbol_diag = {
                    "symbol": qlib_ticker,
                    "market": reg,
                    "ok": resp.ok,
                    "final_state": "updated" if resp.ok else "failed",
                    "attempts": [
                        {
                            "provider": a.provider,
                            "ok": a.ok,
                            "error": a.error or None,
                        }
                        for a in resp.attempts
                    ],
                }
'''
    new_diag = '''                selected_attempt = resp.attempts[-1] if resp.ok and resp.attempts else None
                symbol_diag = {
                    "symbol": qlib_ticker,
                    "market": reg,
                    "ok": resp.ok,
                    "final_state": "updated" if resp.ok else "failed",
                    "selected_provider": (
                        None if resp.result is None else resp.result.provider
                    ),
                    "selected_provider_symbol": (
                        None if resp.result is None else resp.result.provider_symbol
                    ),
                    "selected_rows": 0 if selected_attempt is None else selected_attempt.rows,
                    "selected_first_date": (
                        None if selected_attempt is None else selected_attempt.first_date
                    ),
                    "selected_last_date": (
                        None if selected_attempt is None else selected_attempt.last_date
                    ),
                    "attempts": [attempt.to_dict() for attempt in resp.attempts],
                }
'''
    text = replace_once(text, old_diag, new_diag, "symbol diagnostics")
    text = replace_once(
        text,
        "    _write_provider_diagnostics(provider_diagnostics, ARTIFACTS_DIR)\n\n    # ------------------------------------------------------------------\n    # 2. Dump to Qlib Binary\n",
        "    provider_attempts_path = _write_provider_diagnostics(\n        provider_diagnostics, ARTIFACTS_DIR\n    )\n\n    # ------------------------------------------------------------------\n    # 2. Dump to Qlib Binary\n",
        "immutable attempts assignment",
    )
    text = replace_once(
        text,
        '''            max_missing_count=args.max_missing_count,
        )
''',
        '''            max_missing_count=args.max_missing_count,
            provider_attempts_path=provider_attempts_path,
        )
''',
        "publish attempts argument",
    )
    text = replace_once(
        text,
        '''    except DataUpdateFailure:
        # Write diagnostics even on failure
        _write_provider_diagnostics(provider_diagnostics, ARTIFACTS_DIR)
        raise
''',
        '''    except DataUpdateFailure:
        raise
''',
        "failure duplicate diagnostics",
    )
    text = replace_once(
        text,
        '''    # Write provider diagnostics
    _write_provider_diagnostics(provider_diagnostics, ARTIFACTS_DIR)

    return snapshot
''',
        '''    return snapshot
''',
        "success duplicate diagnostics",
    )
    path.write_text(text, encoding="utf-8")


def patch_test_fixture() -> None:
    path = Path("tests/test_data_runtime_truth.py")
    text = path.read_text(encoding="utf-8")
    old = '''def _provider(root: Path, value: bytes = b"provider") -> Path:
    provider = root / "provider"
    (provider / "features" / "AAPL").mkdir(parents=True)
    (provider / "features" / "AAPL" / "close.day.bin").write_bytes(value)
    (provider / "calendars").mkdir()
    (provider / "calendars" / "day.txt").write_text("2026-06-19\n", encoding="utf-8")
    return provider
'''
    new = '''def _provider(root: Path, value: bytes = b"provider") -> Path:
    provider = root / "provider"
    for symbol in ("AAPL", "MSFT", "SH600000"):
        (provider / "features" / symbol).mkdir(parents=True)
        (provider / "features" / symbol / "close.day.bin").write_bytes(value)
    (provider / "calendars").mkdir()
    (provider / "calendars" / "day.txt").write_text("2026-06-19\n", encoding="utf-8")
    (provider / "instruments").mkdir()
    (provider / "instruments" / "us.txt").write_text(
        "AAPL\\t2026-06-19\\t2026-06-19\\n"
        "MSFT\\t2026-06-19\\t2026-06-19\\n",
        encoding="utf-8",
    )
    (provider / "instruments" / "cn.txt").write_text(
        "SH600000\\t2026-06-19\\t2026-06-19\\n",
        encoding="utf-8",
    )
    return provider
'''
    text = replace_once(text, old, new, "data runtime provider fixture")
    path.write_text(text, encoding="utf-8")


def patch_ci() -> None:
    path = Path(".github/workflows/ci.yml")
    text = path.read_text(encoding="utf-8")
    old = " tests/test_real_market_research_pipeline.py -q --strict-markers"
    new = (
        " tests/test_real_market_research_pipeline.py"
        " tests/test_provider_evidence.py"
        " tests/test_router_provider_attempts.py"
        " tests/test_data_runtime_truth.py"
        " -q --strict-markers"
    )
    text = replace_once(text, old, new, "CI tests")
    path.write_text(text, encoding="utf-8")


patch_snapshot()
patch_update_data()
patch_test_fixture()
patch_ci()
