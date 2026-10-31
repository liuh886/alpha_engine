"""Offline, versioned RDI price repair from an archived existing-provider response."""

from __future__ import annotations

import csv
import gzip
import hashlib
import inspect
import io
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from .price_renewal import FIELDS, PRICE_RESOLUTION, audit_price_renewal


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def repo_file(root: Path, path: str) -> Path:
    resolved = (root / path).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def replay_source(root: Path, manifest: dict) -> bytes:
    """Reuse the installed vendor decoder and existing index normalizer offline."""
    import akshare
    import pandas as pd
    from akshare.stock.cons import hk_js_decode
    from py_mini_racer import MiniRacer

    from src.data.adapters.akshare_adapter import _normalize_index_frame

    if not (manifest["canonical_symbol"] == "000300.SH"
            and manifest["provider_symbol"] == "sh000300"
            and manifest["source_family"] == "sina"
            and manifest["instrument_type"] == "nontraded_equity_index"
            and manifest["price_basis"] == "unadjusted_index_points"
            and manifest["akshare_version"] == akshare.__version__
            and manifest["vendor_decoder_sha256"] == sha256(
                inspect.getsource(akshare.stock_zh_index_daily).encode())
            and manifest["adapter_module_sha256"] == sha256(
                (root / "src/data/adapters/akshare_adapter.py").read_bytes())
            and manifest["uv_lock_git_sha256"] == sha256(subprocess.check_output(
                ["git", "show", "HEAD:uv.lock"], cwd=root))
            and manifest["historical_first_availability_verified"] is False
            and manifest["research_only"] is True and manifest["trade_ready"] is False):
        raise ValueError("source identity, basis or decoder mismatch")
    packed = repo_file(root, manifest["archive_path"]).read_bytes()
    if sha256(packed) != manifest["archive_sha256"]:
        raise ValueError("source archive digest mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        raw = stream.read(1_000_001)
    if (len(raw) > 1_000_000 or len(raw) != manifest["raw_response_bytes"]
            or sha256(raw) != manifest["raw_response_sha256"]):
        raise ValueError("raw source response mismatch")
    payload = re.match(r'^var KLC_KL_sh000300="([^"]+)";', raw.decode())
    if not payload:
        raise ValueError("source payload is not the CSI300 index response")
    decoder = MiniRacer()
    try:
        decoder.eval(hk_js_decode)
        frame = pd.DataFrame(decoder.call("d", payload[1]))
    finally:
        # uv.lock selects mini-racer on Windows and py-mini-racer on Linux.
        # The latter releases its context in its finalizer, without close().
        close = getattr(decoder, "close", None)
        if close is not None:
            close()
    # Match stock_zh_index_daily's date conversion before the repository adapter.
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    normalized = _normalize_index_frame(
        frame, symbol="000300", start=manifest["start"], end=manifest["cutoff"],
    )
    data = normalized.to_csv(index=False, lineterminator="\n").encode()
    if len(normalized) != manifest["rows"] or sha256(data) != manifest["adapter_csv_sha256"]:
        raise ValueError("offline adapter replay differs from captured source CSV")
    return data


def repair_prices(legacy: bytes, source: bytes, contract: dict) -> tuple[bytes, dict]:
    """Keep every untouched retained OHLC string, admit only declared changes."""
    old = [r for r in csv.DictReader(io.StringIO(legacy.decode("utf-8-sig")))
           if r["date"] >= contract["start"]]
    fresh = list(csv.DictReader(io.StringIO(source.decode())))
    old_map = {r["date"]: r for r in old}
    new_map = {r["date"]: r for r in fresh}
    if (len(old_map) != len(old) or len(new_map) != len(fresh)
            or [r["date"] for r in fresh] != sorted(new_map)
            or [r["date"] for r in old] != sorted(old_map)
            or sha256(legacy) != contract["legacy_sha256"]
            or len(old) != contract["expected_retained_rows"]
            or old[-1]["date"] != contract["retained_cutoff"]
            or fresh[0]["date"] != contract["start"] or fresh[-1]["date"] != contract["cutoff"]
            or PRICE_RESOLUTION != contract["ohlc_audit_resolution_index_points"]
            or contract["output_fields"] != ["date", *FIELDS]):
        raise ValueError("retained/source price identity mismatch")
    missing = sorted(d for d in new_map if d <= contract["retained_cutoff"] and d not in old_map)
    if missing != contract["insert_sessions"] or set(old_map) - set(new_map):
        raise ValueError("undeclared historical session change")
    changes = {(r["date"], r["field"]): r for r in contract["replacements"]}
    if len(changes) != len(contract["replacements"]):
        raise ValueError("duplicate repair declaration")
    applied = set()
    for day, row in old_map.items():
        for field in FIELDS:
            if abs(float(row[field]) - float(new_map[day][field])) > PRICE_RESOLUTION:
                change = changes.get((day, field))
                if not change or change["old"] != row[field] or change["new"] != new_map[day][field]:
                    raise ValueError("undeclared or mismatched OHLC repair")
                applied.add((day, field))
    if applied != set(changes):
        raise ValueError("repair declaration does not match actual source conflict")
    fields = contract["output_fields"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    appended = 0
    for day in sorted(new_map):
        row = {k: (old_map[day] if day in old_map else new_map[day])[k] for k in fields}
        for field in FIELDS:
            if (day, field) in changes:
                row[field] = changes[(day, field)]["new"]
        writer.writerow(row)
        appended += day > contract["retained_cutoff"]
    if len(new_map) != contract["expected_output_rows"] or appended != contract["expected_append_rows"]:
        raise ValueError("output/append count mismatch")
    return output.getvalue().encode(), {
        "replacement_fields": contract["replacements"], "insert_sessions": missing,
        "append_rows": appended, "retained_rows": len(old), "output_rows": len(new_map),
        "all_other_retained_ohlc_strings_preserved": True,
    }


def reconstruct(root: Path, contract_path: Path, *, completed_cutoff: date) -> tuple[bytes, dict]:
    raw_contract = contract_path.read_bytes()
    contract = json.loads(raw_contract)
    if not (contract["canonical_symbol"] == "000300.SH"
            and contract["price_basis"] == "unadjusted_index_points"
            and contract["research_only"] is True and contract["trade_ready"] is False
            and contract["historical_first_availability_verified"] is False
            and contract["event_study_ready"] is False
            and contract["predictive_skill_established"] is False
            and date.fromisoformat(contract["cutoff"]) <= completed_cutoff):
        raise ValueError("invalid price-only reconstruction contract")
    raw_manifest = repo_file(root, contract["source_manifest"]).read_bytes()
    if sha256(raw_manifest) != contract["source_manifest_sha256"]:
        raise ValueError("source manifest digest mismatch")
    manifest = json.loads(raw_manifest)
    if manifest["start"] != contract["start"] or manifest["cutoff"] != contract["cutoff"]:
        raise ValueError("source/contract window mismatch")
    blob = contract["legacy_git_blob_sha1"]
    if not re.fullmatch("[0-9a-f]{40}", blob):
        raise ValueError("invalid legacy blob identity")
    legacy = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=root)
    source = replay_source(root, manifest)
    result, repairs = repair_prices(legacy, source, contract)
    market = root / "data/research/market_evidence/cn"
    # Reuse the strict calendar/OHLC/cutoff audit against the complete repaired
    # history. Remaining tiny legacy rounding is preserved, not normalized away.
    preflight = audit_price_renewal(
        result, (market / "catalog.json").read_bytes(),
        (market / "symbols/000300.json").read_bytes(), completed_cutoff=completed_cutoff,
    )
    if preflight["blockers"] != ["no_new_completed_prices", "original_provider_bytes_and_index_price_basis_not_certified"]:
        raise ValueError("reconstructed price history still conflicts with governed evidence")
    return result, {
        "schema_version": "rdi_versioned_price_reconstruction_v1",
        "status": "price_only_reconstruction_verified_not_rdi_validated",
        "contract_id": contract["contract_id"], "contract_sha256": sha256(raw_contract),
        "source_manifest_sha256": sha256(raw_manifest), "source_response_sha256": manifest["raw_response_sha256"],
        "source_retrieved_at": manifest["retrieved_at"], "historical_first_availability_verified": False,
        "legacy_git_blob_sha1": blob, "legacy_sha256": sha256(legacy),
        "output_sha256": sha256(result), "price_basis": manifest["price_basis"],
        "start": contract["start"], "cutoff": contract["cutoff"], "repairs": repairs,
        "calendar": preflight["calendar"], "governed_projection_sha256": preflight["candidate_projection_sha256"],
        "implementation_sha256": {name: sha256((root / "src/research/ashare_rdi" / name).read_bytes())
                                  for name in ("price_reconstruction.py", "price_baseline.py", "price_renewal.py")},
        "reference_registry_sha256": sha256((root / "configs/pools/reference_instrument_registry_v1.yaml").read_bytes()),
        "calendar_gaps": [], "governed_overlap_conflicts": [],
        "legacy_source_overwritten": False, "event_study_ready": False,
        "predictive_skill_established": False, "research_only": True, "trade_ready": False,
    }


def recompute(root: Path, contract_path: Path, *, completed_cutoff: date) -> tuple[bytes, dict]:
    from akshare.stock.cons import hk_js_decode

    from .outcomes import PriceBar
    from .price_baseline import descriptive_drawdown_comparison

    prices, receipt = reconstruct(root, contract_path, completed_cutoff=completed_cutoff)
    contract = json.loads(contract_path.read_bytes())
    protocol = contract["descriptive_protocol"]
    if (protocol["lookback_sessions"] != 60 or protocol["drawdown_threshold"] != -0.1
            or protocol["severe_loss_threshold"] != -0.05 or protocol["horizons"] != [7, 14, 28]):
        raise ValueError("price baseline definitions may not be retuned during renewal")
    rows = list(csv.DictReader(io.StringIO(prices.decode())))
    bars = [PriceBar(date.fromisoformat(r["date"]), float(r["open"]), float(r["low"]), float(r["close"]))
            for r in rows]
    receipt["full_history_descriptive"] = descriptive_drawdown_comparison(bars)
    receipt["retrospective_stress_case"] = descriptive_drawdown_comparison(
        bars, observation_start=date.fromisoformat(protocol["retrospective_start"]),
        observation_end=date.fromisoformat(protocol["retrospective_end"]),
    )
    trailing = bars[-60:]
    drawdown = bars[-1].close / max(b.close for b in trailing) - 1
    receipt["latest_price_only_B_state"] = {
        "session": bars[-1].session.isoformat(), "lookback_sessions": 60,
        "drawdown_from_trailing_close_peak": drawdown,
        "drawdown_at_least_10_percent": drawdown <= -0.1,
        "interpretation": "retrospective observed price state, not a forecast or RDI score",
    }
    receipt["limitations"] = [
        "single Sina transport; agreement with governed projection is not independent provider corroboration",
        "retrieved now, not a historical first-availability or source-revision certificate",
        "overlapping labels and retrospective stress case, no OOS or prospective inference",
        "no event PIT qualification, ETF admission, strategy overlay or product briefing rebinding",
    ]
    manifest = json.loads(repo_file(root, contract["source_manifest"]).read_bytes())
    receipt["source_api_function_sha256"] = manifest["vendor_decoder_sha256"]
    receipt["vendor_decoder_constant_sha256"] = sha256(hk_js_decode.encode())
    receipt["uv_lock_git_sha256"] = manifest["uv_lock_git_sha256"]
    return prices, receipt
