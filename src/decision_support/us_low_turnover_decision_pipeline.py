"""Governed one-command US low-turnover multifactor decision pipeline."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.decision_support.prospective_shadow_cycle import run_prospective_shadow_cycle
from src.research.factor_history_backfill import backfill_history_batch
from src.research.factor_knowledge_registry import FactorKnowledgeRegistry
from src.research.factor_relationship_map import build_factor_relationship_map
from src.research.fundamental_acceleration import run_fundamental_acceleration
from src.research.hierarchical_pool_rotation import run_hierarchical_pool_rotation
from src.research.low_turnover_multifactor_pipeline import (
    run_low_turnover_multifactor_pipeline,
)
from src.research.sec_companyfacts_fundamentals import (
    SecClientProtocol,
    build_sec_companyfacts_fundamentals,
)

FACTOR_KEYS = (
    "revenue_growth_acceleration",
    "gross_margin_yoy_change",
    "basket_relative_momentum_63",
    "basket_drawdown_from_63d_high",
)
FUNDAMENTAL_FACTOR_KEYS = FACTOR_KEYS[:2]
BASKET_FACTOR_FIELDS = {
    "basket_relative_momentum_63": (
        "median_relative_momentum_63_vs_benchmark_percentile"
    ),
    "basket_drawdown_from_63d_high": (
        "median_drawdown_from_63d_high_percentile"
    ),
}


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _repository_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise ValueError(f"unable to resolve repository root from {path}")


def _pool_membership(pool_path: Path) -> tuple[dict[str, str], list[str]]:
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict) or pool.get("pool_id") != "us_small_pool_v1":
        raise ValueError("US decision pipeline requires frozen us_small_pool_v1")
    basket_by_symbol = {
        str(symbol).upper(): str(basket)
        for basket, meta in pool["baskets"].items()
        for symbol in meta["symbols"]
    }
    references = [str(symbol).upper() for symbol in pool.get("references", {})]
    return basket_by_symbol, references


def _verify_prices(
    prices_csv: Path,
    *,
    required_symbols: set[str],
    as_of: date,
) -> pd.DataFrame:
    frame = pd.read_csv(prices_csv, dtype={"symbol": "string"})
    required_columns = {"date", "symbol", "open", "high", "low", "close"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ValueError("prices CSV missing columns: " + ", ".join(missing))
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    if frame["date"].isna().any() or (frame["symbol"] == "").any():
        raise ValueError("prices CSV contains invalid date or symbol identities")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("prices CSV contains duplicate date-symbol identities")
    last_date = frame["date"].max().date()
    if last_date != as_of:
        raise ValueError(
            f"prices CSV must end exactly on {as_of.isoformat()}, observed {last_date}"
        )
    if (frame["date"].dt.date > as_of).any():
        raise ValueError("prices CSV contains future rows")
    observed = set(frame["symbol"].unique())
    missing_symbols = sorted(required_symbols - observed)
    if missing_symbols:
        raise ValueError("prices CSV missing frozen symbols: " + ", ".join(missing_symbols))
    return frame.sort_values(["date", "symbol"]).reset_index(drop=True)


def _artifact_hash_verified(path: Path) -> str:
    manifest_path = path.parent / "evidence_manifest.json"
    manifest = _load_json(manifest_path)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or outputs.get(path.name) != _sha256_file(path):
        raise ValueError(f"artifact hash mismatch: {path}")
    return str(manifest.get("manifest_identity_sha256") or _sha256_file(manifest_path))


def _build_aligned_factor_artifacts(
    *,
    fundamental_scores_path: Path,
    basket_scores_path: Path,
    prices: pd.DataFrame,
    basket_by_symbol: Mapping[str, str],
    benchmark: str,
    output_dir: Path,
) -> Path:
    fundamental_manifest = _artifact_hash_verified(fundamental_scores_path)
    basket_manifest = _artifact_hash_verified(basket_scores_path)
    fundamental_payload = _load_json(fundamental_scores_path)
    basket_payload = _load_json(basket_scores_path)
    fundamental_rows = fundamental_payload.get("rows")
    basket_rows = basket_payload.get("rows")
    if not isinstance(fundamental_rows, list) or not isinstance(basket_rows, list):
        raise ValueError("factor source artifacts must contain rows")

    score_rows: list[dict[str, Any]] = []
    for row in fundamental_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("stable_factor_key", ""))
        if key not in FUNDAMENTAL_FACTOR_KEYS or not bool(row.get("eligible", False)):
            continue
        score = row.get("percentile", row.get("score"))
        symbol = str(row.get("symbol", "")).upper()
        if score is None or symbol not in basket_by_symbol:
            continue
        score_rows.append(
            {
                "date": str(row["date"]),
                "symbol": symbol,
                "basket": basket_by_symbol[symbol],
                "stable_factor_key": key,
                "score": float(score),
            }
        )

    symbols_by_basket: dict[str, list[str]] = {}
    for symbol, basket in basket_by_symbol.items():
        symbols_by_basket.setdefault(basket, []).append(symbol)
    for row in basket_rows:
        if not isinstance(row, dict):
            continue
        basket = str(row.get("basket", ""))
        if basket not in symbols_by_basket:
            continue
        for key, field in BASKET_FACTOR_FIELDS.items():
            score = row.get(field)
            if score is None:
                continue
            for symbol in sorted(symbols_by_basket[basket]):
                score_rows.append(
                    {
                        "date": str(row["date"]),
                        "symbol": symbol,
                        "basket": basket,
                        "stable_factor_key": key,
                        "score": float(score),
                    }
                )
    scores = pd.DataFrame(score_rows)
    if scores.empty or set(scores["stable_factor_key"]) != set(FACTOR_KEYS):
        raise ValueError("aligned score artifact does not cover all frozen factors")
    scores["date"] = pd.to_datetime(scores["date"]).dt.normalize()
    scores = scores.drop_duplicates(
        ["date", "symbol", "stable_factor_key"], keep="last"
    ).sort_values(["date", "stable_factor_key", "symbol"])

    selection_rows: list[dict[str, Any]] = []
    for (signal_date, factor), group in scores.groupby(
        ["date", "stable_factor_key"], sort=True
    ):
        selected_symbols: set[str] = set()
        if factor in FUNDAMENTAL_FACTOR_KEYS:
            for _, basket_group in group.groupby("basket", sort=True):
                count = max(1, math.ceil(len(basket_group) * 0.30))
                selected_symbols.update(
                    basket_group.sort_values(
                        ["score", "symbol"], ascending=[False, True]
                    ).head(count)["symbol"]
                )
        else:
            basket_rank = (
                group.groupby("basket", as_index=False)["score"]
                .first()
                .sort_values(["score", "basket"], ascending=[False, True])
            )
            selected_baskets = set(basket_rank.head(2)["basket"])
            selected_symbols.update(
                group[group["basket"].isin(selected_baskets)]["symbol"]
            )
        for symbol in sorted(group["symbol"].unique()):
            selection_rows.append(
                {
                    "date": signal_date.date().isoformat(),
                    "stable_factor_key": factor,
                    "symbol": symbol,
                    "selected": symbol in selected_symbols,
                }
            )
    selections = pd.DataFrame(selection_rows)

    close = prices[["date", "symbol", "close"]].copy()
    close["date"] = pd.to_datetime(close["date"]).dt.normalize()
    close["close"] = pd.to_numeric(close["close"], errors="coerce")
    close = close.dropna(subset=["close"])
    trading_dates = sorted(close["date"].unique())
    next_date = {
        pd.Timestamp(current): pd.Timestamp(following)
        for current, following in zip(trading_dates, trading_dates[1:])
    }
    close_map = close.set_index(["date", "symbol"])["close"]
    return_rows: list[dict[str, Any]] = []
    selected_only = selections[selections["selected"]]
    for (signal_date, factor), group in selected_only.groupby(
        ["date", "stable_factor_key"], sort=True
    ):
        current = pd.Timestamp(signal_date)
        following = next_date.get(current)
        if following is None:
            continue
        values: list[float] = []
        for symbol in group["symbol"]:
            if (current, symbol) not in close_map.index or (
                following,
                symbol,
            ) not in close_map.index:
                continue
            start = float(close_map.loc[(current, symbol)])
            end = float(close_map.loc[(following, symbol)])
            if start > 0:
                values.append(end / start - 1.0)
        if values:
            return_rows.append(
                {
                    "date": current.date().isoformat(),
                    "stable_factor_key": factor,
                    "return": float(sum(values) / len(values)),
                }
            )
    returns = pd.DataFrame(return_rows)
    if returns.empty or set(returns["stable_factor_key"]) != set(FACTOR_KEYS):
        raise ValueError("aligned return artifact does not cover all frozen factors")

    output_dir.mkdir(parents=True, exist_ok=True)
    scores_path = output_dir / "scores.csv"
    selections_path = output_dir / "selections.csv"
    returns_path = output_dir / "returns.csv"
    scores[["date", "symbol", "stable_factor_key", "score"]].to_csv(
        scores_path, index=False
    )
    selections.to_csv(selections_path, index=False)
    returns.to_csv(returns_path, index=False)
    start_date = min(scores["date"].min(), pd.to_datetime(returns["date"]).min())
    end_date = max(scores["date"].max(), pd.to_datetime(returns["date"]).max())
    provider_identity = _canonical_hash(
        {
            "prices_sha256": _sha256_file(Path(prices.attrs["source_path"])),
            "fundamental_manifest": fundamental_manifest,
            "basket_manifest": basket_manifest,
        }
    )
    manifest = {
        "schema_version": "1.0",
        "scope": {
            "market": "us",
            "universe_version": "us_small_pool_v1",
            "benchmark": benchmark,
            "start_date": pd.Timestamp(start_date).date().isoformat(),
            "end_date": pd.Timestamp(end_date).date().isoformat(),
            "provider_identity": provider_identity,
            "evidence_manifest_hash": _canonical_hash(
                {
                    "fundamental_manifest": fundamental_manifest,
                    "basket_manifest": basket_manifest,
                }
            ),
        },
        "artifacts": {
            "scores": {"path": scores_path.name, "sha256": _sha256_file(scores_path)},
            "returns": {"path": returns_path.name, "sha256": _sha256_file(returns_path)},
            "selections": {
                "path": selections_path.name,
                "sha256": _sha256_file(selections_path),
            },
        },
    }
    manifest_path = output_dir / "input_manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def _assert_truth_boundary(payload: Mapping[str, Any], *, label: str) -> None:
    if payload.get("research_only") is not True:
        raise ValueError(f"{label} must remain research_only")
    if payload.get("trade_ready") is not False:
        raise ValueError(f"{label} must remain trade_ready=false")


def run_us_low_turnover_decision_pipeline(
    *,
    as_of_date: str,
    prices_csv: str | Path,
    registry_db: str | Path,
    ledger_dir: str | Path,
    workspace_dir: str | Path,
    sec_contract: str | Path = "configs/providers/sec_companyfacts_fundamentals_v1.yaml",
    fundamental_contract: str | Path = "configs/factors/us_fundamental_acceleration_v1.yaml",
    rotation_spec: str | Path = (
        "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2.yaml"
    ),
    relationship_contract: str | Path = (
        "configs/factor_knowledge/relationship_map_v1.yaml"
    ),
    multifactor_contract: str | Path = (
        "configs/factors/us_low_turnover_multifactor_v1.yaml"
    ),
    cutover_contract: str | Path = (
        "configs/operations/prospective_shadow_cutover_v1.yaml"
    ),
    fundamentals_csv: str | Path | None = None,
    sec_client: SecClientProtocol | None = None,
) -> dict[str, Any]:
    """Run the complete diagnostic pipeline and persist one immutable ticket."""

    as_of = date.fromisoformat(as_of_date)
    resolved_rotation = Path(rotation_spec).resolve()
    root = _repository_root(resolved_rotation)
    rotation_payload = yaml.safe_load(resolved_rotation.read_text(encoding="utf-8"))
    pool_path = root / str(rotation_payload["pool_spec"])
    basket_by_symbol, references = _pool_membership(pool_path)
    resolved_prices = Path(prices_csv).resolve()
    required_symbols = set(basket_by_symbol) | set(references)
    prices = _verify_prices(
        resolved_prices, required_symbols=required_symbols, as_of=as_of
    )
    prices.attrs["source_path"] = str(resolved_prices)

    run_root = Path(workspace_dir).resolve() / "us_low_turnover_pipeline" / as_of.isoformat()
    run_root.mkdir(parents=True, exist_ok=True)
    registry_path = Path(registry_db).resolve()
    registry = FactorKnowledgeRegistry(registry_path)
    legacy_migration = registry.migrate_legacy_registry()
    history_backfill = backfill_history_batch(
        registry,
        root / "configs/factor_knowledge/historical_factor_cards_v1.yaml",
    )

    sec_decision: dict[str, Any] | None = None
    if fundamentals_csv is None:
        sec_dir = run_root / "sec_companyfacts"
        sec_decision = build_sec_companyfacts_fundamentals(
            contract_path=sec_contract,
            output_dir=sec_dir,
            client=sec_client,
        )
        _assert_truth_boundary(sec_decision, label="SEC fundamentals")
        candidate_count = int(sec_decision.get("candidate_count", 0))
        ready_count = int(sec_decision.get("factor_ready_count", 0))
        if candidate_count <= 0 or ready_count != candidate_count:
            raise ValueError(
                "SEC fundamentals must cover every frozen candidate before pipeline use"
            )
        resolved_fundamentals = sec_dir / "fundamentals.csv"
    else:
        resolved_fundamentals = Path(fundamentals_csv).resolve()
        if not resolved_fundamentals.is_file():
            raise FileNotFoundError(resolved_fundamentals)

    fundamental_dir = run_root / "fundamental_acceleration"
    fundamental_decision = run_fundamental_acceleration(
        contract_path=fundamental_contract,
        fundamentals_csv=resolved_fundamentals,
        prices_csv=resolved_prices,
        output_dir=fundamental_dir,
        registry_db=registry_path,
    )
    _assert_truth_boundary(fundamental_decision, label="fundamental acceleration")

    rotation_dir = run_root / "hierarchical_rotation"
    rotation_decision = run_hierarchical_pool_rotation(
        spec_path=resolved_rotation,
        prices_csv=resolved_prices,
        output_dir=rotation_dir,
        authoritative_mode=False,
    )
    _assert_truth_boundary(rotation_decision, label="hierarchical rotation")

    aligned_dir = run_root / "aligned_factor_artifacts"
    relationship_input = _build_aligned_factor_artifacts(
        fundamental_scores_path=fundamental_dir / "factor_scores.json",
        basket_scores_path=rotation_dir / "basket_score_history.json",
        prices=prices,
        basket_by_symbol=basket_by_symbol,
        benchmark=str(rotation_payload["benchmark"]),
        output_dir=aligned_dir,
    )
    relationship_dir = run_root / "factor_relationship_map"
    relationship_decision = build_factor_relationship_map(
        contract_path=relationship_contract,
        input_manifest_path=relationship_input,
        registry_db=registry_path,
        output_dir=relationship_dir,
    )
    _assert_truth_boundary(relationship_decision, label="factor relationship map")

    multifactor_dir = run_root / "low_turnover_multifactor"
    multifactor_decision = run_low_turnover_multifactor_pipeline(
        contract_path=multifactor_contract,
        fundamental_scores_path=fundamental_dir / "factor_scores.json",
        basket_scores_path=rotation_dir / "basket_score_history.json",
        relationship_map_path=relationship_dir / "factor_relationships.json",
        prices_csv=resolved_prices,
        registry_db=registry_path,
        output_dir=multifactor_dir,
    )
    _assert_truth_boundary(multifactor_decision, label="low-turnover multifactor")
    if not bool(
        multifactor_decision.get("turnover_diagnostics", {}).get(
            "turnover_gate_passed", False
        )
    ):
        raise ValueError("low-turnover multifactor candidate failed turnover contract")

    shadow_workspace = run_root / "prospective_shadow"
    shadow_manifest = run_prospective_shadow_cycle(
        market="us",
        as_of_date=as_of.isoformat(),
        prices_csv=resolved_prices,
        spec_path=resolved_rotation,
        registry_db=registry_path,
        ledger_dir=ledger_dir,
        workspace_dir=shadow_workspace,
        cutover_contract=cutover_contract,
        factor_scores_path=multifactor_dir / "multifactor_scores.json",
    )
    if shadow_manifest.get("trade_ready") is not False:
        raise ValueError("prospective shadow output must remain trade_ready=false")
    ticket_path = Path(ledger_dir).resolve() / "us" / f"{as_of.isoformat()}.json"
    ticket = _load_json(ticket_path)
    _assert_truth_boundary(ticket, label="shadow ticket")

    input_identity = {
        "as_of_date": as_of.isoformat(),
        "prices_sha256": _sha256_file(resolved_prices),
        "fundamentals_sha256": _sha256_file(resolved_fundamentals),
        "registry_sha256": _sha256_file(registry_path),
        "sec_contract_sha256": _sha256_file(Path(sec_contract).resolve()),
        "fundamental_contract_sha256": _sha256_file(Path(fundamental_contract).resolve()),
        "rotation_spec_sha256": _sha256_file(resolved_rotation),
        "relationship_contract_sha256": _sha256_file(
            Path(relationship_contract).resolve()
        ),
        "multifactor_contract_sha256": _sha256_file(
            Path(multifactor_contract).resolve()
        ),
        "cutover_contract_sha256": _sha256_file(Path(cutover_contract).resolve()),
    }
    top_manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "pipeline_id": "us_low_turnover_decision_pipeline_v1",
        "market": "us",
        "as_of_date": as_of.isoformat(),
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "automatic_order_routing": False,
        "performance_evaluated": False,
        "inputs": input_identity,
        "stages": {
            "legacy_migration": legacy_migration,
            "history_backfill_card_count": history_backfill["card_count"],
            "sec_decision": sec_decision,
            "fundamental_decision": fundamental_decision,
            "rotation_decision": rotation_decision,
            "relationship_decision": relationship_decision,
            "multifactor_decision": multifactor_decision,
            "shadow_run_manifest_identity_sha256": shadow_manifest.get(
                "run_manifest_identity_sha256"
            ),
        },
        "outputs": {
            "fundamental_manifest_sha256": _sha256_file(
                fundamental_dir / "evidence_manifest.json"
            ),
            "rotation_manifest_sha256": _sha256_file(
                rotation_dir / "evidence_manifest.json"
            ),
            "relationship_manifest_sha256": _sha256_file(
                relationship_dir / "evidence_manifest.json"
            ),
            "multifactor_manifest_sha256": _sha256_file(
                multifactor_dir / "evidence_manifest.json"
            ),
            "ticket_identity_sha256": ticket["ticket_identity_sha256"],
            "ticket_file_sha256": _sha256_file(ticket_path),
        },
    }
    top_manifest["pipeline_run_identity_sha256"] = _canonical_hash(top_manifest)
    manifest_path = run_root / "pipeline_run_manifest.json"
    if manifest_path.exists():
        existing = _load_json(manifest_path)
        if existing.get("pipeline_run_identity_sha256") != top_manifest[
            "pipeline_run_identity_sha256"
        ]:
            raise ValueError("same-date pipeline run identity conflict")
        return existing
    _write_json(manifest_path, top_manifest)
    return top_manifest
