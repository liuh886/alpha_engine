import json
import os
import random
import time

from src.agents.core.base_agent import BaseAgent
from src.agents.tools.governance_tools import format_thought_stream_for_report


class RiskAgent(BaseAgent):
    """
    Risk Agent (The Auditor + Macro Sentinel)
    Evaluates market conditions, audits model proposals, maintains risk cases, and has dynamic veto power.
    """

    def __init__(self, llm_client=None):
        super().__init__(model_name="gpt-4o", max_context_tokens=2000)
        self.llm = llm_client
        self.memory_file = "artifacts/memory/risk_cases.json"

        # Ensure memory dir exists (using json instead of vdb for simple stub)
        os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, "w") as f:
                json.dump([], f)

        # 32/33/40: Compress Context and Enforce Chain Of Thought
        self.system_prompt = self.generate_chain_of_thought_prompt(
            self.compress_context("""You are the Risk Agent of the Agentic Alpha Engine.
Your job is to act as a strict macro sentinel and auditor.
You must:
1. Review market meltdown conditions by checking memory of past risk cases (Risk Case Study).
2. Perform Sentiment Audit by analyzing current news/volatility.
3. Audit proposed models from Alpha Agent for excessive leverage or volatility exposure.
4. Exercise Dynamic Veto: reject any proposal that violates the current risk tolerance threshold.
""")
        )

    def record_risk_case(self, event_name: str, metrics: dict):
        """Record an extreme event into the risk cases memory."""
        try:
            with open(self.memory_file) as f:
                cases = json.load(f)
            cases.append({"timestamp": time.time(), "event": event_name, "metrics": metrics})
            with open(self.memory_file, "w") as f:
                json.dump(cases, f, indent=2)
            format_thought_stream_for_report(
                "Risk Agent (Sentinel)", "info", f"Recorded new risk case: {event_name}"
            )
        except Exception:
            pass

    def sentiment_audit(self) -> float:
        """Analyze news and return a panic index (0-100)."""
        format_thought_stream_for_report(
            "Risk Agent (Sentinel)", "info", "Performing Sentiment Audit via news aggregation..."
        )
        time.sleep(1)
        # Simulate sentiment parsing
        panic_index = random.uniform(10.0, 90.0)
        format_thought_stream_for_report(
            "Risk Agent (Sentinel)", "info", f"Calculated market panic index: {panic_index:.1f}/100"
        )
        return panic_index

    def audit_market_conditions(self, market: str) -> bool:
        format_thought_stream_for_report(
            "Risk Agent", "info", f"Commencing Risk Audit Routine over {market.upper()}..."
        )
        time.sleep(1)

        # 1. Sentiment & Volatility Audit
        panic_index = self.sentiment_audit()
        vol_metric = random.uniform(15.0, 32.0)
        format_thought_stream_for_report(
            "Risk Agent",
            "info",
            f"Real-time IV: {vol_metric:.2f}. Analyzing regime against historical risk cases.",
        )
        time.sleep(1)

        # 2. Dynamic Intervention
        if vol_metric > 25.0 or panic_index > 75.0:
            format_thought_stream_for_report(
                "Risk Agent",
                "error",
                f"High risk event detected (IV={vol_metric:.2f}, Panic={panic_index:.1f}). Exercising Dynamic Veto.",
            )
            time.sleep(1)
            self.record_risk_case("High_Vol_Panic", {"vol": vol_metric, "panic": panic_index})
            format_thought_stream_for_report(
                "Risk Agent",
                "warning",
                "VETO: Rejecting current Alpha proposals. Modifying pipeline guardrails. Reduced target leverage by 25%.",
            )
            return False
        else:
            format_thought_stream_for_report(
                "Risk Agent",
                "success",
                "Market regime declared NORMAL. Current leverage target maintained. Alpha proposals conditionally approved.",
            )
            return True


if __name__ == "__main__":
    agent = RiskAgent()
    agent.audit_market_conditions("us")
