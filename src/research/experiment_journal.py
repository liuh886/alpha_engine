"""Unified experiment memory -- query across all registries.

Provides a single ``ExperimentJournal`` class that can answer questions like
"what factors have I tried?", "which models were rejected?", and "what are
the walk-forward results?" by querying the factor registry, model registry,
and walk-forward artifact files.

Intended for agent consumption: the ``what_have_i_tried`` and ``what_failed``
methods return dicts that the agent's ``chat()`` method can format into
human-readable responses.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.common.logging import get_logger

__all__ = ["ExperimentJournal"]

logger = get_logger(__name__)


class ExperimentJournal:
    """Unified experiment memory -- query across all registries.

    Aggregates data from:
    - FactorRegistry (``artifacts/factor_registry.db``)
    - MLRegistry (``artifacts/registry.db``)
    - Walk-forward JSON files (``artifacts/walk_forward/``)

    Usage::

        journal = ExperimentJournal()
        summary = journal.get_summary(market="us")
        tried = journal.what_have_i_tried(market="us")
        failures = journal.what_failed(market="us")
    """

    def __init__(
        self,
        factor_db_path: str | None = None,
        model_db_path: str | None = None,
        walk_forward_dir: str | None = None,
    ) -> None:
        from src.common.paths import ARTIFACTS_DIR

        self._factor_db_path = factor_db_path or str(ARTIFACTS_DIR / "factor_registry.db")
        self._model_db_path = model_db_path or str(ARTIFACTS_DIR / "registry.db")
        self._walk_forward_dir = (
            Path(walk_forward_dir) if walk_forward_dir else ARTIFACTS_DIR / "walk_forward"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_factor_registry(self):
        """Lazy-import and return a FactorRegistry instance."""
        from src.research.factor_registry import FactorRegistry

        return FactorRegistry(db_path=self._factor_db_path)

    def _get_model_registry(self):
        """Lazy-import and return an MLRegistry instance."""
        from src.common.registry import MLRegistry

        return MLRegistry(db_path=self._model_db_path)

    @staticmethod
    def _parse_walk_forward_filename(filename: str) -> dict[str, str] | None:
        """Parse market and timestamp from a walk-forward filename.

        Expected pattern: ``{market}_{YYYYMMDD}_{HHMMSS}_{uuid}.json``
        """
        m = re.match(r"^(\w+)_(\d{8})_(\d{6})_[a-f0-9]+\.json$", filename)
        if not m:
            return None
        market, date_part, time_part = m.groups()
        ts = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        return {"market": market, "timestamp": ts, "filename": filename}

    def _load_walk_forward_files(self, market: str | None = None) -> list[dict]:
        """Load all walk-forward JSON files, optionally filtered by market."""
        wf_dir = self._walk_forward_dir
        if not wf_dir.exists():
            return []

        results: list[dict] = []
        for path in sorted(wf_dir.glob("*.json"), reverse=True):
            meta = self._parse_walk_forward_filename(path.name)
            if not meta:
                continue
            if market and meta["market"] != market:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                data["_file"] = path.name
                data["_timestamp"] = meta["timestamp"]
                data.setdefault("market", meta["market"])
                results.append(data)
            except Exception:
                logger.debug("Failed to load walk-forward file", path=str(path), exc_info=True)

        return results

    # ------------------------------------------------------------------
    # Factor experiments
    # ------------------------------------------------------------------

    def list_factor_experiments(
        self,
        market: str | None = None,
        stage: str | None = None,
        category: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List factor experiments with optional filters.

        Args:
            market: Filter validations by market (factors themselves are market-agnostic).
            stage: Filter by factor stage (Proposed, Candidate, Validated, Active, Deprecated).
            category: Filter by factor category.
            since: ISO-8601 timestamp; only return factors created after this time.
            limit: Maximum number of results.

        Returns:
            List of factor dicts, each enriched with latest validation info.
        """
        registry = self._get_factor_registry()
        factors = registry.list_factors(stage=stage, category=category)

        # Apply since filter
        if since:
            factors = [f for f in factors if f.get("created_at", "") >= since]

        results: list[dict] = []
        for f in factors[:limit]:
            validations = registry.get_validations(f["id"])
            # Filter validations by market if specified
            if market:
                validations = [v for v in validations if v.get("market") == market]

            latest_val = validations[0] if validations else None
            usage = registry.get_usage(f["id"])

            results.append(
                {
                    **f,
                    "latest_validation": latest_val,
                    "validation_count": len(validations),
                    "usage_count": len(usage),
                }
            )

        return results

    def get_factor_history(self, factor_id: int) -> dict:
        """Get full history of a factor: validations, promotions, usage.

        Returns:
            Dict with keys ``factor``, ``validations``, ``usage``.
        """
        registry = self._get_factor_registry()
        factor = registry.get_factor(factor_id)
        if not factor:
            return {"error": f"Factor {factor_id} not found"}

        validations = registry.get_validations(factor_id)
        usage = registry.get_usage(factor_id)

        return {
            "factor": factor,
            "validations": validations,
            "usage": usage,
        }

    # ------------------------------------------------------------------
    # Model experiments
    # ------------------------------------------------------------------

    def list_model_experiments(
        self,
        market: str | None = None,
        stage: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List model training experiments.

        Args:
            market: Filter by market (matched against model_name or metrics).
            stage: Filter by model stage (Staging, Production, Archived).
            since: ISO-8601 timestamp; only return models created after this time.
            limit: Maximum number of results.

        Returns:
            List of model version dicts.
        """
        registry = self._get_model_registry()
        models = registry.list_models(stage=stage)

        results: list[dict] = []
        for m in models:
            d = m.model_dump() if hasattr(m, "model_dump") else m.dict()
            # Apply since filter
            if since and d.get("created_at", "") < since:
                continue
            # Apply market filter (heuristic: check model_name or hyperparameters)
            if market:
                name_lower = (d.get("model_name") or "").lower()
                arch_lower = (d.get("architecture") or "").lower()
                hp = d.get("hyperparameters") or {}
                hp_market = str(hp.get("market", "")).lower()
                if (
                    market.lower() not in name_lower
                    and market.lower() not in arch_lower
                    and market.lower() != hp_market
                ):
                    continue

            results.append(d)
            if len(results) >= limit:
                break

        return results

    def get_model_history(self, model_id: str) -> dict:
        """Get full history of a model: training metrics, hyperparameters, stage.

        Returns:
            Model version dict, or an error dict if not found.
        """
        registry = self._get_model_registry()
        model = registry.get_model(model_id)
        if not model:
            return {"error": f"Model {model_id} not found"}

        d = model.model_dump() if hasattr(model, "model_dump") else model.dict()
        return d

    # ------------------------------------------------------------------
    # Walk-forward experiments
    # ------------------------------------------------------------------

    def list_walk_forward_results(
        self,
        market: str | None = None,
        since: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List walk-forward validation results from artifact JSON files.

        Args:
            market: Filter by market (e.g., "us", "cn").
            since: ISO-8601 timestamp; only return results after this time.
            limit: Maximum number of results.

        Returns:
            List of walk-forward result dicts with summary fields.
        """
        all_results = self._load_walk_forward_files(market=market)

        if since:
            all_results = [r for r in all_results if r.get("_timestamp", "") >= since]

        summaries: list[dict] = []
        for r in all_results[:limit]:
            splits = r.get("splits", [])
            # Summarise splits into key metrics
            split_summaries = []
            for s in splits:
                split_summaries.append(
                    {
                        "split_id": s.get("split_id"),
                        "train_period": f"{s.get('train_start', '')} -> {s.get('train_end', '')}",
                        "test_period": f"{s.get('test_start', '')} -> {s.get('test_end', '')}",
                        "ic": s.get("ic"),
                        "rank_ic": s.get("rank_ic"),
                        "sharpe": s.get("sharpe"),
                        "max_drawdown": s.get("max_drawdown"),
                        "annual_return": s.get("annual_return"),
                    }
                )

            summaries.append(
                {
                    "market": r.get("market"),
                    "model_type": r.get("model_type"),
                    "n_splits": len(splits),
                    "mean_ic": r.get("mean_ic"),
                    "std_ic": r.get("std_ic"),
                    "ic_ir": r.get("ic_ir"),
                    "consistency_score": r.get("consistency_score"),
                    "timestamp": r.get("_timestamp"),
                    "file": r.get("_file"),
                    "splits": split_summaries,
                }
            )

        return summaries

    # ------------------------------------------------------------------
    # Cross-registry search
    # ------------------------------------------------------------------

    def search_experiments(self, query: str, scope: str = "all") -> list[dict]:
        """Search across factors, models, and walk-forward results.

        Args:
            query: Free-text search string.
            scope: ``"all"``, ``"factors"``, ``"models"``, or ``"walk_forward"``.

        Returns:
            List of matching experiment dicts, each tagged with ``_source``
            indicating which registry it came from.
        """
        query_lower = query.strip().lower()
        results: list[dict] = []

        if scope in ("all", "factors"):
            registry = self._get_factor_registry()
            factors = registry.search_factors(query)
            for f in factors:
                results.append({**f, "_source": "factor"})

        if scope in ("all", "models"):
            model_reg = self._get_model_registry()
            models = model_reg.list_models()
            for m in models:
                d = m.model_dump() if hasattr(m, "model_dump") else m.dict()
                # Search across name, architecture, and serialized hyperparameters
                searchable = json.dumps(d, default=str).lower()
                if query_lower in searchable:
                    results.append({**d, "_source": "model"})

        if scope in ("all", "walk_forward"):
            wf_results = self._load_walk_forward_files()
            for r in wf_results:
                searchable = json.dumps(r, default=str).lower()
                if query_lower in searchable:
                    results.append(
                        {
                            "market": r.get("market"),
                            "model_type": r.get("model_type"),
                            "mean_ic": r.get("mean_ic"),
                            "ic_ir": r.get("ic_ir"),
                            "timestamp": r.get("_timestamp"),
                            "file": r.get("_file"),
                            "_source": "walk_forward",
                        }
                    )

        return results

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------

    def get_summary(self, market: str | None = None) -> dict:
        """Get summary stats across all registries.

        Returns:
            Dict with ``factors``, ``models``, ``walk_forward`` sub-dicts
            containing counts, stage breakdowns, and recent activity.
        """
        # Factor summary
        registry = self._get_factor_registry()
        factor_stats = registry.get_stats()

        factor_summary = {
            "total": factor_stats["total_factors"],
            "by_stage": factor_stats["by_stage"],
            "by_category": factor_stats["by_category"],
            "total_validations": factor_stats["total_validations"],
            "total_passed_validations": factor_stats["total_passed_validations"],
            "pass_rate": (
                round(
                    factor_stats["total_passed_validations"] / factor_stats["total_validations"], 4
                )
                if factor_stats["total_validations"] > 0
                else 0.0
            ),
        }

        # Model summary
        model_reg = self._get_model_registry()
        all_models = model_reg.list_models()
        by_stage: dict[str, int] = {}
        for m in all_models:
            s = m.stage
            by_stage[s] = by_stage.get(s, 0) + 1

        model_summary = {
            "total": len(all_models),
            "by_stage": by_stage,
        }

        # Walk-forward summary
        wf_files = self._load_walk_forward_files(market=market)
        wf_summary = {
            "total_files": len(wf_files),
            "markets": list({r.get("market") for r in wf_files}),
        }
        if wf_files:
            ics = [r.get("mean_ic", 0) for r in wf_files if r.get("mean_ic") is not None]
            wf_summary["best_mean_ic"] = max(ics) if ics else None
            wf_summary["worst_mean_ic"] = min(ics) if ics else None

        return {
            "factors": factor_summary,
            "models": model_summary,
            "walk_forward": wf_summary,
        }

    # ------------------------------------------------------------------
    # Agent-facing query methods
    # ------------------------------------------------------------------

    def what_have_i_tried(self, market: str = "us") -> dict:
        """Human-readable summary of all experiments for agent consumption.

        Returns a dict with three keys whose values are plain-language strings
        suitable for direct inclusion in agent chat responses.

        Returns:
            ``{"factors": "...", "models": "...", "walk_forward": "..."}``
        """
        # Factors
        registry = self._get_factor_registry()
        factor_stats = registry.get_stats()
        registry.list_factors()
        by_stage = factor_stats["by_stage"]
        active = by_stage.get("Active", 0)
        validated = by_stage.get("Validated", 0)
        candidate = by_stage.get("Candidate", 0)
        proposed = by_stage.get("Proposed", 0)
        deprecated = by_stage.get("Deprecated", 0)
        total = factor_stats["total_factors"]
        passed = factor_stats["total_passed_validations"]
        total_val = factor_stats["total_validations"]

        factor_parts = [f"Tried {total} factors"]
        stage_bits = []
        if active:
            stage_bits.append(f"{active} active")
        if validated:
            stage_bits.append(f"{validated} validated")
        if candidate:
            stage_bits.append(f"{candidate} candidates")
        if proposed:
            stage_bits.append(f"{proposed} proposed")
        if deprecated:
            stage_bits.append(f"{deprecated} deprecated")
        if stage_bits:
            factor_parts.append(", ".join(stage_bits))
        if total_val > 0:
            factor_parts.append(
                f"{passed}/{total_val} validations passed ({passed / total_val:.0%})"
            )

        # Top categories
        by_cat = factor_stats.get("by_category", {})
        if by_cat:
            top_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:3]
            factor_parts.append(f"Top categories: {', '.join(f'{c}={n}' for c, n in top_cats)}")

        factor_text = ". ".join(factor_parts) + "."

        # Models
        model_reg = self._get_model_registry()
        all_models = model_reg.list_models()
        model_by_stage: dict[str, int] = {}
        for m in all_models:
            model_by_stage[m.stage] = model_by_stage.get(m.stage, 0) + 1
        total_models = len(all_models)
        prod = model_by_stage.get("Production", 0)
        staging = model_by_stage.get("Staging", 0)
        archived = model_by_stage.get("Archived", 0)

        model_parts = [f"Trained {total_models} models"]
        m_bits = []
        if prod:
            m_bits.append(f"{prod} in production")
        if staging:
            m_bits.append(f"{staging} in staging")
        if archived:
            m_bits.append(f"{archived} archived")
        if m_bits:
            model_parts.append(", ".join(m_bits))
        model_text = ". ".join(model_parts) + "." if total_models > 0 else "No models trained yet."

        # Walk-forward
        wf_files = self._load_walk_forward_files(market=market)
        n_wf = len(wf_files)
        if n_wf > 0:
            passed_wf = sum(1 for r in wf_files if (r.get("ic_ir") or 0) > 0.5)
            best_ic = max((r.get("mean_ic") or 0) for r in wf_files)
            wf_text = (
                f"{n_wf} walk-forward validations for {market}. "
                f"{passed_wf} passed quality threshold (IC_IR > 0.5). "
                f"Best mean IC: {best_ic:.4f}."
            )
        else:
            wf_text = f"No walk-forward validations found for {market}."

        return {
            "factors": factor_text,
            "models": model_text,
            "walk_forward": wf_text,
        }

    def what_failed(self, market: str = "us") -> list[dict]:
        """List all failed experiments with reasons.

        Returns factors with an explicit failed validation or a terminal
        Deprecated/Retired stage, models that are Archived, and walk-forward
        results with poor IC_IR. A Proposed factor with no validation is
        pending work, not a failed experiment.

        Returns:
            List of dicts, each with ``_source``, ``name``/``id``, and
            ``reason`` fields.
        """
        failures: list[dict] = []

        # Failed factors: an explicit failed validation, or a terminal stage.
        registry = self._get_factor_registry()
        for stage in ("Proposed", "Deprecated", "Retired"):
            factors = registry.list_factors(stage=stage)
            for f in factors:
                validations = registry.get_validations(f["id"])
                latest = validations[0] if validations else None
                if stage == "Proposed" and (
                    not latest or latest.get("passed") is None or bool(latest.get("passed"))
                ):
                    continue
                reason = f"Stage: {stage}"
                if latest and not latest.get("passed"):
                    # Extract failure reason from metrics
                    icir = latest.get("icir")
                    t_stat = latest.get("t_stat")
                    parts = []
                    if icir is not None and icir < 0.5:
                        parts.append(f"ICIR={icir:.4f}")
                    if t_stat is not None and t_stat < 2.0:
                        parts.append(f"t_stat={t_stat:.4f}")
                    if parts:
                        reason += f" (low {', '.join(parts)})"
                elif not latest:
                    reason += " (no validation runs)"

                failures.append(
                    {
                        "_source": "factor",
                        "id": f["id"],
                        "name": f["name"],
                        "category": f.get("category"),
                        "stage": stage,
                        "timestamp": f.get("updated_at") or f.get("created_at") or "",
                        "reason": reason,
                    }
                )

        # Failed models: Archived stage
        model_reg = self._get_model_registry()
        for m in model_reg.list_models(stage="Archived"):
            d = m.model_dump() if hasattr(m, "model_dump") else m.dict()
            failures.append(
                {
                    "_source": "model",
                    "id": d["version_id"],
                    "name": d["model_name"],
                    "architecture": d.get("architecture"),
                    "stage": "Archived",
                    "timestamp": d.get("updated_at") or d.get("created_at") or "",
                    "reason": "Archived (superseded or underperforming)",
                    "metrics": d.get("metrics"),
                }
            )

        # Failed walk-forward: low IC_IR
        wf_files = self._load_walk_forward_files(market=market)
        for r in wf_files:
            ic_ir = r.get("ic_ir") or 0
            if ic_ir < 0.3:
                failures.append(
                    {
                        "_source": "walk_forward",
                        "file": r.get("_file"),
                        "market": r.get("market"),
                        "model_type": r.get("model_type"),
                        "_timestamp": r.get("_timestamp") or "",
                        "reason": f"Low IC_IR={ic_ir:.4f} (< 0.3)",
                        "mean_ic": r.get("mean_ic"),
                        "ic_ir": ic_ir,
                    }
                )

        return failures
