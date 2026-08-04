"""Build canonical selected-pool VWAP providers and governed Alpha158 panels."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.build_market_providers import build_market_provider
from src.data.canonical_vwap import (
    CanonicalVwapError,
    derive_adjusted_vwap,
    write_source_role_manifest,
)
from src.data.model_data_bundle import ComponentSpec, build_model_data_bundle
from src.factors.panel import build_alpha158_panel


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CanonicalVwapError(f"YAML must be a mapping: {path}")
    return payload


def _pool_symbols(path: Path, market: str) -> tuple[str, list[str]]:
    payload = _load_yaml(path)
    if str(payload.get("market", "")).lower() != market:
        raise CanonicalVwapError("selected-pool market mismatch")
    symbols = [str(value).strip().upper() for value in payload.get("symbols", [])]
    expected = int(payload.get("candidate_count", 0))
    if len(symbols) != expected or len(set(symbols)) != expected:
        raise CanonicalVwapError("selected-pool identity is not exact")
    return str(payload.get("pool_id", "")), symbols


def _provider_symbol(symbol: str) -> str:
    if symbol.startswith(("60", "68")):
        return f"sh{symbol}"
    if symbol.startswith(("4", "8", "92")):
        return f"bj{symbol}"
    return f"sz{symbol}"


def _fetch_cn_pair(
    symbol: str, *, start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        import akshare as ak
    except Exception as exc:
        raise CanonicalVwapError(f"akshare import failed: {exc}") from exc
    provider_symbol = _provider_symbol(symbol)
    arguments = {
        "symbol": provider_symbol,
        "start_date": start.replace("-", ""),
        "end_date": end.replace("-", ""),
    }
    try:
        raw = ak.stock_zh_a_daily(**arguments, adjust="")
        adjusted = ak.stock_zh_a_daily(**arguments, adjust="qfq")
    except Exception as exc:
        raise CanonicalVwapError(
            f"AKShare Sina raw/qfq fetch failed for {provider_symbol}: {exc}"
        ) from exc
    if raw is None or adjusted is None:
        raise CanonicalVwapError(f"empty AKShare Sina pair for {provider_symbol}")
    return raw.copy(), adjusted.copy()


def _cached_cn_pair(
    *,
    symbol: str,
    start: str,
    end: str,
    raw_path: Path,
    qfq_path: Path,
    metadata_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Return an exact-cutoff cached source pair when its dates are complete."""

    if (
        not raw_path.is_file()
        or not qfq_path.is_file()
        or not metadata_path.is_file()
    ):
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if (
        metadata.get("symbol") != symbol
        or metadata.get("start") != start
        or metadata.get("cutoff") != end
        or metadata.get("source_provider") != "akshare_sina"
    ):
        return None
    raw = pd.read_csv(raw_path)
    qfq = pd.read_csv(qfq_path)
    if "date" not in raw or "date" not in qfq or raw.empty or qfq.empty:
        return None
    raw_dates = pd.to_datetime(raw["date"], errors="coerce")
    qfq_dates = pd.to_datetime(qfq["date"], errors="coerce")
    requested_start = pd.Timestamp(start)
    requested_end = pd.Timestamp(end)
    if (
        raw_dates.isna().any()
        or qfq_dates.isna().any()
        or raw_dates.min() > requested_start
        or qfq_dates.min() > requested_start
        or raw_dates.max() < requested_end
        or qfq_dates.max() < requested_end
    ):
        return None
    raw = raw.loc[raw_dates.between(requested_start, requested_end)].copy()
    qfq = qfq.loc[qfq_dates.between(requested_start, requested_end)].copy()
    return raw, qfq


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_us_blocker(
    *,
    pool_id: str,
    symbols: list[str],
    cutoff: str,
    output_root: Path,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    blocker = {
        "schema_version": "1.0",
        "component_id": "factors.qlib_alpha158.panel.us.v1",
        "component_kind": "factor_panel",
        "status": "blocked",
        "market": "us",
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "expected_symbol_count": len(symbols),
        "ready_symbol_count": 0,
        "coverage_ratio": 0.0,
        "missing_symbols": [],
        "invalid_symbols": symbols,
        "quarantined_symbols": [],
        "providers": [],
        "blocker": (
            "Current canonical US provider has synthetic amount and no provider-reported "
            "daily VWAP or turnover. Validation-only Tiingo/Polygon data cannot satisfy "
            "canonical Alpha158 fields."
        ),
        "required_resolution": (
            "Approve and implement a canonical US source with reported VWAP or reported "
            "turnover and share volume on the same adjusted-price basis."
        ),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_root / "factor_panel_manifest.json", blocker)
    return blocker


def _price_component(
    *,
    pool_id: str,
    cutoff: str,
    diagnostics: list[dict[str, Any]],
    provider_manifest_path: Path,
    source_role_manifest_path: Path,
) -> dict[str, Any]:
    expected = len(diagnostics)
    return {
        "schema_version": "1.0",
        "component_id": f"prices.{pool_id}",
        "component_kind": "selected_pool_prices",
        "status": "ready",
        "market": "cn",
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "first_date": min(row["first_date"] for row in diagnostics),
        "last_date": min(row["last_date"] for row in diagnostics),
        "expected_symbol_count": expected,
        "ready_symbol_count": expected,
        "coverage_ratio": 1.0,
        "missing_symbols": [],
        "invalid_symbols": [],
        "quarantined_symbols": [],
        "providers": ["akshare_sina"],
        "professional_source_ready": False,
        "research_only": True,
        "trade_ready": False,
        "details": {
            "provider_manifest_path": str(provider_manifest_path),
            "source_role_manifest_path": str(source_role_manifest_path),
            "price_basis": "same_source_qfq_adjusted",
            "volume_basis": "reported_shares",
            "vwap_basis": "reported_turnover_divided_by_reported_volume",
        },
    }


def build_cn(
    *,
    pool_path: Path,
    start: str,
    cutoff: str,
    output_root: Path,
    fixture_dir: Path | None,
) -> dict[str, Any]:
    pool_id, symbols = _pool_symbols(pool_path, "cn")
    source_root = output_root / "source_csv"
    raw_cache = output_root / "raw"
    qfq_cache = output_root / "qfq"
    cache_metadata = output_root / "cache_metadata"
    provider = output_root / "provider"
    panel = output_root / "alpha158"
    model_data = output_root / "model_data"
    frontend = output_root / "frontend"
    source_root.mkdir(parents=True, exist_ok=True)
    raw_cache.mkdir(parents=True, exist_ok=True)
    qfq_cache.mkdir(parents=True, exist_ok=True)
    cache_metadata.mkdir(parents=True, exist_ok=True)
    diagnostics: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for symbol in symbols:
        try:
            raw_path = raw_cache / f"{symbol}.csv"
            qfq_path = qfq_cache / f"{symbol}.csv"
            metadata_path = cache_metadata / f"{symbol}.json"
            if fixture_dir is None:
                cached = _cached_cn_pair(
                    symbol=symbol,
                    start=start,
                    end=cutoff,
                    raw_path=raw_path,
                    qfq_path=qfq_path,
                    metadata_path=metadata_path,
                )
                if cached is None:
                    raw, qfq = _fetch_cn_pair(symbol, start=start, end=cutoff)
                    cache_mode = "source_fetch"
                else:
                    raw, qfq = cached
                    cache_mode = "exact_cutoff_reuse"
            else:
                raw = pd.read_csv(fixture_dir / f"{symbol}.raw.csv")
                qfq = pd.read_csv(fixture_dir / f"{symbol}.qfq.csv")
                cache_mode = "fixture"
            # Preserve source evidence even when semantic validation fails.
            raw.to_csv(raw_path, index=False)
            qfq.to_csv(qfq_path, index=False)
            _write_json(
                metadata_path,
                {
                    "schema_version": "1.0",
                    "symbol": symbol,
                    "start": start,
                    "cutoff": cutoff,
                    "source_provider": "akshare_sina",
                    "raw_path": str(raw_path),
                    "qfq_path": str(qfq_path),
                    "research_only": True,
                    "trade_ready": False,
                },
            )
            frame, evidence = derive_adjusted_vwap(
                raw,
                qfq,
                symbol=symbol,
                amount_is_reported=True,
                volume_unit="shares",
                amount_unit="CNY",
            )
            evidence["cache_mode"] = cache_mode
            frame.to_csv(source_root / f"{symbol}.csv", index=False)
            diagnostics.append(evidence)
        except Exception as exc:
            failures.append(
                {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}
            )

    audit = {
        "schema_version": "1.0",
        "market": "cn",
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "expected_symbol_count": len(symbols),
        "ready_symbol_count": len(diagnostics),
        "failed_symbol_count": len(failures),
        "failures": failures,
        "symbols": diagnostics,
        "source_provider": "akshare_sina",
        "source_family": "sina_finance",
        "raw_and_qfq_fetched_from_same_endpoint": True,
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_root / "vwap_audit.json", audit)
    if failures:
        raise CanonicalVwapError(
            "canonical CN VWAP build is incomplete: "
            + ", ".join(row["symbol"] for row in failures)
        )

    provider_manifest = build_market_provider(
        csv_dir=source_root,
        provider_dir=provider,
        market="cn",
        include_fields="open,high,low,close,vwap,volume",
    )
    provider_manifest_path = provider / "provider_manifest.json"
    source_role = write_source_role_manifest(
        provider,
        provider_manifest=provider_manifest,
        provider_manifest_path=provider_manifest_path,
        source_providers=["akshare_sina"],
        market="cn",
        vwap_ready=True,
    )
    source_role_path = provider / "source_role_manifest.json"
    panel_manifest = build_alpha158_panel(
        root=Path.cwd(),
        contract_path=Path("configs/data/alpha158_panel_v1.yaml"),
        provider_uri=provider,
        market="cn",
        start=start,
        cutoff=cutoff,
        output_root=panel,
    )
    price_manifest = _price_component(
        pool_id=pool_id,
        cutoff=cutoff,
        diagnostics=diagnostics,
        provider_manifest_path=provider_manifest_path,
        source_role_manifest_path=source_role_path,
    )
    price_manifest_path = output_root / "price_component_manifest.json"
    _write_json(price_manifest_path, price_manifest)
    panel_manifest_path = panel / "factor_panel_manifest.json"
    model_manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=Path("configs/data_contracts/model_data_bundle_v1.yaml"),
        component_specs=[
            ComponentSpec(
                component_id=f"prices.{pool_id}",
                component_kind="selected_pool_prices",
                manifest_path=price_manifest_path,
                market="cn",
            ),
            ComponentSpec(
                component_id="factors.qlib_alpha158.panel.cn.v1",
                component_kind="factor_panel",
                manifest_path=panel_manifest_path,
                market="cn",
            ),
        ],
        output_root=model_data,
        evidence_cutoff=cutoff,
        frontend_data_dir=frontend,
    )
    result = {
        "schema_version": "1.0",
        "market": "cn",
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "vwap_audit": audit,
        "provider_manifest": provider_manifest,
        "source_role_manifest": source_role,
        "price_component_manifest": price_manifest,
        "factor_panel_manifest": panel_manifest,
        "model_data_manifest": model_manifest,
        "status": panel_manifest.get("status"),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_root / "canonical_vwap_bundle.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, default=None)
    args = parser.parse_args()
    contract = _load_yaml(Path("configs/data/alpha158_panel_v1.yaml"))
    market_contract = contract["markets"][args.market]
    pool_path = Path(str(market_contract["pool_spec"]))
    if args.market == "us":
        pool_id, symbols = _pool_symbols(pool_path, "us")
        result = _write_us_blocker(
            pool_id=pool_id,
            symbols=symbols,
            cutoff=args.cutoff,
            output_root=args.output_root,
        )
    else:
        result = build_cn(
            pool_path=pool_path,
            start=args.start,
            cutoff=args.cutoff,
            output_root=args.output_root,
            fixture_dir=args.fixture_dir,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in {"ready", "partial", "blocked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
