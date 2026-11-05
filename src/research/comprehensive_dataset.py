"""Data-first preflight and complete governed daily-history exchange planning.

Market-history packages include every *selected* symbol and all catalogued reference/
auxiliary instruments, never a handpicked sample. Full cross-domain approval is
a separate gate: missing vendor event bytes/Alpha158 cannot be invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from src.research.cloud_exchange import ExchangeError, _git_head, pack

RESEARCH_ROOT = Path("data/research/model_data_bundle_v1")
DATA_COMPONENTS = RESEARCH_ROOT / "data-components.json"
REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
REF_REGISTRY = Path("configs/pools/reference_instrument_registry_v1.yaml")
MARKETS = ("us", "cn")
FAMILIES = ("fundamentals", "corporate_actions")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict[str, Any]:
    val = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(val, dict):
        raise ExchangeError(f"expected YAML map: {path}")
    return val


def _file(root: Path, rel: str) -> Path:
    path = root / rel
    if not path.resolve().is_relative_to(root.resolve()):
        raise ExchangeError(f"unsafe path: {rel}")
    if path.is_symlink() or not path.is_file():
        raise ExchangeError(f"missing, symlinked or untrusted file: {rel}")
    return path


def _entry(root: Path, rel: str, role: str, expected: str | None = None) -> dict:
    file = _file(root, rel)
    observed = _hash(file)
    if expected is not None and observed != expected:
        raise ExchangeError(f"SHA mismatch {rel}: expected={expected} actual={observed}")
    return {"path": rel, "sha256": observed, "role": role, "size": file.stat().st_size}


def _event_payload(root: Path, market: str, family: str, component: dict) -> dict:
    """The repository commits source manifests; source *bytes* may be in durable archives."""
    base = RESEARCH_ROOT / "sources" / f"{market}_events" / family
    details = component.get("details") or {}
    rows = []
    for kind in ("events", "coverage"):
        rel = (base / f"{kind}.jsonl" if kind == "events" else
               base / f"{kind}.json").as_posix()
        expected = details.get(f"{kind}_sha256")
        target = root / rel
        if not expected or not re.fullmatch(r"[a-f0-9]{64}", str(expected)):
            rows.append({"path": rel, "status": "MISSING_EXPECTED_SHA"})
        elif not target.is_file() or target.is_symlink():
            rows.append({"path": rel, "status": "ARCHIVED_SOURCE_BYTES_NOT_STAGED",
                         "expected_sha256": expected})
        else:
            observed = _hash(target)
            rows.append({"path": rel, "status": "VERIFIED" if observed == expected
                         else "HASH_MISMATCH", "expected_sha256": expected})
    return {"family": family, "status": component.get("status"), "records": rows}


def _market(root: Path, market: str, components: list[dict]) -> dict:
    registry = _read_yaml(_file(root, REGISTRY.as_posix()))
    market_cfg = registry["markets"][market]
    pool = market_cfg["active_pool_id"]
    pool_path = market_cfg["pool_spec"]
    pool_spec = _read_yaml(_file(root, pool_path))
    members = set(map(str, pool_spec.get("symbols", [])))
    expected_count = market_cfg["candidate_count"]
    if pool_spec.get("pool_id") != pool or len(members) != expected_count:
        raise ExchangeError(f"selected pool roster mismatch: {market}")
    path = f"data/research/market_evidence/{market}/catalog.json"
    catalog = _read_json(_file(root, path))
    if catalog.get("pool_id") != pool or catalog.get("candidate_count") != expected_count:
        raise ExchangeError(f"market evidence catalog pool mismatch: {market}")
    if not (catalog.get("research_only") is True and catalog.get("market") == market):
        raise ExchangeError("market evidence does not satisfy research-only contract")
    symbols = catalog.get("symbols")
    if not isinstance(symbols, list):
        raise ExchangeError("market evidence catalog symbols missing")
    candidate_records = {str(x["symbol"]): x for x in symbols
                         if "selected_pool_candidate" in x.get("roles", [])}
    if set(candidate_records) != members:
        raise ExchangeError(f"catalogue candidates differ from frozen pool: {market}")
    ref_records = [x for x in symbols
                   if x.get("symbol") == catalog.get("benchmark") or
                   x.get("symbol") in catalog.get("auxiliary_symbols", []) or
                   'comparison_reference' in x.get('roles', [])]
    expected_refs = (set(map(str, catalog.get("auxiliary_symbols", []))) |
                     {catalog["benchmark"]} |
                     {str(x['symbol']) for x in symbols if 'comparison_reference' in x.get('roles', [])})
    observed_refs = {str(x["symbol"]) for x in ref_records}
    if expected_refs != observed_refs:
        raise ExchangeError(f"reference/auxiliary market coverage mismatch: {market}")
    expected_symbols = members | expected_refs
    if len(expected_symbols) != len(members) + len(expected_refs):
        raise ExchangeError("candidate and reference roles overlap")
    files: list[dict] = []
    failures: list[dict] = []
    # The catalog hash itself is the source manifest for the market-history export.
    files.append(_entry(root, pool_path, "pool_spec"))
    files.append(_entry(root, path, "source_manifest"))
    for rel in [REGISTRY.as_posix(), REF_REGISTRY.as_posix(), DATA_COMPONENTS.as_posix(),
                (RESEARCH_ROOT / "model-data-readiness.json").as_posix(),
                (RESEARCH_ROOT / "model-data-bundle.json").as_posix(),
                (RESEARCH_ROOT / "training-profiles.json").as_posix(),
                (RESEARCH_ROOT / "sources/governed-source-receipt.json").as_posix()]:
        files.append(_entry(root, rel, "data"))
    for comp in components:
        if comp.get("market") != market:
            continue
        manifest_rel = comp.get("manifest_path")
        if not manifest_rel:
            continue
        manifest_path = (RESEARCH_ROOT / manifest_rel).as_posix()
        # Some summary products refer to the existing price component summary,
        # while events reference source-family component manifests.
        if manifest_path in {x["path"] for x in files}:
            continue
        try:
            files.append(_entry(root, manifest_path, "data", comp.get("manifest_sha256")))
        except ExchangeError as exc:
            failures.append({"kind": comp.get("component_id"), "error": str(exc)})
    for rec in symbols:
        if str(rec.get("symbol")) not in expected_symbols:
            continue
        sub = rec.get("path")
        if not isinstance(sub, str) or not re.fullmatch(r"symbols/[A-Za-z0-9_.-]+\.json", sub):
            raise ExchangeError("invalid symbol evidence path")
        rel = f"data/research/market_evidence/{market}/{sub}"
        try:
            files.append(_entry(root, rel, "data", rec.get("sha256")))
        except ExchangeError as exc:
            failures.append({"symbol": rec["symbol"], "error": str(exc)})
    diag = catalog.get("factor_diagnostics_path")
    if diag:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", diag):
            raise ExchangeError("unsafe diagnostic path")
        try:
            files.append(_entry(root, f"data/research/market_evidence/{market}/{diag}",
                                "data", catalog.get("factor_diagnostics_sha256")))
        except ExchangeError as exc:
            failures.append({"kind": "factor_diagnostics", "error": str(exc)})
    comp_by_id = {x["component_id"]: x for x in components}
    price = comp_by_id.get(f"prices.{pool}")
    if not price or price.get("ready_symbol_count") != expected_count:
        failures.append({"kind": "prices", "error": "canonical price component not fully ready"})
    if price and catalog.get("provider_manifest_sha256") != price.get("manifest_sha256"):
        failures.append({"kind": "price_identity", "error": "provider manifest identity differs"})
    full = []
    for family in FAMILIES:
        component = comp_by_id.get(f"{family}.{pool}")
        if component is None:
            full.append({"family": family, "status": "MISSING_COMPONENT"})
            continue
        full.append(_event_payload(root, market, family, component))
    # Independently recorded CN Alpha158 is NOT the daily market evidence factor
    # series. The real component needs its own portable, hash-bound source payload.
    if market == "cn":
        alpha = comp_by_id.get("factors.qlib_alpha158.panel.cn.v1", {})
        full.append({"family": "qlib_alpha158", "status": alpha.get("status", "missing"),
                     "ready_symbols": alpha.get("ready_symbol_count"),
                     "expected_symbols": alpha.get("expected_symbol_count"),
                     "portable_payload_verified": False})
    full_complete = all(x.get("status") == "ready" and
                        all(y.get("status") == "VERIFIED" for y in x.get("records", []))
                        for x in full)
    # CN Alpha158 is deliberately not treated as complete from its summary metadata.
    return {
        "market": market, "pool_id": pool, "candidate_count": expected_count,
        "candidate_symbol_count": len(candidate_records),
        "reference_symbols": sorted(expected_refs),
        "source_start": catalog.get("start"), "source_cutoff": catalog.get("cutoff"),
        "latest_candidate_first_date": max(str(x.get("start", "")) for x in
                                           candidate_records.values()),
        "candidate_factor_series": sum(bool(x.get("factor_series_available"))
                                       for x in candidate_records.values()),
        "total_inputs": len(files), "total_bytes": sum(x["size"] for x in files),
        "market_history_status": "READY_FOR_RIGHTS_REVIEW" if not failures else "BLOCKED",
        "market_history_failures": failures,
        "additional_data_families": full,
        "full_research_status": "READY_FOR_RIGHTS_REVIEW" if full_complete and not failures
                                else "BLOCKED_INCOMPLETE_SOURCE_PAYLOAD",
        "files": files,
    }


def plan(root: Path, market: str = "all", *, detailed: bool = False) -> dict:
    root = root.resolve()
    components = _read_json(_file(root, DATA_COMPONENTS.as_posix()))
    if not isinstance(components, list):
        raise ExchangeError("data-components must be a list")
    markets = MARKETS if market == "all" else (market,)
    results = [_market(root, mk, components) for mk in markets]
    if detailed:
        from src.research.dataset_inventory import audit_market
        for item in results:
            catalog = _read_json(root / f"data/research/market_evidence/{item['market']}/catalog.json")
            item['physical_inventory'] = audit_market(root, catalog)
    return {
        "schema_version": "p2_comprehensive_data_plan_v1",
        "source_repository_revision": _git_head(root),
        "research_only": True, "trade_ready": False, "pit_certified": False,
        "rights_for_private_cloud_transfer": "UNREVIEWED",
        "no_colab_execution_authorized": True,
        "markets": results,
        "readiness": {
            "market_history": "READY_FOR_RIGHTS_REVIEW" if all(
                x["market_history_status"] == "READY_FOR_RIGHTS_REVIEW" for x in results
            ) else "BLOCKED",
            "full_research": "READY_FOR_RIGHTS_REVIEW" if all(
                x["full_research_status"] == "READY_FOR_RIGHTS_REVIEW" for x in results
            ) else "BLOCKED",
        },
    }


def approved_pack(root: Path, market: str, approval_path: Path, target: Path) -> dict:
    report = plan(root, market)
    item = report["markets"][0]
    if item["market_history_status"] != "READY_FOR_RIGHTS_REVIEW":
        raise ExchangeError("market-history source readiness is BLOCKED")
    approval = _read_json(approval_path)
    if not isinstance(approval, dict) or set(approval) != {
        "owner_approved_private_cloud_copy", "market", "source_manifest_sha256",
        "rights_class",
    } or approval.get("owner_approved_private_cloud_copy") is not True or (
        approval.get("rights_class") != "private_cloud_research_allowed"
    ):
        raise ExchangeError("explicit provider-rights approval for private cloud copy required")
    if approval["market"] != market:
        raise ExchangeError("approval market mismatch")
    source = next(x for x in item["files"] if x["role"] == "source_manifest")
    if approval["source_manifest_sha256"] != source["sha256"]:
        raise ExchangeError("source manifest changed after provider rights approval")
    recipe = {
        "schema_version": "alpha_research_exchange_v1",
        "study_id": f"{market}_complete_daily_history_{item['source_cutoff'].replace('-', '')}",
        "market": market, "pool_id": item["pool_id"],
        "data_cutoff": item["source_cutoff"],
        "repo_revision": report["source_repository_revision"],
        "source_manifest_path": source["path"],
        "source_manifest_sha256": source["sha256"],
        "owner_approved_private_cloud_copy": True,
        "rights_class": approval["rights_class"],
        "inputs": [
            {"path": x["path"], "sha256": x["sha256"], "role": x["role"]}
            for x in item["files"]
        ],
    }
    # Make recipe a private temporary file outside the checkout. No implicit Drive upload.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="alpha-exchange-") as tmp:
        spec = Path(tmp) / "recipe.json"
        spec.write_text(json.dumps(recipe), encoding="utf-8")
        output = pack(root, spec, target)
    return {"package": output["package"], "sha256": output["sha256"],
            "market": market, "input_count": item["total_inputs"],
            "tier": "complete_market_history_only",
            "full_research": item["full_research_status"],
            "private_cloud_rights_approved": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full market-history audit before Colab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--repo-root", type=Path, default=Path("."))
    audit.add_argument("--market", choices=("us", "cn", "all"), default="all")
    audit.add_argument("--output", type=Path)
    export = sub.add_parser("pack-market-history")
    export.add_argument("--repo-root", type=Path, default=Path("."))
    export.add_argument("--market", choices=MARKETS, required=True)
    rights = export.add_mutually_exclusive_group(required=True)
    rights.add_argument("--approval", type=Path)
    rights.add_argument("--local-only", action="store_true",
                        help="Build an explicitly non-cloud-approved local archive")
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "audit":
            result = plan(args.repo_root, args.market, detailed=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            # Do not flood stdout with 200+ file hashes.
            brief = {k: v for k, v in result.items() if k != "markets"}
            brief["markets"] = [
                {k: v for k, v in m.items() if k not in {"files", "physical_inventory"}}
                for m in result["markets"]
            ]
            print(json.dumps(brief, indent=2))
            return 0 if result["readiness"]["market_history"] != "BLOCKED" else 10
        if args.local_only:
            from src.research.comprehensive_bundle import local_history_pack
            result = local_history_pack(args.repo_root, args.market, args.output)
        else:
            result = approved_pack(args.repo_root, args.market, args.approval, args.output)
        print(json.dumps(result, indent=2))
        return 0
    except (ExchangeError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"BLOCKED_DATA_PACKAGE: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
