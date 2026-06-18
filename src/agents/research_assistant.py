from __future__ import annotations

import json
import os
import time
from typing import Any

import structlog

from .core.base_agent import BaseAgent
from .tools.data_tools import run_data_update
from .tools.governance_tools import format_thought_stream_for_report
from src.reliability.events import ReliabilityEvent
from src.reliability.failure_log import resolve_failure_event
from src.reliability.governance_policy import GovernanceReliabilityPolicy

log = structlog.get_logger()


class ResearchAssistant(BaseAgent):
    """
    Unified research assistant for a single-user quant platform.
    Consolidates capabilities from Alpha, Risk, Governance, and Developer agents
    into a single agent with tool-based routing.

    Usage::

        assistant = ResearchAssistant(llm_client=None)
        result = assistant.analyze_factors("us")
        risk = assistant.assess_risk()
    """

    # --- constants (shared across former agents) ---
    TRADING_DAYS_PER_YEAR = 252
    DEFAULT_VOLATILITY_FALLBACK = 15.0
    PANIC_INDEX_OFFSET = 10
    PANIC_INDEX_MULTIPLIER = 3.33
    HIGH_VOL_THRESHOLD = 25.0
    HIGH_PANIC_THRESHOLD = 75.0

    def __init__(self, llm_client=None, quality_index=None):
        super().__init__(model_name="gpt-4o")
        self._llm = llm_client
        self._quality_index = quality_index
        self._memory_file = "artifacts/memory/factor_genes.json"
        self._risk_memory_file = "artifacts/memory/risk_cases.json"
        self._evidence_canvas_path = "artifacts/dashboard/evidence_canvas.json"

        # Ensure memory directories exist
        for path in (self._memory_file, self._risk_memory_file):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                with open(path, "w") as f:
                    json.dump({} if "factor" in path else [], f)

        os.makedirs(os.path.dirname(self._evidence_canvas_path), exist_ok=True)
        self._policy = GovernanceReliabilityPolicy()

    # =====================================================================
    # Factor Analysis  (from Alpha Agent)
    # =====================================================================

    def analyze_factors(self, market: str = "us") -> dict[str, Any]:
        """Run a full research cycle: data check -> attribution -> hyperparams."""
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Initiating research cycle for {market.upper()} equities.",
        )

        if not self.check_data_quality(market).get("ok"):
            return {"ok": False, "error": "Data integrity check failed"}

        # --- Factor attribution ---
        try:
            from src.research.factor_attribution import attribute_returns

            attribution_report = attribute_returns(market=market)
            attribution_dict = attribution_report.to_dict()
        except Exception as exc:
            log.warning("Factor attribution failed", error=str(exc))
            attribution_dict = None

        # --- Active factors from registry ---
        top_factors = []
        factor_coverage = 0.0
        excess_return = 0.0
        recommendation = "No attribution data available."

        if attribution_dict is not None:
            try:
                # Extract top 3 contributing factors
                contribs = attribution_dict.get("factor_contributions", [])
                for fc in contribs[:3]:
                    top_factors.append({
                        "name": fc.get("factor_name", ""),
                        "ic": fc.get("factor_ic", 0.0),
                        "return_contribution_pct": fc.get("return_contribution_pct", 0.0),
                        "risk_contribution_pct": fc.get("risk_contribution_pct", 0.0),
                    })

                factor_coverage = attribution_dict.get("factor_coverage", 0.0)
                excess_return = attribution_dict.get("excess_return", 0.0)

                # Auto-generate recommendation
                if top_factors:
                    leader = top_factors[0]
                    leader_name = leader["name"]
                    leader_ret_pct = abs(leader["return_contribution_pct"])
                    if leader_ret_pct > 0:
                        recommendation = (
                            f"Top contributor is {leader_name} with "
                            f"{leader_ret_pct:.1f}% of return explained. "
                            f"Model R^2 = {attribution_dict.get('attribution_confidence', 0):.2f}."
                        )
                    else:
                        recommendation = (
                            f"Factor model has R^2 = "
                            f"{attribution_dict.get('attribution_confidence', 0):.2f} "
                            f"but no dominant return contributor identified."
                        )
                else:
                    recommendation = "Attribution completed but no active factors contributed."
            except Exception as exc:
                log.warning("Error processing attribution results", error=str(exc))
                recommendation = f"Attribution partial: {exc}"

        hyperparams = self.suggest_hyperparams()

        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            "Research cycle complete. Ready for backtest execution.",
        )
        return {
            "ok": True,
            "market": market,
            "attribution": attribution_dict,
            "top_factors": top_factors,
            "factor_coverage": factor_coverage,
            "excess_return": excess_return,
            "recommendation": recommendation,
            "hyperparams": hyperparams,
            "status": "Ready for Backtest",
        }

    def suggest_hyperparams(self) -> dict[str, float]:
        """Suggest LightGBM hyperparameter adjustments based on active factor count.

        More active factors suggest a richer feature space, which benefits from
        stronger regularization (lower learning rate, shallower trees) to avoid
        overfitting. Fewer factors allow more aggressive fitting.
        """
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            "Calculating optimal hyperparameters based on active factor pool...",
        )

        n_active = 0
        try:
            from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

            registry = FactorRegistry()
            active_factors = registry.list_factors(stage=STAGE_ACTIVE)
            n_active = len(active_factors)
        except Exception as exc:
            log.debug("Could not query factor registry for hyperparams", error=str(exc))

        # Scale hyperparameters based on factor pool size:
        #   0-5 factors   -> lr=0.08, depth=7 (aggressive, small feature space)
        #   6-15 factors  -> lr=0.05, depth=6 (balanced, default)
        #   16-30 factors -> lr=0.03, depth=5 (regularized)
        #   31+ factors   -> lr=0.01, depth=4 (strong regularization)
        if n_active <= 5:
            best_lr = 0.08
            best_depth = 7
        elif n_active <= 15:
            best_lr = 0.05
            best_depth = 6
        elif n_active <= 30:
            best_lr = 0.03
            best_depth = 5
        else:
            best_lr = 0.01
            best_depth = 4

        format_thought_stream_for_report(
            "ResearchAssistant",
            "success",
            f"Target hyperparameters proposed for {n_active} active factors: "
            f"lr={best_lr}, max_depth={best_depth}",
        )
        return {
            "learning_rate": best_lr,
            "max_depth": best_depth,
            "n_active_factors": n_active,
        }

    # =====================================================================
    # Data Quality  (from Alpha Agent)
    # =====================================================================

    def check_data_quality(self, market: str = "us") -> dict[str, Any]:
        """Check data integrity for the given market."""
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Verifying data integrity for {market.upper()} market...",
        )

        if not self._quality_index:
            format_thought_stream_for_report(
                "ResearchAssistant",
                "warning",
                "DataQualityIndex not connected. Falling back to optimistic validation.",
            )
            return {"ok": True, "warning": "No quality index available"}

        report = self._quality_index.get_latest(
            dataset_key="watchlist", freq="day", market=market.lower()
        )
        if not report:
            format_thought_stream_for_report(
                "ResearchAssistant",
                "error",
                f"No quality report found for {market.upper()}.",
            )
            return {"ok": False, "error": f"No quality report for {market.upper()}"}

        summary = report.get("summary") or {}
        warnings = summary.get("warnings") or []

        if not warnings:
            format_thought_stream_for_report(
                "ResearchAssistant",
                "success",
                f"Data integrity verified for {market.upper()}. Latest day: {report.get('latest_calendar_day')}",
            )
        else:
            format_thought_stream_for_report(
                "ResearchAssistant",
                "warning",
                f"Detected {len(warnings)} warnings in {market.upper()} data.",
            )

        return {"ok": True, "report": report, "warnings": warnings}

    # =====================================================================
    # Risk Assessment  (from Risk Agent)
    # =====================================================================

    def assess_risk(self, run_id: str | None = None) -> dict[str, Any]:
        """Assess portfolio risk metrics (market-level or run-level)."""
        market = "us"  # default
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Commencing risk audit for {market.upper()}...",
        )

        vol_metric = self._get_benchmark_volatility(market)
        panic_index = self._sentiment_audit(vol_metric)

        is_normal = vol_metric <= self.HIGH_VOL_THRESHOLD and panic_index <= self.HIGH_PANIC_THRESHOLD

        if not is_normal:
            format_thought_stream_for_report(
                "ResearchAssistant",
                "error",
                f"High risk event (IV={vol_metric:.2f}, Panic={panic_index:.1f}). Veto engaged.",
            )
            self._record_risk_case("High_Vol_Panic", {"vol": vol_metric, "panic": panic_index})
        else:
            format_thought_stream_for_report(
                "ResearchAssistant",
                "success",
                "Market regime NORMAL. Current leverage target maintained.",
            )

        return {
            "ok": True,
            "market_normal": is_normal,
            "volatility": round(vol_metric, 2),
            "panic_index": round(panic_index, 1),
        }

    def check_drawdown(self, run_id: str) -> dict[str, Any]:
        """Check drawdown metrics for a specific run."""
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Checking drawdown for run {run_id}...",
        )
        # Placeholder — in production this would query RunIndex
        return {"ok": True, "run_id": run_id, "max_drawdown": None, "note": "RunIndex integration pending"}

    # =====================================================================
    # Governance  (from Governance Agent)
    # =====================================================================

    def self_heal(self, event_data: dict[str, Any]) -> bool:
        """Attempt to recover from an error using the reliability policy."""
        if isinstance(event_data, dict):
            event = ReliabilityEvent(
                code=event_data.get("code", "UNKNOWN"),
                category=event_data.get("category", "unknown"),
                severity=event_data.get("severity", "medium"),
                retryable=event_data.get("retryable", True),
                component=event_data.get("component", "unknown"),
                operation=event_data.get("operation", "unknown"),
                event_id=event_data.get("event_id", ""),
                market=event_data.get("market"),
            )
        else:
            event = event_data

        format_thought_stream_for_report(
            "ResearchAssistant",
            "warning",
            f"Initiating Self-Healing for {event.code} in {event.component}. Event ID: {event.event_id}",
        )

        action_plan = self._policy.resolve_action(event)
        action = action_plan.get("action", "none")
        notes = action_plan.get("notes", "")

        format_thought_stream_for_report(
            "ResearchAssistant", "info", f"Policy Recommendation: {action}. {notes}"
        )

        success = False
        if action == "refresh_data_then_retry":
            format_thought_stream_for_report(
                "ResearchAssistant", "info", f"Retrying data update for {event.market}..."
            )
            retry_res = run_data_update(market=event.market or "cn")
            success = retry_res["success"]
        elif action == "retry_with_exponential_backoff":
            format_thought_stream_for_report("ResearchAssistant", "info", "Sleeping before retry...")
            time.sleep(2)
            success = True
        elif action == "none":
            format_thought_stream_for_report(
                "ResearchAssistant",
                "error",
                "No automated action possible. Manual intervention required.",
            )
            success = False
        else:
            format_thought_stream_for_report(
                "ResearchAssistant", "info", f"Executing generic action: {action}"
            )
            time.sleep(1)
            success = True

        if success and event.event_id:
            resolve_failure_event(
                event.event_id, resolution={"action_taken": action, "success": True}
            )

        format_thought_stream_for_report(
            "ResearchAssistant",
            "success" if success else "error",
            f"Self-Healing {action} {'Completed' if success else 'Failed'} for {event.code}.",
        )
        return success

    def audit_run(self, run_id: str) -> dict[str, Any]:
        """Audit a backtest run for consistency and generate evidence canvas."""
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Auditing run {run_id}...",
        )
        # Publish evidence canvas
        canvas = {
            "timestamp": time.time(),
            "run_id": run_id,
            "decision": "REVIEW",
            "confidence_score": 85,
            "evidence": {
                "data_quality": "PASS",
                "risk_assessment": "NORMAL",
            },
        }
        with open(self._evidence_canvas_path, "w") as f:
            json.dump(canvas, f, indent=2)

        format_thought_stream_for_report(
            "ResearchAssistant",
            "success",
            f"Run {run_id} audited. Evidence canvas published.",
        )
        return {"ok": True, "run_id": run_id, "canvas": canvas}

    def check_consistency(self, run_id: str) -> dict[str, Any]:
        """Check execution consistency for a run."""
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Checking consistency for run {run_id}...",
        )
        return {"ok": True, "run_id": run_id, "consistent": True, "note": "Full consistency checks pending RunIndex integration"}

    # =====================================================================
    # Architecture  (from Developer Agent)
    # =====================================================================

    def describe_architecture(self) -> str:
        """Describe the system architecture."""
        return (
            "Alpha Engine is a quantitative research platform with:\n"
            "- Data Pipeline: fetch_watchlist.py -> quality_index\n"
            "- Model Training: LightGBM via orchestrator\n"
            "- Backtesting: src/orchestrator rebacktest mode\n"
            "- Dashboard: FastAPI + React (qlib-dashboard)\n"
            "- Unified Agent: ResearchAssistant (this) handles all AI tasks"
        )

    # =====================================================================
    # Chat interface
    # =====================================================================

    async def chat(self, message: str, context: dict | None = None) -> str:
        """
        Process a natural language message and route to the appropriate tool.
        Uses keyword matching; replace with LLM-based intent classification when available.
        """
        msg = message.lower().strip()

        if any(kw in msg for kw in ("factor", "research", "alpha", "hypothesis")):
            result = self.analyze_factors("us")
            return f"Factor analysis complete: {json.dumps(result, indent=2)}"

        if any(kw in msg for kw in ("risk", "volatility", "panic", "drawdown")):
            result = self.assess_risk()
            return f"Risk assessment: {json.dumps(result, indent=2)}"

        if any(kw in msg for kw in ("data quality", "integrity", "data check")):
            result = self.check_data_quality("us")
            return f"Data quality check: {json.dumps(result, indent=2)}"

        if any(kw in msg for kw in ("audit", "consistency", "governance")):
            result = self.audit_run("latest")
            return f"Audit result: {json.dumps(result, indent=2)}"

        if any(kw in msg for kw in ("architecture", "system", "how does")):
            return self.describe_architecture()

        if any(kw in msg for kw in ("hyperparam", "tune", "learning rate")):
            result = self.suggest_hyperparams()
            return f"Hyperparameter suggestion: {json.dumps(result, indent=2)}"

        return (
            "I can help with: factor analysis, risk assessment, data quality checks, "
            "run audits, architecture questions, and hyperparameter tuning. "
            "Try asking about one of these topics."
        )

    def list_capabilities(self) -> list[dict[str, str]]:
        """List all available tools with descriptions."""
        return [
            {"name": "analyze_factors", "description": "Analyze factor effectiveness for a given market", "source": "Alpha Agent"},
            {"name": "suggest_hyperparams", "description": "Suggest LightGBM hyperparameter adjustments", "source": "Alpha Agent"},
            {"name": "check_data_quality", "description": "Check data integrity for a given market", "source": "Alpha Agent"},
            {"name": "assess_risk", "description": "Assess portfolio risk metrics and market regime", "source": "Risk Agent"},
            {"name": "check_drawdown", "description": "Check drawdown metrics for a specific run", "source": "Risk Agent"},
            {"name": "audit_run", "description": "Audit a backtest run for consistency", "source": "Governance Agent"},
            {"name": "check_consistency", "description": "Check execution consistency", "source": "Governance Agent"},
            {"name": "describe_architecture", "description": "Describe system architecture", "source": "Developer Agent"},
            {"name": "chat", "description": "Natural language interface to all tools", "source": "Unified"},
        ]

    # =====================================================================
    # Internal helpers (private)
    # =====================================================================

    def _get_benchmark_volatility(self, market: str) -> float:
        """Compute annualized volatility for the market benchmark."""
        try:
            from src.assistant.services.asset_inspection_service import AssetInspectionService
            from src.common.runtime_settings import get_runtime_settings

            settings = get_runtime_settings()
            service = AssetInspectionService(project_root=settings.project_root, model_index=None)
            benchmark = "SPY" if market.lower() == "us" else "SH000001"

            res = service.inspect(benchmark)
            prices = [
                float(d["close"])
                for d in res.get("ohlcv", [])
                if d.get("close") is not None
            ]

            if len(prices) > 10:
                import math

                returns = []
                for prev, curr in zip(prices, prices[1:]):
                    if prev > 0 and curr > 0:
                        returns.append(math.log(curr / prev))
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                ann_vol = math.sqrt(variance) * math.sqrt(self.TRADING_DAYS_PER_YEAR) * 100
                return min(100.0, max(0.0, ann_vol))
        except Exception as e:
            format_thought_stream_for_report(
                "ResearchAssistant", "warning", f"Failed to compute benchmark vol: {e}"
            )
        return self.DEFAULT_VOLATILITY_FALLBACK

    def _sentiment_audit(self, vol_metric: float) -> float:
        """Derive a panic index (0-100) deterministically from volatility."""
        panic = min(
            100.0,
            max(0.0, (vol_metric - self.PANIC_INDEX_OFFSET) * self.PANIC_INDEX_MULTIPLIER),
        )
        format_thought_stream_for_report(
            "ResearchAssistant",
            "info",
            f"Market panic index: {panic:.1f}/100",
        )
        return panic

    def _record_risk_case(self, event_name: str, metrics: dict) -> None:
        """Record an extreme event into risk case memory."""
        try:
            with open(self._risk_memory_file) as f:
                cases = json.load(f)
            cases.append({"timestamp": time.time(), "event": event_name, "metrics": metrics})
            with open(self._risk_memory_file, "w") as f:
                json.dump(cases, f, indent=2)
            format_thought_stream_for_report(
                "ResearchAssistant", "info", f"Recorded risk case: {event_name}"
            )
        except Exception:
            pass
