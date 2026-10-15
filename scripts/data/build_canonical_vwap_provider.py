"""Build canonical selected-pool VWAP providers and governed Alpha158 panels."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.build_market_providers import build_market_provider
from src.data.adapters.alpaca_adapter import AlpacaAdapter
from src.data.adapters.base import FetchRequest
from src.data.adapters.polygon_adapter import PolygonAdapter
from src.data.canonical_vwap import (
    CanonicalVwapError,
    derive_adjusted_vwap,
    write_source_role_manifest,
)
from src.data.model_data_bundle import ComponentSpec, build_model_data_bundle
from src.data.listing_lifecycle import REGISTRY_PATH, load_terminal_listings
from src.factors.governance import build_factor_governance_manifest
from src.factors.reusable_panel import build_reusable_alpha158_panel


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CanonicalVwapError(f"YAML must be a mapping: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _us_feed(symbol: str, source_policy: dict[str, Any]) -> str:
    default_feed = str(source_policy.get("feed", "sip")).strip().lower()
    overrides = {
        str(key).strip().upper(): str(value).strip().lower()
        for key, value in dict(source_policy.get("symbol_feed_overrides", {})).items()
    }
    return overrides.get(str(symbol).strip().upper(), default_feed)


def _fetch_cn_pair(symbol: str, *, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
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
    """Reuse byte-verified sources for the exact request, including session gaps."""

    if not raw_path.is_file() or not qfq_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if (
        not isinstance(metadata, dict)
        or metadata.get("raw_sha256") != hashlib.sha256(raw_path.read_bytes()).hexdigest()
        or metadata.get("qfq_sha256") != hashlib.sha256(qfq_path.read_bytes()).hexdigest()
        or metadata.get("research_only") is not True
        or metadata.get("trade_ready") is not False
        or metadata.get("semantic_validation") != "passed"
        or metadata.get("symbol") != symbol
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
        or raw_dates.duplicated().any()
        or qfq_dates.duplicated().any()
    ):
        return None
    raw = raw.loc[raw_dates.between(requested_start, requested_end)].copy()
    qfq = qfq.loc[qfq_dates.between(requested_start, requested_end)].copy()
    return raw, qfq


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_us(
    *,
    pool_path: Path,
    start: str,
    cutoff: str,
    output_root: Path,
    fixture_dir: Path | None,
    source_policy: dict[str, Any] | None = None,
    recent_research: bool = False,
) -> dict[str, Any]:
    pool_id, symbols = _pool_symbols(pool_path, "us")
    source_root = output_root / "source_csv"
    provider = output_root / "provider"
    panel = output_root / "alpha158"
    model_data = output_root / "model_data"
    frontend = output_root / "frontend"
    source_root.mkdir(parents=True, exist_ok=True)
    policy = dict(source_policy or {})
    if recent_research:
        frozen = _load_yaml(Path("configs/data/alpha158_us87_recent_research_v1.yaml"))
        if policy != frozen["markets"]["us"]["canonical_vwap_source"] or start != frozen["history"]["requested_start"] or pool_path.resolve() != Path(frozen["markets"]["us"]["pool_spec"]).resolve():
            raise CanonicalVwapError("recent panel must use its exact frozen source, pool and window")
    feed_overrides = {
        str(symbol).strip().upper(): str(feed).strip().lower()
        for symbol, feed in dict(policy.get("symbol_feed_overrides", {})).items()
    }
    unknown_overrides = sorted(set(feed_overrides).difference(symbols))
    if unknown_overrides:
        raise CanonicalVwapError(
            f"US VWAP feed overrides are outside the selected pool: {unknown_overrides}"
        )
    adapters: dict[str, Any] = {}
    diagnostics: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    terminal_listings = load_terminal_listings(Path.cwd(), market="us")
    for symbol in symbols:
        try:
            terminal = terminal_listings.get(symbol)
            symbol_cutoff = min(cutoff, terminal.terminal_date) if terminal else cutoff
            feed = _us_feed(symbol, policy)
            provider_name = dict(policy.get("provider_overrides", {})).get(symbol, "alpaca") if recent_research else "alpaca"
            if fixture_dir is None:
                key = f"{provider_name}:{feed}"
                if key not in adapters:
                    adapters[key] = PolygonAdapter() if provider_name == "polygon" else AlpacaAdapter(feed=feed, adjustment="split" if recent_research else "all")
                adapter = adapters[key]
                result = adapter.fetch_daily_bars(
                    FetchRequest(symbol=symbol, market="us", start=start, end=symbol_cutoff)
                )
                frame = result.df.copy()
                metadata = dict(frame.attrs.get("provider_metadata", {}))
                source_mode = f"{provider_name}_{feed}_live"
            else:
                frame = pd.read_csv(fixture_dir / f"{symbol}.csv")
                metadata = {"fixture": True}
                source_mode = f"fixture_{provider_name}_{feed}"
            required = {"date", "open", "high", "low", "close", "vwap", "volume"}
            missing = sorted(required.difference(frame.columns))
            if missing:
                raise CanonicalVwapError(f"{symbol}: Alpaca bars missing columns: {missing}")
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            if frame["date"].isna().any():
                raise CanonicalVwapError(f"{symbol}: source contains invalid dates")
            outside_window_rows = int((~frame["date"].between(start, symbol_cutoff)).sum())
            frame = frame.loc[frame["date"].between(start, symbol_cutoff)].copy()
            for column in required.difference({"date"}):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame[list(required)].isna().any().any() or frame.empty:
                raise CanonicalVwapError(f"{symbol}: Alpaca bars contain missing values")
            if (frame[["open", "high", "low", "close", "vwap", "volume"]] <= 0).any().any():
                raise CanonicalVwapError(f"{symbol}: Alpaca bars must be positive")
            envelope_distance = pd.concat(
                [
                    (frame["low"] - frame["vwap"]).clip(lower=0.0),
                    (frame["vwap"] - frame["high"]).clip(lower=0.0),
                ],
                axis=1,
            ).max(axis=1)
            if (envelope_distance > 0.005).any():
                raise CanonicalVwapError(
                    f"{symbol}: reported VWAP violates OHLC envelope; "
                    f"sessions={int((envelope_distance > 0.005).sum())}, "
                    f"max_distance={float(envelope_distance.max()):.8f}"
                )
            frame["amount"] = frame["vwap"] * frame["volume"]
            frame["factor"] = 1.0
            frame = frame.sort_values("date").drop_duplicates("date", keep="last")
            frame.to_csv(source_root / f"{symbol}.csv", index=False)
            diagnostics.append(
                {
                    "symbol": symbol,
                    "rows": len(frame),
                    "first_date": frame["date"].min().date().isoformat(),
                    "last_date": frame["date"].max().date().isoformat(),
                    "vwap_semantics": "reported_vwap",
                    "adjustment_method": "split_adjusted_same_record_daily_bars" if recent_research else "alpaca_sip_adjustment_all_daily_bars",
                    "source_mode": source_mode,
                    "feed": feed,
                    "provider": provider_name,
                    "provider_metadata": metadata,
                    "governed_terminal_date": terminal.terminal_date if terminal else None,
                    "effective_source_cutoff": symbol_cutoff,
                    "outside_governed_window_rows_excluded": outside_window_rows,
                    "rounded_envelope_tolerance_sessions": int((envelope_distance > 1e-8).sum()),
                    "research_only": True,
                    "trade_ready": False,
                }
            )
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

    audit = {
        "schema_version": "1.0",
        "market": "us",
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "expected_symbol_count": len(symbols),
        "ready_symbol_count": len(diagnostics),
        "failed_symbol_count": len(failures),
        "failures": failures,
        "symbols": diagnostics,
        "source_provider": "alpaca_sip_and_polygon_otc" if recent_research else "alpaca_market_data",
        "source_feeds": sorted({row["feed"] for row in diagnostics}),
        "same_record_ohlcv_vwap": True,
        "lifecycle_registry_sha256": _sha256(Path(REGISTRY_PATH)),
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_root / "vwap_audit.json", audit)
    if failures:
        raise CanonicalVwapError(
            "canonical US VWAP build is incomplete: " + ", ".join(row["symbol"] for row in failures)
        )

    provider_manifest = build_market_provider(
        csv_dir=source_root,
        provider_dir=provider,
        market="us",
        include_fields="open,high,low,close,vwap,volume",
    )
    provider_manifest_path = provider / "provider_manifest.json"
    source_role = write_source_role_manifest(
        provider,
        provider_manifest=provider_manifest,
        provider_manifest_path=provider_manifest_path,
        source_providers=["alpaca_market_data", "polygon"] if recent_research else ["alpaca_market_data"],
        market="us",
        vwap_ready=True,
        field_semantics={
            "open": "split_adjusted_same_record" if recent_research else "alpaca_adjusted_all_daily_bar",
            "high": "split_adjusted_same_record" if recent_research else "alpaca_adjusted_all_daily_bar",
            "low": "split_adjusted_same_record" if recent_research else "alpaca_adjusted_all_daily_bar",
            "close": "split_adjusted_same_record" if recent_research else "alpaca_adjusted_all_daily_bar",
            "vwap": "reported_vwap",
            "volume": "split_adjusted_reported_volume" if recent_research else "alpaca_adjusted_all_daily_bar_volume",
            "amount": "derived_reported_vwap_times_reported_volume",
            "factor": "identity_within_adjusted_aggregate_basis",
        },
    )
    source_role_path = provider / "source_role_manifest.json"
    panel_manifest = build_reusable_alpha158_panel(
        root=Path.cwd(),
        contract_path=Path("configs/data/alpha158_us87_recent_research_v1.yaml" if recent_research else "configs/data/alpha158_panel_v1.yaml"),
        provider_uri=provider,
        market="us",
        start=start,
        cutoff=cutoff,
        output_root=panel,
    )
    if recent_research:
        result = {
            "scope": "independent_recent_us87_panel_validation",
            "status": panel_manifest.get("status"), "evidence_cutoff": cutoff,
            "requested_start": start, "pool_id": pool_id,
            "expected_symbol_count": len(symbols), "factor_panel_manifest": panel_manifest,
            "contract_sha256": _sha256(Path("configs/data/alpha158_us87_recent_research_v1.yaml")),
            "source_audit_sha256": _sha256(output_root / "vwap_audit.json"),
            "selected_pool_registry_sha256": _sha256(Path("configs/pools/selected_pool_registry_v1.yaml")),
            "lifecycle_registry_sha256": _sha256(Path(REGISTRY_PATH)),
            "reference_registry_sha256": _sha256(Path("configs/pools/reference_instrument_registry_v1.yaml")),
            "governed_source_registry_sha256": _sha256(Path("configs/data/formal_model_data_sources_v1.yaml")),
            "model_data_registered": False, "original_training_gate_satisfied": False,
            "research_only": True, "trade_ready": False,
        }
        _write_json(output_root / "recent_research_manifest.json", result)
        return result
    price_manifest = _price_component(
        pool_id=pool_id,
        market="us",
        cutoff=cutoff,
        diagnostics=diagnostics,
        providers=["alpaca_market_data"],
        provider_identity_sha256=provider_manifest.get("provider_identity_sha256"),
        provider_manifest_path=provider_manifest_path,
        source_role_manifest_path=source_role_path,
        price_basis="alpaca_adjusted_all_daily_bar_with_governed_feed_mapping",
        vwap_basis="reported_vwap_same_aggregate_record",
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
                market="us",
            ),
            ComponentSpec(
                component_id="factors.qlib_alpha158.panel.us.v1",
                component_kind="factor_panel",
                manifest_path=panel_manifest_path,
                market="us",
            ),
        ],
        output_root=model_data,
        evidence_cutoff=cutoff,
        frontend_data_dir=frontend,
    )
    factor_governance = build_factor_governance_manifest(
        root=Path.cwd(),
        market="us",
        pool_id=pool_id,
        evidence_cutoff=cutoff,
        factor_panel_manifest=panel_manifest,
        model_data_manifest=model_manifest,
        output_path=output_root / "factor_governance_manifest.json",
    )
    result = {
        "schema_version": "1.0",
        "market": "us",
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "vwap_audit": audit,
        "provider_manifest": provider_manifest,
        "source_role_manifest": source_role,
        "price_component_manifest": price_manifest,
        "factor_panel_manifest": panel_manifest,
        "model_data_manifest": model_manifest,
        "factor_governance_manifest": factor_governance,
        "status": panel_manifest.get("status"),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_root / "canonical_vwap_bundle.json", result)
    return result


def _price_component(
    *,
    pool_id: str,
    market: str,
    cutoff: str,
    diagnostics: list[dict[str, Any]],
    providers: list[str],
    provider_identity_sha256: str | None,
    provider_manifest_path: Path,
    source_role_manifest_path: Path,
    price_basis: str,
    vwap_basis: str,
) -> dict[str, Any]:
    expected = len(diagnostics)
    return {
        "schema_version": "1.0",
        "component_id": f"prices.{pool_id}",
        "component_kind": "selected_pool_prices",
        "status": "ready",
        "market": market,
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
        "providers": providers,
        "provider_identity_sha256": provider_identity_sha256,
        "professional_source_ready": False,
        "research_only": True,
        "trade_ready": False,
        "details": {
            "provider_manifest_path": str(provider_manifest_path),
            "source_role_manifest_path": str(source_role_manifest_path),
            "price_basis": price_basis,
            "volume_basis": "reported_shares",
            "vwap_basis": vwap_basis,
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
            # Preserve new source evidence even when semantic validation fails;
            # an exact cache hit retains the already verified bytes unchanged.
            if cache_mode != "exact_cutoff_reuse":
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
                        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        "qfq_sha256": hashlib.sha256(qfq_path.read_bytes()).hexdigest(),
                        "semantic_validation": "pending",
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
            if cache_mode != "exact_cutoff_reuse":
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["semantic_validation"] = "passed"
                _write_json(metadata_path, metadata)
            evidence["cache_mode"] = cache_mode
            frame.to_csv(source_root / f"{symbol}.csv", index=False)
            diagnostics.append(evidence)
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

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
            "canonical CN VWAP build is incomplete: " + ", ".join(row["symbol"] for row in failures)
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
    panel_manifest = build_reusable_alpha158_panel(
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
        market="cn",
        cutoff=cutoff,
        diagnostics=diagnostics,
        providers=["akshare_sina"],
        provider_identity_sha256=provider_manifest.get("provider_identity_sha256"),
        provider_manifest_path=provider_manifest_path,
        source_role_manifest_path=source_role_path,
        price_basis="same_source_qfq_adjusted",
        vwap_basis="reported_turnover_divided_by_reported_volume",
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
    factor_governance = build_factor_governance_manifest(
        root=Path.cwd(),
        market="cn",
        pool_id=pool_id,
        evidence_cutoff=cutoff,
        factor_panel_manifest=panel_manifest,
        model_data_manifest=model_manifest,
        output_path=output_root / "factor_governance_manifest.json",
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
        "factor_governance_manifest": factor_governance,
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
    parser.add_argument("--recent-us-research", action="store_true")
    args = parser.parse_args()
    if args.recent_us_research and (args.market != "us" or args.start != "2026-01-01"):
        parser.error("recent US research requires market=us and start=2026-01-01")
    contract = _load_yaml(Path("configs/data/alpha158_us87_recent_research_v1.yaml" if args.recent_us_research else "configs/data/alpha158_panel_v1.yaml"))
    market_contract = contract["markets"][args.market]
    pool_path = Path(str(market_contract["pool_spec"]))
    if args.market == "us":
        result = build_us(
            pool_path=pool_path,
            start=args.start,
            cutoff=args.cutoff,
            output_root=args.output_root,
            fixture_dir=args.fixture_dir,
            source_policy=dict(market_contract["canonical_vwap_source"]),
            recent_research=args.recent_us_research,
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
