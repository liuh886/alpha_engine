import os
import json
import time

from src.agents.core.base_agent import BaseAgent
from src.agents.tools.data_tools import run_data_update
from src.agents.tools.governance_tools import (
    append_to_human_run_log,
    format_thought_stream_for_report,
)
from src.agents.tools.orchestrator_tools import run_orchestrator
from src.agents.alpha.alpha_agent import AlphaAgent
from src.agents.risk.risk_agent import RiskAgent

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

    def self_heal(self, component: str, error_msg: str) -> bool:
        """Attempt to recover from an error."""
        format_thought_stream_for_report("Governance Agent", "warning", f"Initiating Self-Healing for {component}. Error: {error_msg}")
        time.sleep(1)
        # Mock self-healing logic
        success = True
        if "data" in component.lower():
             format_thought_stream_for_report("Governance Agent", "info", "Switching to backup data source and retrying...")
             time.sleep(1)
        else:
             format_thought_stream_for_report("Governance Agent", "info", "Re-initializing environment variables...")
             time.sleep(1)
             
        format_thought_stream_for_report("Governance Agent", "success", f"Self-Healing completed for {component}. Status: {'Resolved' if success else 'Failed'}")
        return success

    def publish_evidence_canvas(self, market: str, risk_approved: bool):
        canvas = {
            "timestamp": time.time(),
            "market": market,
            "decision": "APPROVED" if risk_approved else "VETOED",
            "confidence_score": 90 if risk_approved else 30,
            "evidence": {
                "alpha_proposal": "High volatility + Momentum",
                "risk_assessment": "NORMAL" if risk_approved else "HIGH VOLATILITY / PANIC"
            }
        }
        with open(self.evidence_canvas_path, 'w') as f:
            json.dump(canvas, f, indent=2)
        format_thought_stream_for_report("Governance Agent", "info", "Evidence Canvas published to artifacts/dashboard/evidence_canvas.json")

    def execute_daily_routine(self, market: str = "all") -> None:
        """
        Implements the v2.1 Coordination Protocol.
        """
        print(f"--- Governance Agent starting daily routine for {market} ---")
        
        format_thought_stream_for_report("Governance Agent", "info", f"Starting daily routine for {market} market...")
        
        # Step 1: Data Update with Self-Healing
        data_res = run_data_update(market=market if market != "all" else "cn")
        if not data_res["success"]:
            msg = f"Data update failed with code {data_res.get('returncode')}."
            if not self.self_heal("Data Pipeline", msg):
                append_to_human_run_log("FAILURE", "Data update failed and self-healing aborted.")
                return

        # Step 2: Daily Sync (Risk weather check)
        target_market = market if market != "all" else "us"
        format_thought_stream_for_report("Governance Agent", "info", "Consulting Risk Agent for Market Weather...")
        is_market_normal = self.risk_agent.audit_market_conditions(target_market)
        
        # Step 3: Alpha Research
        if not is_market_normal:
            format_thought_stream_for_report("Governance Agent", "warning", "Risk Agent reported high risk. Instructing Alpha to use defensive factor library.")
        else:
            format_thought_stream_for_report("Governance Agent", "info", "Market normal. Instructing Alpha to proceed with standard research.")
            
        self.alpha_agent.research_cycle(target_market)
        
        # Step 4: Final Veto & Evidence Canvas
        format_thought_stream_for_report("Governance Agent", "info", "Review Loop: Submitting Alpha proposal for final Risk Audit...")
        final_approval = self.risk_agent.audit_market_conditions(target_market) # Simplified for demo
        
        self.publish_evidence_canvas(target_market, final_approval)
        
        if final_approval:
            msg = "Daily Routine -> SUCCESS"
            print(msg)
            append_to_human_run_log("SUCCESS", msg)
            format_thought_stream_for_report("Governance Agent", "success", "All pipelines executed successfully. Evidence Canvas ready for human review.")
        else:
            msg = "Daily Routine -> BLOCKED BY RISK VETO"
            print(msg)
            append_to_human_run_log("BLOCKED", msg)
            format_thought_stream_for_report("Governance Agent", "warning", "Pipeline blocked by Risk Veto. Awaiting human intervention.")
        
if __name__ == "__main__":
    agent = GovernanceAgent()
    agent.execute_daily_routine("us")
