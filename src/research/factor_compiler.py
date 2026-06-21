"""Factor-to-strategy config compiler.

Loads Active factors from the FactorRegistry and merges their Qlib expressions
into an existing workflow YAML config, producing a new config file ready for
backtesting or live inference.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.common.logging import get_logger
from src.common.paths import CONFIG_DIR
from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

logger = get_logger(__name__)

__all__ = [
    "CompiledConfig",
    "compile_factors_to_config",
    "get_recommended_factors",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CompiledConfig:
    """Summary returned after compiling factors into a strategy config."""

    output_path: str
    factors_included: int
    factor_names: list[str]
    factor_expressions: list[str]
    original_feature_count: int
    new_feature_count: int
    config_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": self.output_path,
            "factors_included": self.factors_included,
            "factor_names": self.factor_names,
            "factor_expressions": self.factor_expressions,
            "original_feature_count": self.original_feature_count,
            "new_feature_count": self.new_feature_count,
            "config_summary": self.config_summary,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_config_path(base_config_path: str) -> Path:
    """Resolve *base_config_path* to an absolute path.

    Accepts an absolute path, a path relative to the project root, or just a
    filename (looked up in the configs directory).
    """
    p = Path(base_config_path)
    if p.is_absolute() and p.exists():
        return p

    # Try relative to configs dir first
    candidate = CONFIG_DIR / base_config_path
    if candidate.exists():
        return candidate

    # Try relative to project root
    from src.common.paths import PROJECT_ROOT

    candidate = PROJECT_ROOT / base_config_path
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"Config not found: {base_config_path!r} "
        f"(checked {CONFIG_DIR / base_config_path} and {candidate})"
    )


def _auto_output_path(base_config_path: Path, market: str) -> Path:
    """Generate an output path like ``<base>_with_factors_<market>_<date>.yaml``."""
    stem = base_config_path.stem
    suffix = base_config_path.suffix
    date_str = datetime.now().strftime("%Y%m%d")
    return base_config_path.parent / f"{stem}_with_factors_{market}_{date_str}{suffix}"


def _extract_feature_list(cfg: dict) -> list[str]:
    """Walk the config dict and return the current feature expression list.

    Follows the standard Qlib workflow YAML structure:
    ``task -> dataset -> kwargs -> handler -> kwargs -> data_loader -> kwargs -> config -> feature``
    """
    try:
        return list(
            cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"]["kwargs"][
                "config"
            ]["feature"]
        )
    except (KeyError, TypeError):
        return []


def _set_feature_list(cfg: dict, features: list[str]) -> None:
    """Set the feature expression list in the config dict (in-place)."""
    cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"]["kwargs"]["config"][
        "feature"
    ] = features


def _extract_config_summary(cfg: dict) -> dict[str, Any]:
    """Pull key parameters from the compiled config for the result summary."""
    summary: dict[str, Any] = {}
    summary["market"] = cfg.get("market")
    summary["benchmark"] = cfg.get("benchmark")

    model = cfg.get("task", {}).get("model", {})
    summary["model_class"] = model.get("class")
    summary["model_params"] = {k: v for k, v in model.get("kwargs", {}).items()}

    segments = cfg.get("task", {}).get("dataset", {}).get("kwargs", {}).get("segments", {})
    summary["segments"] = segments

    strategy = cfg.get("port_analysis_config", {}).get("strategy", {})
    summary["strategy_class"] = strategy.get("class")
    summary["strategy_params"] = strategy.get("kwargs", {})

    return summary


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_factors_to_config(
    base_config_path: str,
    output_path: str | None = None,
    factor_ids: list[int] | None = None,
    market: str = "us",
    merge_mode: str = "append",
) -> CompiledConfig:
    """Compile registered factors into a workflow YAML config.

    Steps:
    1. Load the base YAML config.
    2. Load Active factors from FactorRegistry (or specific *factor_ids*).
    3. Get the current feature list from the config.
    4. Merge the factor expressions into the feature list:
       - ``"append"``: add new factor expressions after existing features, skip duplicates.
       - ``"replace"``: use only the registered factor expressions.
    5. Update the config's feature section with the merged list.
    6. Add factor metadata as comments in the YAML header.
    7. Write the output YAML.
    8. Return :class:`CompiledConfig` with summary.

    Args:
        base_config_path: Path to existing workflow YAML (absolute, relative
            to project root, or just a filename found in ``configs/``).
        output_path: Where to write the new config.  If ``None``, an
            auto-generated name is used.
        factor_ids: Specific factor IDs to include.  If ``None``, all Active
            factors are used.
        market: Market filter for factor selection.
        merge_mode: ``"append"`` or ``"replace"``.

    Returns:
        A :class:`CompiledConfig` summarising the compilation.

    Raises:
        FileNotFoundError: If *base_config_path* cannot be resolved.
        ValueError: If *merge_mode* is not recognised or no factors are found.
    """
    if merge_mode not in ("append", "replace"):
        raise ValueError(f"merge_mode must be 'append' or 'replace', got {merge_mode!r}")

    # ------------------------------------------------------------------
    # 1. Load base config
    # ------------------------------------------------------------------
    config_path = _resolve_config_path(base_config_path)
    logger.info("loading_base_config", path=str(config_path))

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    cfg = copy.deepcopy(cfg)

    # ------------------------------------------------------------------
    # 2. Load factors from registry
    # ------------------------------------------------------------------
    registry = FactorRegistry()

    if factor_ids is not None:
        factors = []
        for fid in factor_ids:
            f = registry.get_factor(fid)
            if f is None:
                logger.warning("factor_not_found", factor_id=fid)
                continue
            factors.append(f)
        if not factors:
            raise ValueError(f"No factors found for the given IDs: {factor_ids}")
    else:
        factors = registry.list_factors(stage=STAGE_ACTIVE)

    if not factors:
        raise ValueError(
            "No Active factors found in the registry. "
            "Use discover_factor or scan_factor_pool to create factors first."
        )

    logger.info("factors_loaded", count=len(factors), market=market)

    # ------------------------------------------------------------------
    # 3. Get current feature list
    # ------------------------------------------------------------------
    existing_features = _extract_feature_list(cfg)
    original_count = len(existing_features)
    logger.info("existing_features", count=original_count)

    # ------------------------------------------------------------------
    # 4. Build new expression list from factors
    # ------------------------------------------------------------------
    factor_names: list[str] = []
    factor_expressions: list[str] = []
    for f in factors:
        expr = f["expression"].strip()
        name = f["name"].strip()
        if expr and expr not in factor_expressions:
            factor_names.append(name)
            factor_expressions.append(expr)

    if not factor_expressions:
        raise ValueError("All loaded factors have empty expressions.")

    logger.info("factor_expressions_prepared", count=len(factor_expressions))

    # ------------------------------------------------------------------
    # 5. Merge
    # ------------------------------------------------------------------
    if merge_mode == "append":
        existing_set = set(existing_features)
        new_expressions = [e for e in factor_expressions if e not in existing_set]
        merged_features = existing_features + new_expressions
        logger.info(
            "merge_append",
            added=len(new_expressions),
            skipped_duplicates=len(factor_expressions) - len(new_expressions),
        )
    else:  # replace
        merged_features = list(factor_expressions)
        logger.info("merge_replace", new_count=len(merged_features))

    new_count = len(merged_features)

    # ------------------------------------------------------------------
    # 6. Update config
    # ------------------------------------------------------------------
    _set_feature_list(cfg, merged_features)

    # ------------------------------------------------------------------
    # 7. Resolve output path
    # ------------------------------------------------------------------
    if output_path is not None:
        out = Path(output_path)
        if not out.is_absolute():
            from src.common.paths import PROJECT_ROOT

            out = PROJECT_ROOT / output_path
    else:
        out = _auto_output_path(config_path, market)

    out.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 8. Build YAML header comment with factor metadata
    # ------------------------------------------------------------------
    header_lines = [
        "# --- Factor Compiler Metadata ---",
        f"# Generated: {datetime.now().isoformat()}",
        f"# Base config: {config_path.name}",
        f"# Merge mode: {merge_mode}",
        f"# Market: {market}",
        f"# Factors included: {len(factor_names)}",
        "#",
        "# Registered factors:",
    ]
    for name, expr in zip(factor_names, factor_expressions):
        header_lines.append(f"#   {name}: {expr}")
    header_lines.append("# --- End Factor Compiler Metadata ---")
    header_lines.append("")

    header = "\n".join(header_lines)

    # ------------------------------------------------------------------
    # 9. Write output
    # ------------------------------------------------------------------
    yaml_content = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=False)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.write(yaml_content)

    logger.info(
        "config_compiled",
        output_path=str(out),
        factors_included=len(factor_names),
        original_features=original_count,
        new_features=new_count,
    )

    # ------------------------------------------------------------------
    # 10. Return summary
    # ------------------------------------------------------------------
    return CompiledConfig(
        output_path=str(out),
        factors_included=len(factor_names),
        factor_names=factor_names,
        factor_expressions=factor_expressions,
        original_feature_count=original_count,
        new_feature_count=new_count,
        config_summary=_extract_config_summary(cfg),
    )


def get_recommended_factors(
    market: str = "us",
    min_icir: float = 0.7,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Get Active factors that meet quality thresholds for strategy compilation.

    Queries the factor registry for Active factors, then filters by the most
    recent validation metrics for the given *market*.  Only factors whose
    ``icir >= min_icir`` (absolute value) and whose validation ``passed`` flag
    is true are returned.

    Args:
        market: Market to check validations against.
        min_icir: Minimum absolute ICIR for a factor to be recommended.
        category: Optional category filter.

    Returns:
        A list of dicts, each containing factor metadata plus the latest
        validation metrics.  Sorted by descending |ICIR|.
    """
    registry = FactorRegistry()
    factors = registry.list_factors(stage=STAGE_ACTIVE, category=category)

    if not factors:
        return []

    recommended: list[dict[str, Any]] = []

    with registry._connect() as conn:
        for f in factors:
            # Get the most recent passed validation for this market
            row = conn.execute(
                """
                SELECT ic, rank_ic, icir, t_stat, positive_ratio,
                       quintile_spread, validated_at
                FROM factor_validations
                WHERE factor_id = ? AND market = ? AND passed = 1
                ORDER BY validated_at DESC
                LIMIT 1
                """,
                (f["id"], market),
            ).fetchone()

            if row is None:
                continue

            icir_val = row["icir"]
            if icir_val is None:
                continue
            if abs(icir_val) < min_icir:
                continue

            entry = {
                "factor_id": f["id"],
                "name": f["name"],
                "expression": f["expression"],
                "category": f["category"],
                "direction": f["direction"],
                "lookback_days": f["lookback_days"],
                "thesis": f["thesis"],
                "ic": row["ic"],
                "rank_ic": row["rank_ic"],
                "icir": row["icir"],
                "t_stat": row["t_stat"],
                "positive_ratio": row["positive_ratio"],
                "quintile_spread": row["quintile_spread"],
                "validated_at": row["validated_at"],
            }
            recommended.append(entry)

    # Sort by absolute ICIR descending
    recommended.sort(key=lambda x: abs(x.get("icir") or 0), reverse=True)

    logger.info(
        "recommended_factors",
        market=market,
        min_icir=min_icir,
        category=category,
        total_active=len(factors),
        recommended=len(recommended),
    )

    return recommended
