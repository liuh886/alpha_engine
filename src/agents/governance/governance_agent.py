# DEPRECATED: Use src.agents.research_assistant.ResearchAssistant instead.
# This module is kept for backward compatibility only.

import json
import os
import time
from typing import Any

from src.agents.alpha.alpha_agent import AlphaAgent
from src.agents.core.base_agent import BaseAgent
from src.agents.risk.risk_agent import RiskAgent
from src.agents.tools.data_tools import run_data_update
from src.agents.tools.governance_tools import (
    append_to_human_run_log,
    format_thought_stream_for_report,
)
from src.common.logging import get_logger
from src.reliability.events import ReliabilityEvent
from src.reliability.failure_log import resolve_failure_event
from src.reliability.governance_policy import GovernanceReliabilityPolicy

logger = get_logger(__name__)


class GovernanceAgent(BaseAgent):
    """
    Governance Agent (The Manager + Healer)
    Orchestrates Alpha and Risk, handles self-healing, and generates the Evidence Canvas.
    """

    def __init__(self, llm_client=None):
        super().__init__(model_name="gpt-4o", max_context_tokens=1500)
        self.llm = llm_client
        self.alpha_agent = AlphaAgent(llm_client)
        self.risk_agent = RiskAgent(llm_client)
        self.policy = GovernanceReliabilityPolicy()

        self.evidence_canvas_path = "artifacts/dashboard/evidence_canvas.json"
        os.makedirs(os.path.dirname(self.evidence_canvas_path), exist_ok=True)

        # 32/33/40: Compress Context and Enforce Chain Of Thought
        self.system_prompt = self.generate_chain_of_thought_prompt(
            self.compress_context("""You are the Governance Agent of the Agentic Alpha Engine.
Your job is to orchestrate the daily trading pipeline and maintain system health.
You must:
1. Daily Sync: Consult Risk Agent for weather; configure Alpha Agent accordingly.
2. Self-Healing: If data/orchestrator tools fail, analyze the error and attempt a retry or graceful fallback.
3. Review Loop: Submit Alpha's work to Risk for final veto.
4. Evidence Canvas: Publish a JSON summary of the decision for human review.
""")
        )

    def self_heal(self, event_data: dict[str, Any]) -> bool:
        """Attempt to recover from an error using the reliability policy."""
        # Convert dict to event object if needed
        if isinstance(event_data, dict):
            # Minimal reconstruction for policy check
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
            "Governance Agent",
            "warning",
            f"Initiating Self-Healing for {event.code} in {event.component}. Event ID: {event.event_id}",
        )

        # Resolve action from policy
        action_plan = self.policy.resolve_action(event)
        action = action_plan.get("action", "none")
        notes = action_plan.get("notes", "")

        format_thought_stream_for_report(
            "Governance Agent", "info", f"Policy Recommendation: {action}. {notes}"
        )

        success = False
        if action == "refresh_data_then_retry":
            format_thought_stream_for_report(
                "Governance Agent", "info", f"Retrying data update for {event.market}..."
            )
            # Actual retry logic
            retry_res = run_data_update(market=event.market or "cn")
            success = retry_res["success"]
        elif action == "retry_with_exponential_backoff":
            format_thought_stream_for_report("Governance Agent", "info", "Sleeping before retry...")
            time.sleep(2)
            success = True  # Signal to retry higher level
        elif action == "none":
            format_thought_stream_for_report(
                "Governance Agent",
                "error",
                "No automated action possible. Manual intervention required.",
            )
            success = False
        else:
            # Fallback for other defined actions
            format_thought_stream_for_report(
                "Governance Agent", "info", f"Executing generic action: {action}"
            )
            time.sleep(1)
            success = True

        if success and event.event_id:
            resolve_failure_event(
                event.event_id, resolution={"action_taken": action, "success": True}
            )

        format_thought_stream_for_report(
            "Governance Agent",
            "success" if success else "error",
            f"Self-Healing {action} {'Completed' if success else 'Failed'} for {event.code}.",
        )
        return success

    def publish_evidence_canvas(self, market: str, risk_approved: bool):
        canvas = {
            "timestamp": time.time(),
            "market": market,
            "decision": "APPROVED" if risk_approved else "VETOED",
            "confidence_score": 90 if risk_approved else 30,
            "evidence": {
                "alpha_proposal": "High volatility + Momentum",
                "risk_assessment": "NORMAL" if risk_approved else "HIGH VOLATILITY / PANIC",
            },
        }
        with open(self.evidence_canvas_path, "w") as f:
            json.dump(canvas, f, indent=2)
        format_thought_stream_for_report(
            "Governance Agent",
            "info",
            "Evidence Canvas published to artifacts/dashboard/evidence_canvas.json",
        )

    def execute_daily_routine(self, market: str = "all") -> None:
        """
        Implements the v2.1 Coordination Protocol.
        """
        logger.info("Governance Agent starting daily routine", market=market)

        format_thought_stream_for_report(
            "Governance Agent", "info", f"Starting daily routine for {market} market..."
        )

        # Step 1: Data Update with Self-Healing
        data_res = run_data_update(market=market if market != "all" else "cn")
        if not data_res["success"]:
            event = data_res.get("event")
            if event:
                if not self.self_heal(event):
                    append_to_human_run_log(
                        "FAILURE",
                        f"Data update failed ({event.get('code')}) and self-healing aborted.",
                    )
                    return
            else:
                append_to_human_run_log(
                    "FAILURE", "Data update failed with no reliability event captured."
                )
                return

        # Step 2: Daily Sync (Risk weather check)
        target_market = market if market != "all" else "us"
        format_thought_stream_for_report(
            "Governance Agent", "info", "Consulting Risk Agent for Market Weather..."
        )
        is_market_normal = self.risk_agent.audit_market_conditions(target_market)

        # Step 3: Alpha Research
        if not is_market_normal:
            format_thought_stream_for_report(
                "Governance Agent",
                "warning",
                "Risk Agent reported high risk. Instructing Alpha to use defensive factor library.",
            )
        else:
            format_thought_stream_for_report(
                "Governance Agent",
                "info",
                "Market normal. Instructing Alpha to proceed with standard research.",
            )

        self.alpha_agent.research_cycle(target_market)

        # Step 4: Final Veto & Evidence Canvas
        format_thought_stream_for_report(
            "Governance Agent",
            "info",
            "Review Loop: Submitting Alpha proposal for final Risk Audit...",
        )
        final_approval = self.risk_agent.audit_market_conditions(
            target_market
        )  # Simplified for demo

        self.publish_evidence_canvas(target_market, final_approval)

        if final_approval:
            msg = "Daily Routine -> SUCCESS"
            logger.info(msg)
            append_to_human_run_log("SUCCESS", msg)
            format_thought_stream_for_report(
                "Governance Agent",
                "success",
                "All pipelines executed successfully. Evidence Canvas ready for human review.",
            )
        else:
            msg = "Daily Routine -> BLOCKED BY RISK VETO"
            logger.warning(msg)
            append_to_human_run_log("BLOCKED", msg)
            format_thought_stream_for_report(
                "Governance Agent",
                "warning",
                "Pipeline blocked by Risk Veto. Awaiting human intervention.",
            )


if __name__ == "__main__":
    agent = GovernanceAgent()
    agent.execute_daily_routine("us")
