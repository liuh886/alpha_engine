"""Validate the governed indicator registry and generate its TypeScript view.

The YAML registry in ``configs/indicators`` is the governance authority. The
browser chart layer must not re-author indicator definitions, so this module
renders a deterministic, hash-bound TypeScript snapshot for the formula module
to consume. A pytest gate rejects drift between the YAML and the snapshot.

Boundaries: indicators are descriptive research evidence only.
``research_only=true`` and ``trade_ready=false`` are structural requirements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_RELATIVE = "configs/indicators/indicator_registry_v1.yaml"
GENERATED_RELATIVE = "qlib-dashboard/src/lib/indicator-registry.generated.ts"

ALLOWED_SCOPES = {"instrument", "market"}
ALLOWED_STATUSES = {"governed", "research_only", "blocked"}
ALLOWED_KINDS = {"derived", "series", "reserved"}
ALLOWED_MARKETS = {"us", "cn"}
ALLOWED_FIELDS = {"close", "volume"}

POLICY_CONTRACT = {
    "scope_isolation": True,
    "cross_market_indicator_use_allowed": False,
    "instrument_indicators_use_own_bars_only": True,
    "exact_observed_bars_only": True,
    "forward_fill_or_interpolation_allowed": False,
    "insufficient_data_emits_value": False,
    "browser_derived_at_render_time": True,
    "market_series_require_governed_publication": True,
}

# Required parameter names and ordered outputs per formula implementation.
FORMULA_CONTRACT: dict[str, tuple[dict[str, str], tuple[str, ...]]] = {
    "sma": ({"period": "integer"}, ("value",)),
    "ema": ({"period": "integer"}, ("value",)),
    "rsi": ({"period": "integer"}, ("value",)),
    "macd": (
        {"fast": "integer", "slow": "integer", "signal": "integer"},
        ("macd", "signal", "histogram"),
    ),
    "bollinger": (
        {"period": "integer", "std_dev": "positive_number"},
        ("middle", "upper", "lower"),
    ),
    "volume_sma": ({"period": "integer"}, ("value",)),
}
FORMULA_VERSION = "1"

ENTRY_KEYS = {
    "indicator_id",
    "scope",
    "kind",
    "market",
    "formula",
    "formula_version",
    "inputs",
    "params",
    "version",
    "status",
    "description",
    "provenance",
}
PROVENANCE_KEYS = {"authorized_by", "authorized_on", "rationale", "source"}

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INDICATOR_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SERIES_ID_PATTERN = re.compile(r"^(us|cn):[A-Za-z0-9._^-]+$")


def _fail(message: str) -> None:
    raise ValueError(message)


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{context} must be a mapping")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{context} must be a non-empty string")
    return value


def _date(value: Any, context: str) -> str:
    text = _text(value, context)
    if not DATE_PATTERN.match(text):
        _fail(f"{context} must be an ISO date")
    try:
        from datetime import date as _date_type

        parsed = _date_type.fromisoformat(text)
    except ValueError as error:  # pragma: no cover - defensive
        _fail(f"{context} is not a valid date: {error}")
    if parsed.isoformat() != text:
        _fail(f"{context} is not a canonical ISO date")
    return text


def _positive_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{context} must be a positive integer")
    return value


def _positive_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{context} must be a positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        _fail(f"{context} must be a finite positive number")
    return number


def load_indicator_registry(repository_root: Path | str = REPOSITORY_ROOT) -> dict[str, Any]:
    """Load the YAML registry from the repository root."""
    import yaml

    path = Path(repository_root).resolve() / REGISTRY_RELATIVE
    if not path.is_file():
        _fail(f"indicator registry is missing: {REGISTRY_RELATIVE}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        _fail("indicator registry must be a mapping")
    return document


def _validate_formula_catalog(catalog: Mapping[str, Any]) -> None:
    if set(catalog) != set(FORMULA_CONTRACT):
        _fail(
            "formula_catalog must list exactly the implemented formulas: "
            f"{sorted(FORMULA_CONTRACT)}"
        )
    for formula_id, raw in catalog.items():
        entry = _mapping(raw, f"formula_catalog.{formula_id}")
        if set(entry) != {"version", "params", "outputs"}:
            _fail(f"formula_catalog.{formula_id} has unexpected fields")
        if entry["version"] != FORMULA_VERSION:
            _fail(
                f"formula_catalog.{formula_id}.version must be {FORMULA_VERSION!r}"
            )
        expected_params, expected_outputs = FORMULA_CONTRACT[formula_id]
        params = entry["params"]
        outputs = entry["outputs"]
        if not isinstance(params, list) or set(params) != set(expected_params):
            _fail(f"formula_catalog.{formula_id}.params does not match the contract")
        if not isinstance(outputs, list) or tuple(outputs) != expected_outputs:
            _fail(f"formula_catalog.{formula_id}.outputs does not match the contract")


def _validate_inputs(entry: Mapping[str, Any], scope: str, market: str | None) -> None:
    inputs = _mapping(entry.get("inputs"), f"{entry.get('indicator_id')}.inputs")
    if scope == "instrument":
        if set(inputs) != {"source", "field"}:
            _fail(f"{entry.get('indicator_id')}.inputs must declare source and field")
        if inputs["source"] != "instrument_bars":
            _fail(f"{entry.get('indicator_id')}.inputs.source must be instrument_bars")
        if inputs["field"] not in ALLOWED_FIELDS:
            _fail(f"{entry.get('indicator_id')}.inputs.field must be close or volume")
        return

    if set(inputs) != {"source", "series_id"}:
        _fail(f"{entry.get('indicator_id')}.inputs must declare source and series_id")
    if inputs["source"] != "market_series":
        _fail(f"{entry.get('indicator_id')}.inputs.source must be market_series")
    series_id = _text(inputs["series_id"], f"{entry.get('indicator_id')}.series_id")
    match = SERIES_ID_PATTERN.match(series_id)
    if not match:
        _fail(f"{entry.get('indicator_id')}.series_id is not a governed market series id")
    if match.group(1) != market:
        _fail(
            f"{entry.get('indicator_id')}.series_id market {match.group(1)!r} "
            f"does not match declared market {market!r}"
        )


def _validate_derived_params(
    entry: Mapping[str, Any], formula: str
) -> None:
    params = _mapping(entry.get("params"), f"{entry.get('indicator_id')}.params")
    expected = FORMULA_CONTRACT[formula][0]
    if set(params) != set(expected):
        _fail(
            f"{entry.get('indicator_id')}.params must be exactly {sorted(expected)} "
            f"for formula {formula}"
        )
    for name, kind in expected.items():
        value = params[name]
        context = f"{entry.get('indicator_id')}.params.{name}"
        if kind == "integer":
            _positive_integer(value, context)
        else:
            _positive_number(value, context)
    if formula == "macd" and params["fast"] >= params["slow"]:
        _fail(f"{entry.get('indicator_id')}.params.fast must be less than slow")


def _validate_provenance(entry: Mapping[str, Any]) -> None:
    provenance = _mapping(
        entry.get("provenance"), f"{entry.get('indicator_id')}.provenance"
    )
    if set(provenance) != PROVENANCE_KEYS:
        _fail(f"{entry.get('indicator_id')}.provenance is incomplete")
    _text(provenance["authorized_by"], "provenance.authorized_by")
    _date(provenance["authorized_on"], "provenance.authorized_on")
    _text(provenance["rationale"], "provenance.rationale")
    _text(provenance["source"], "provenance.source")


def _validate_entry(entry: Any, seen: set[str]) -> None:
    row = _mapping(entry, "indicator entry")
    unknown = set(row) - ENTRY_KEYS
    if unknown:
        _fail(f"indicator entry has unexpected fields: {sorted(unknown)}")

    indicator_id = _text(row.get("indicator_id"), "indicator_id")
    if not INDICATOR_ID_PATTERN.match(indicator_id):
        _fail(f"indicator_id {indicator_id!r} is not snake_case")
    if indicator_id in seen:
        _fail(f"duplicate indicator_id {indicator_id!r}")
    seen.add(indicator_id)

    scope = row.get("scope")
    if scope not in ALLOWED_SCOPES:
        _fail(f"{indicator_id}.scope must be instrument or market")
    kind = row.get("kind")
    if kind not in ALLOWED_KINDS:
        _fail(f"{indicator_id}.kind must be derived, series or reserved")
    status = row.get("status")
    if status not in ALLOWED_STATUSES:
        _fail(f"{indicator_id}.status must be governed, research_only or blocked")
    _text(row.get("version"), f"{indicator_id}.version")
    _text(row.get("description"), f"{indicator_id}.description")

    market: str | None = None
    if scope == "instrument":
        if "market" in row:
            _fail(f"{indicator_id} is instrument-scope and must not declare a market")
    else:
        market = row.get("market")
        if market not in ALLOWED_MARKETS:
            _fail(f"{indicator_id}.market must be us or cn")

    _validate_inputs(row, scope, market)
    _validate_provenance(row)

    formula = row.get("formula")
    formula_version = row.get("formula_version")
    params = _mapping(row.get("params"), f"{indicator_id}.params")

    if kind == "derived":
        if formula not in FORMULA_CONTRACT:
            _fail(f"{indicator_id}.formula is not in the implemented formula catalog")
        if formula_version != FORMULA_VERSION:
            _fail(f"{indicator_id}.formula_version must be {FORMULA_VERSION!r}")
        _validate_derived_params(row, formula)
        if scope == "market" and formula == "volume_sma":
            _fail(f"{indicator_id} cannot apply volume_sma to a market series")
        if scope == "instrument":
            field = _mapping(row["inputs"], f"{indicator_id}.inputs")["field"]
            expected_field = "volume" if formula == "volume_sma" else "close"
            if field != expected_field:
                _fail(
                    f"{indicator_id}.inputs.field must be {expected_field!r} "
                    f"for formula {formula}"
                )
        return

    if formula is not None or formula_version is not None or params:
        _fail(f"{indicator_id} of kind {kind} must not declare a formula or params")
    if kind == "reserved" and status == "governed":
        _fail(f"{indicator_id} is reserved and cannot be governed")


def validate_indicator_registry(document: Mapping[str, Any]) -> None:
    """Fail closed on any registry shape that cannot be computed honestly."""
    if document.get("schema_version") != "1.0":
        _fail("indicator registry schema_version must be '1.0'")
    if document.get("registry_id") != "indicator_registry_v1":
        _fail("indicator registry id must be indicator_registry_v1")
    _date(document.get("created_at"), "created_at")
    if document.get("status") != "active_governance_contract":
        _fail("indicator registry must be an active governance contract")
    if document.get("research_only") is not True:
        _fail("indicator registry must remain research_only=true")
    if document.get("trade_ready") is not False:
        _fail("indicator registry must remain trade_ready=false")

    policy = _mapping(document.get("policy"), "policy")
    if set(policy) != set(POLICY_CONTRACT):
        _fail("policy must declare exactly the governed indicator rules")
    for name, expected in POLICY_CONTRACT.items():
        if policy[name] is not expected:
            _fail(f"policy.{name} must be {expected!r}")

    _validate_formula_catalog(_mapping(document.get("formula_catalog"), "formula_catalog"))

    indicators = document.get("indicators")
    if not isinstance(indicators, list) or not indicators:
        _fail("indicator registry must declare at least one indicator")
    seen: set[str] = set()
    for entry in indicators:
        _validate_entry(entry, seen)


def _ordered_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in (
        "indicator_id",
        "scope",
        "kind",
        "market",
        "formula",
        "formula_version",
        "inputs",
        "params",
        "version",
        "status",
        "description",
        "provenance",
    ):
        if key not in entry:
            continue
        value = entry[key]
        if key == "inputs":
            value = {
                name: value[name]
                for name in ("source", "field", "series_id")
                if name in value
            }
        elif key == "provenance":
            value = {
                name: value[name]
                for name in ("authorized_by", "authorized_on", "rationale", "source")
            }
        ordered[key] = value
    return ordered


def render_typescript(
    document: Mapping[str, Any], repository_root: Path | str = REPOSITORY_ROOT
) -> str:
    """Render the deterministic TypeScript snapshot consumed by the chart layer."""
    validate_indicator_registry(document)
    registry_path = Path(repository_root).resolve() / REGISTRY_RELATIVE
    source_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()

    catalog = {
        formula_id: {
            "version": entry["version"],
            "params": list(entry["params"]),
            "outputs": list(entry["outputs"]),
        }
        for formula_id, entry in document["formula_catalog"].items()
    }
    entries = [_ordered_entry(entry) for entry in document["indicators"]]

    catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2)
    entries_json = json.dumps(entries, ensure_ascii=False, indent=2)
    entries_json = "\n".join(
        f"  {line}" if line else line for line in entries_json.splitlines()
    )
    return (
        "// Generated from configs/indicators/indicator_registry_v1.yaml.\n"
        "// Do not edit by hand; run "
        "`python -m src.governance.indicator_registry --write`.\n"
        "import type { FormulaCatalogEntry, IndicatorEntry } from './indicators';\n\n"
        'export const INDICATOR_REGISTRY_SOURCE = '
        f'"{REGISTRY_RELATIVE}";\n'
        f'export const INDICATOR_REGISTRY_SOURCE_SHA256 = "{source_sha256}";\n'
        f'export const INDICATOR_REGISTRY_SCHEMA_VERSION = "{document["schema_version"]}";\n\n'
        "export const INDICATOR_FORMULA_CATALOG: "
        f"Readonly<Record<string, FormulaCatalogEntry>> = {catalog_json};\n\n"
        "export const INDICATOR_REGISTRY: readonly IndicatorEntry[] = "
        f"{entries_json};\n"
    )


def synchronize(
    repository_root: Path | str = REPOSITORY_ROOT, *, write: bool = False
) -> str:
    """Validate the registry and write or verify the generated TypeScript file."""
    root = Path(repository_root).resolve()
    document = load_indicator_registry(root)
    rendered = render_typescript(document, root)
    path = root / GENERATED_RELATIVE
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
        return rendered
    if not path.is_file():
        _fail(
            f"generated indicator registry is missing: {GENERATED_RELATIVE}; "
            "run `python -m src.governance.indicator_registry --write`"
        )
    if path.read_text(encoding="utf-8") != rendered:
        _fail(
            "generated indicator registry is out of date; "
            "run `python -m src.governance.indicator_registry --write`"
        )
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite the generated TypeScript snapshot",
    )
    args = parser.parse_args(argv)
    synchronize(REPOSITORY_ROOT, write=args.write)
    print(
        "indicator registry valid; generated snapshot "
        + ("written" if args.write else "in sync")
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
