from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.dependencies import (
    get_asset_inspection_service,
    get_data_service,
    get_job_coordinator,
    get_quality_index,
    get_snapshot_index,
)
from src.api.schemas.jobs import JobResponse
from src.api.schemas.release_contracts import (
    ContractAPIRoute,
    DataUpdateRequestV1,
)
from src.common.paths import DASHBOARD_DB_PATH

router = APIRouter(tags=["data"], route_class=ContractAPIRoute)


@router.post("/update", response_model=JobResponse)
def trigger_data_update(payload: DataUpdateRequestV1):
    try:
        job = get_data_service().create_update_job_from_payload(payload.model_dump())
        return get_job_coordinator().submit_response(job)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/instruments")
def get_instruments(market: str = Query("us")):
    instruments = get_data_service().get_instruments(market=market)
    return {"ok": True, "market": market, "instruments": instruments}


@router.get("/status")
def get_data_status():
    status = get_data_service().get_data_status(
        dashboard_db_path=Path(DASHBOARD_DB_PATH),
        snapshot_index=get_snapshot_index(),
        quality_index=get_quality_index(),
    )
    return {"ok": True, "data": status}


@router.get("/snapshots/latest")
def get_latest_snapshot(dataset_key: str = "watchlist", freq: str = "day"):
    snap = get_snapshot_index().get_latest(dataset_key=dataset_key, freq=freq)
    if not snap:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return {"ok": True, "snapshot": snap}


@router.get("/quality/latest")
def get_latest_quality(dataset_key: str = "watchlist", freq: str = "day", market: str = "all"):
    rep = get_quality_index().get_latest(dataset_key=dataset_key, freq=freq, market=market)
    if not rep:
        raise HTTPException(status_code=404, detail="quality report not found")
    return {"ok": True, "quality": rep}


@router.get("/stock/{symbol}")
def get_stock_data(symbol: str):
    try:
        return get_asset_inspection_service().inspect(symbol)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/completeness")
def get_data_completeness(
    market: str = Query("us"),
    feature: str = Query("close"),
):
    """Return a completeness/value matrix for the given market and feature.

    For feature=close, returns 1.0 (data present) or null (missing).
    For other features (volume, amount, etc), returns actual values or null.
    """
    from src.assistant.services.data_service import AVAILABLE_FEATURES

    if feature not in AVAILABLE_FEATURES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown feature '{feature}'. Available: {AVAILABLE_FEATURES}",
        )
    result = get_data_service().get_completeness_matrix(market=market, feature=feature)
    return {"ok": True, "data": result}


@router.get("/features")
def list_available_features():
    """Return the list of features available for the completeness heatmap."""
    from src.assistant.services.data_service import AVAILABLE_FEATURES

    return {"ok": True, "features": AVAILABLE_FEATURES}


@router.get("/integrity")
def check_data_integrity(market: str = Query("us"), strict: bool = Query(False)):
    """Run data integrity checks: instrument sync, binary alignment, temporal gaps."""
    return get_data_service().validate_data_integrity(market=market, strict=strict)


@router.get("/name-map")
def get_name_map():
    """Return the ticker-to-name mapping for displaying human-readable names."""
    from pathlib import Path

    import yaml

    name_map_path = Path(__file__).resolve().parents[3] / "configs" / "name_map.yaml"
    if not name_map_path.exists():
        return {"ok": True, "name_map": {}}

    with open(name_map_path, encoding="utf-8") as f:
        name_map = yaml.safe_load(f) or {}

    return {"ok": True, "name_map": name_map}


# ---------------------------------------------------------------------------
# Watchlist Management
# ---------------------------------------------------------------------------


def _load_watchlist_yaml() -> dict:
    """Load the watchlist.yaml file."""
    import yaml

    wl_path = Path(__file__).resolve().parents[3] / "configs" / "watchlist.yaml"
    if not wl_path.exists():
        return {"us": [], "cn": [], "hk": []}
    with wl_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_watchlist_yaml(data: dict) -> None:
    """Save the watchlist.yaml file."""
    import yaml

    wl_path = Path(__file__).resolve().parents[3] / "configs" / "watchlist.yaml"
    with wl_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _sync_instruments_file(market: str, symbols: list[str]) -> None:
    """Sync the instruments txt file for a market."""
    instr_path = (
        Path(__file__).resolve().parents[3] / "data" / "watchlist" / "instruments" / f"{market}.txt"
    )
    if not instr_path.parent.exists():
        instr_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing to preserve date ranges
    existing: dict[str, str] = {}
    if instr_path.exists():
        for line in instr_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split("\t")
            if parts:
                existing[parts[0]] = line.rstrip()

    # Build new file
    lines = []
    for sym in sorted(set(symbols), key=lambda x: int(x) if x.isdigit() else x):
        if sym in existing:
            lines.append(existing[sym])
        else:
            lines.append(f"{sym}\t2018-01-01\t2026-12-31")

    instr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Also rebuild all.txt
    all_path = instr_path.parent / "all.txt"
    all_lines = []
    for mkt in ("us", "cn", "hk"):
        mkt_path = instr_path.parent / f"{mkt}.txt"
        if mkt_path.exists():
            all_lines.extend(mkt_path.read_text(encoding="utf-8").strip().splitlines())
    all_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")


@router.get("/watchlist")
def get_watchlist():
    """Get the full watchlist with names, grouped by market."""
    data = _load_watchlist_yaml()

    # Load name map
    import yaml as _yaml

    name_map_path = Path(__file__).resolve().parents[3] / "configs" / "name_map.yaml"
    name_map: dict[str, str] = {}
    if name_map_path.exists():
        name_map = _yaml.safe_load(name_map_path.open("r", encoding="utf-8")) or {}

    result = {}
    for market, symbols in data.items():
        if not isinstance(symbols, list):
            continue
        result[market] = [{"symbol": str(s), "name": name_map.get(str(s), "")} for s in symbols]

    return {"ok": True, "watchlist": result}


class AddSymbolsRequest(BaseModel):
    symbols: list[str]
    market: str = "cn"


class RemoveSymbolsRequest(BaseModel):
    symbols: list[str]
    market: str = "cn"


@router.post("/instruments/add")
def add_symbols(req: AddSymbolsRequest):
    """Add symbols to the watchlist."""
    if not req.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")

    data = _load_watchlist_yaml()
    market = req.market.lower()
    existing = set(str(s) for s in data.get(market, []))

    added = []
    for sym in req.symbols:
        clean = sym.strip().upper().split(".")[0]  # Strip exchange suffix
        if clean and clean not in existing:
            data.setdefault(market, []).append(clean)
            existing.add(clean)
            added.append(clean)

    if not added:
        return {"ok": True, "added": [], "message": "All symbols already exist"}

    # Sort numerically for CN/HK, alphabetically for US
    if market in ("cn", "hk"):
        data[market] = sorted(
            set(str(s) for s in data[market]), key=lambda x: int(x) if x.isdigit() else x
        )
    else:
        data[market] = sorted(set(str(s) for s in data[market]))

    _save_watchlist_yaml(data)
    _sync_instruments_file(market, [str(s) for s in data[market]])

    return {"ok": True, "added": added, "total": len(data[market])}


@router.post("/instruments/remove")
def remove_symbols(req: RemoveSymbolsRequest):
    """Remove symbols from the watchlist."""
    if not req.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")

    data = _load_watchlist_yaml()
    market = req.market.lower()
    existing = [str(s) for s in data.get(market, [])]
    to_remove = set(s.strip().upper().split(".")[0] for s in req.symbols)

    removed = []
    new_list = []
    for sym in existing:
        if sym in to_remove:
            removed.append(sym)
        else:
            new_list.append(sym)

    if not removed:
        return {"ok": True, "removed": [], "message": "No matching symbols found"}

    data[market] = new_list
    _save_watchlist_yaml(data)
    _sync_instruments_file(market, new_list)

    return {"ok": True, "removed": removed, "total": len(new_list)}
