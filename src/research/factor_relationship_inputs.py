"""Assemble aligned score, selection and return artifacts for factor relationships."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _verify_output(path: Path) -> tuple[dict[str, Any], str]:
    manifest_path = path.parent / "evidence_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing sibling evidence manifest: {path}")
    manifest = _load_json(manifest_path)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or outputs.get(path.name) != _sha256_file(path):
        raise ValueError(f"artifact hash mismatch: {path.name}")
    return manifest, _sha256_file(manifest_path)


def _pool_membership(pool_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict):
        raise ValueError("pool must be a YAML mapping")
    basket_by_symbol: dict[str, str] = {}
    for basket, meta in pool.get("baskets", {}).items():
        for symbol in meta.get("symbols", []):
            canonical = str(symbol).upper()
            if canonical in basket_by_symbol:
                raise ValueError(f"duplicate pool symbol: {canonical}")
            basket_by_symbol[canonical] = str(basket)
    references = {
        str(symbol).upper(): str(meta.get("provider_symbol", symbol)).upper()
        for symbol, meta in pool.get("references", {}).items()
    }
    return basket_by_symbol, references


def _load_factor_rows(path: Path, factor_keys: set[str]) -> pd.DataFrame:
    payload = _load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("factor score artifact must contain rows")
    frame = pd.DataFrame(rows)
    required = {"date", "symbol", "stable_factor_key", "percentile"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("factor score rows missing columns: " + ", ".join(missing))
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["stable_factor_key"] = frame["stable_factor_key"].astype(str).str.strip()
    frame["score"] = pd.to_numeric(frame["percentile"], errors="coerce")
    if "eligible" in frame:
        frame = frame[frame["eligible"].fillna(False).astype(bool)]
    frame = frame[
        frame["stable_factor_key"].isin(factor_keys) & frame["score"].notna()
    ][["date", "symbol", "stable_factor_key", "score"]]
    if frame.duplicated(["date", "symbol", "stable_factor_key"]).any():
        raise ValueError("factor score rows contain duplicate identities")
    return frame.sort_values(["date", "stable_factor_key", "symbol"])


def _load_basket_rows(
    path: Path,
    *,
    basket_by_symbol: Mapping[str, str],
    basket_factor_fields: Mapping[str, str],
) -> pd.DataFrame:
    payload = _load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("basket score artifact must contain rows")
    frame = pd.DataFrame(rows)
    required = {"date", "basket", *basket_factor_fields.values()}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("basket score rows missing columns: " + ", ".join(missing))
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["basket"] = frame["basket"].astype(str).str.strip()
    if frame.duplicated(["date", "basket"]).any():
        raise ValueError("basket score rows contain duplicate identities")
    members: dict[str, list[str]] = {}
    for symbol, basket in basket_by_symbol.items():
        members.setdefault(basket, []).append(symbol)
    rows_out: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        basket = str(row["basket"])
        for factor_key, source_field in basket_factor_fields.items():
            score = pd.to_numeric(row.get(source_field), errors="coerce")
            if pd.isna(score):
                continue
            for symbol in sorted(members.get(basket, [])):
                rows_out.append(
                    {
                        "date": row["date"],
                        "symbol": symbol,
                        "stable_factor_key": factor_key,
                        "score": float(score),
                    }
                )
    output = pd.DataFrame(rows_out)
    if output.empty:
        raise ValueError("basket score broadcast produced no rows")
    if output.duplicated(["date", "symbol", "stable_factor_key"]).any():
        raise ValueError("broadcast basket scores contain duplicate identities")
    return output.sort_values(["date", "stable_factor_key", "symbol"])


def _load_prices(path: Path, symbols: set[str]) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": "string"})
    required = {"date", "symbol", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("prices missing columns: " + ", ".join(missing))
    frame = frame[["date", "symbol", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame[frame["symbol"].isin(symbols)]
    if frame[["date", "close"]].isna().any().any() or (frame["close"] <= 0).any():
        raise ValueError("prices contain invalid dates or closes")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("prices contain duplicate date-symbol identities")
    missing_symbols = sorted(symbols - set(frame["symbol"].unique()))
    if missing_symbols:
        raise ValueError("prices missing factor-universe symbols: " + ", ".join(missing_symbols))
    return frame.sort_values(["date", "symbol"])


def _selection_rows(
    scores: pd.DataFrame,
    *,
    basket_by_symbol: Mapping[str, str],
    security_factor_keys: set[str],
    basket_factor_keys: set[str],
    security_top_fraction: float,
    basket_top_fraction: float,
) -> pd.DataFrame:
    frame = scores.copy()
    frame["basket"] = frame["symbol"].map(basket_by_symbol)
    if frame["basket"].isna().any():
        raise ValueError("factor scores contain symbols outside the frozen pool")
    rows: list[dict[str, Any]] = []
    for (day, factor), factor_frame in frame.groupby(
        ["date", "stable_factor_key"], sort=True
    ):
        selected_symbols: set[str] = set()
        if factor in security_factor_keys:
            threshold = 1.0 - security_top_fraction
            for _, basket_frame in factor_frame.groupby("basket", sort=True):
                ranked = basket_frame.copy()
                ranked["rank_percentile"] = ranked["score"].rank(
                    method="average", pct=True
                )
                selected_symbols.update(
                    ranked.loc[
                        ranked["rank_percentile"] >= threshold, "symbol"
                    ].astype(str)
                )
        elif factor in basket_factor_keys:
            basket_scores = factor_frame.groupby("basket", sort=True)["score"].first()
            ranked_baskets = basket_scores.rank(method="average", pct=True)
            selected_baskets = set(
                ranked_baskets[
                    ranked_baskets >= 1.0 - basket_top_fraction
                ].index.astype(str)
            )
            selected_symbols.update(
                factor_frame.loc[
                    factor_frame["basket"].isin(selected_baskets), "symbol"
                ].astype(str)
            )
        else:
            raise ValueError(f"factor selection scope is unknown: {factor}")
        for symbol in sorted(factor_frame["symbol"].astype(str).unique()):
            rows.append(
                {
                    "date": day,
                    "stable_factor_key": factor,
                    "symbol": symbol,
                    "selected": symbol in selected_symbols,
                }
            )
    output = pd.DataFrame(rows)
    if output.empty:
        raise ValueError("factor selections produced no rows")
    return output.sort_values(["date", "stable_factor_key", "symbol"])


def _factor_returns(
    selections: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    rows: list[dict[str, Any]] = []
    for factor, factor_frame in selections.groupby("stable_factor_key", sort=True):
        dates = sorted(factor_frame["date"].unique())
        for current, following in zip(dates, dates[1:]):
            selected = set(
                factor_frame.loc[
                    (factor_frame["date"] == current) & factor_frame["selected"],
                    "symbol",
                ].astype(str)
            )
            if not selected:
                factor_return = 0.0
            else:
                if current not in close.index or following not in close.index:
                    raise ValueError("factor evaluation dates are missing from price history")
                current_prices = close.loc[current, sorted(selected)]
                next_prices = close.loc[following, sorted(selected)]
                available = current_prices.notna() & next_prices.notna()
                if not bool(available.all()):
                    missing = list(current_prices.index[~available])
                    raise ValueError(
                        f"selected factor holdings have missing returns: {factor}: {missing}"
                    )
                factor_return = float((next_prices / current_prices - 1.0).mean())
            rows.append(
                {
                    "date": pd.Timestamp(current),
                    "stable_factor_key": factor,
                    "return": factor_return,
                }
            )
    output = pd.DataFrame(rows)
    if output.empty:
        raise ValueError("factor return construction produced no rows")
    return output.sort_values(["date", "stable_factor_key"])


def build_factor_relationship_inputs(
    *,
    pipeline_contract_path: str | Path,
    multifactor_contract_path: str | Path,
    fundamental_scores_path: str | Path,
    basket_scores_path: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build hash-bound relationship inputs for the four frozen factors."""

    pipeline_path = Path(pipeline_contract_path).resolve()
    pipeline = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
    multifactor_path = Path(multifactor_contract_path).resolve()
    multifactor = yaml.safe_load(multifactor_path.read_text(encoding="utf-8"))
    if not isinstance(pipeline, dict) or not isinstance(multifactor, dict):
        raise ValueError("pipeline and multifactor contracts must be mappings")
    if pipeline.get("status") != "frozen_diagnostic_pipeline":
        raise ValueError("decision pipeline is not frozen")
    root = pipeline_path.parents[2]
    pool_path = root / str(pipeline["pool_spec"])
    basket_by_symbol, _ = _pool_membership(pool_path)
    configured_keys = [
        str(value) for value in pipeline["relationship_inputs"]["factor_keys"]
    ]
    multifactor_rows = {
        str(row["stable_factor_key"]): row for row in multifactor["factors"]
    }
    if set(configured_keys) != set(multifactor_rows):
        raise ValueError("relationship input factors differ from the multifactor contract")
    security_keys = {
        key for key, row in multifactor_rows.items() if str(row["scope"]) == "security"
    }
    basket_fields = {
        key: str(row["source_percentile_field"])
        for key, row in multifactor_rows.items()
        if str(row["scope"]) == "basket"
    }
    fundamental_path = Path(fundamental_scores_path).resolve()
    basket_path = Path(basket_scores_path).resolve()
    prices_path = Path(prices_csv).resolve()
    fundamental_manifest, fundamental_manifest_hash = _verify_output(fundamental_path)
    basket_manifest, basket_manifest_hash = _verify_output(basket_path)
    security_scores = _load_factor_rows(fundamental_path, security_keys)
    basket_scores = _load_basket_rows(
        basket_path,
        basket_by_symbol=basket_by_symbol,
        basket_factor_fields=basket_fields,
    )
    scores = pd.concat([security_scores, basket_scores], ignore_index=True).sort_values(
        ["date", "stable_factor_key", "symbol"]
    )
    if set(scores["stable_factor_key"].unique()) != set(configured_keys):
        raise ValueError("not all configured factors produced score rows")
    prices = _load_prices(prices_path, set(basket_by_symbol))
    inputs = pipeline["relationship_inputs"]
    selections = _selection_rows(
        scores,
        basket_by_symbol=basket_by_symbol,
        security_factor_keys=security_keys,
        basket_factor_keys=set(basket_fields),
        security_top_fraction=float(inputs["security_factor_selection_top_fraction"]),
        basket_top_fraction=float(inputs["basket_factor_selection_top_fraction"]),
    )
    returns = _factor_returns(selections, prices)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "scores": output / "scores.csv",
        "returns": output / "returns.csv",
        "selections": output / "selections.csv",
    }
    scores.assign(date=scores["date"].dt.date).to_csv(paths["scores"], index=False)
    returns.assign(date=returns["date"].dt.date).to_csv(paths["returns"], index=False)
    selections.assign(date=selections["date"].dt.date).to_csv(
        paths["selections"], index=False
    )
    start_date = scores["date"].min().date().isoformat()
    end_date = scores["date"].max().date().isoformat()
    upstream_identity = _canonical_hash(
        {
            "fundamental_manifest": fundamental_manifest.get(
                "manifest_identity_sha256"
            ),
            "basket_manifest": basket_manifest.get("manifest_identity_sha256"),
            "prices": _sha256_file(prices_path),
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "scope": {
            "market": "us",
            "universe_version": "us_small_pool_v1",
            "benchmark": "QQQ",
            "start_date": start_date,
            "end_date": end_date,
            "provider_identity": _sha256_file(prices_path),
            "evidence_manifest_hash": upstream_identity,
        },
        "artifacts": {
            kind: {"path": path.name, "sha256": _sha256_file(path)}
            for kind, path in paths.items()
        },
        "upstream": {
            "fundamental_manifest_sha256": fundamental_manifest_hash,
            "basket_manifest_sha256": basket_manifest_hash,
            "prices_sha256": _sha256_file(prices_path),
        },
        "construction": {
            "security_top_fraction": float(
                inputs["security_factor_selection_top_fraction"]
            ),
            "basket_top_fraction": float(
                inputs["basket_factor_selection_top_fraction"]
            ),
            "return_measure": inputs["return_measure"],
            "transaction_cost_applied": False,
        },
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(output / "input_manifest.json", manifest)
    decision = {
        "schema_version": "1.0",
        "decision": "factor_relationship_inputs_ready",
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "factor_count": len(configured_keys),
        "score_row_count": len(scores),
        "selection_row_count": len(selections),
        "return_row_count": len(returns),
        "start_date": start_date,
        "end_date": end_date,
    }
    _write_json(output / "decision.json", decision)
    return decision
