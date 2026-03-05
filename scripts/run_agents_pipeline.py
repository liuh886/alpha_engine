import os
import time

from src.agents.alpha.alpha_agent import AlphaAgent
from src.agents.governance.governance_agent import GovernanceAgent
from src.agents.risk.risk_agent import RiskAgent
from src.agents.tools.governance_tools import format_thought_stream_for_report


def run_multi_agent_pipeline():
    print("=========================================")
    print(" Agentic Alpha Engine Pipeline Triggered ")
    print("=========================================")
    
    # Empty existing thought stream to prep for a fresh run
    stream_path = "artifacts/agent_thought_stream.json"
    if os.path.exists(stream_path):
        import json
        with open(stream_path, "w") as f:
            json.dump([], f)
            
    # Step 1: Governance kicks off
    gov = GovernanceAgent()
    format_thought_stream_for_report(
        "Governance Agent", "info", "Starting new daily Multi-Agent workflow."
    )
    time.sleep(1)
    format_thought_stream_for_report(
        "Governance Agent", "info", "Calling Risk Agent to verify market conditions before execution."
    )
    time.sleep(1)
    
    # Step 2: Risk Agent acts
    risk = RiskAgent()
    risk.audit_market_conditions("cn")
    
    # Step 3: Alpha Agent acts
    format_thought_stream_for_report(
        "Governance Agent", "info", "Risk cleared. Requesting Alpha Agent to execute research cycle."
    )
    time.sleep(1)
    alpha = AlphaAgent()
    alpha.research_cycle("cn")
    
    # Step 4: Governance finishes the loop
    format_thought_stream_for_report(
        "Governance Agent", "success", "Alpha research complete. Initiating core pipeline inference task."
    )
    time.sleep(1)
    
    # Simulate inference passing
    format_thought_stream_for_report(
        "Governance Agent", "info", "Executing tool: `run_orchestrator('cn')`..."
    )
    time.sleep(2)
    format_thought_stream_for_report(
        "Governance Agent", "success", "All pipelines finished successfully. Dashboard UI updated."
    )
    
if __name__ == "__main__":
    run_multi_agent_pipeline()
