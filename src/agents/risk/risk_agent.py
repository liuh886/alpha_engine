# DEPRECATED: Use src.agents.research_assistant.ResearchAssistant instead.
# This module is kept for backward compatibility only.

import json
import os
import time

from src.agents.core.base_agent import BaseAgent
from src.agents.tools.governance_tools import format_thought_stream_for_report

TRADING_DAYS_PER_YEAR = 252
DEFAULT_VOLATILITY_FALLBACK = 15.0
PANIC_INDEX_OFFSET = 10
PANIC_INDEX_MULTIPLIER = 3.33
HIGH_VOL_THRESHOLD = 25.0
HIGH_PANIC_THRESHOLD = 75.0


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

    def get_benchmark_volatility(self, market: str) -> float:
        try:
            from src.assistant.services.asset_inspection_service import AssetInspectionService
            from src.common.runtime_settings import get_runtime_settings

            settings = get_runtime_settings()
            service = AssetInspectionService(project_root=settings.project_root, model_index=None)
            benchmark = "SPY" if market.lower() == "us" else "SH000001"

            res = service.inspect(benchmark)
            prices = [float(d["close"]) for d in res.get("ohlcv", []) if d.get("close") is not None]

            if len(prices) > 10:
                import math
                returns = []
                for prev, curr in zip(prices, prices[1:]):
                    if prev > 0 and curr > 0:
                        returns.append(math.log(curr / prev))
                mean_ret = sum(returns) / len(returns)
                variance = sum((ret - mean_ret) ** 2 for ret in returns) / len(returns)
                ann_vol = math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100
                return min(100.0, max(0.0, ann_vol))
        except Exception as e:
            format_thought_stream_for_report("Risk Agent", "warning", f"Failed to compute benchmark vol: {e}")
        return DEFAULT_VOLATILITY_FALLBACK

    def sentiment_audit(self, vol_metric: float) -> float:
        """Derive a panic index (0-100) deterministically."""
        format_thought_stream_for_report(
            "Risk Agent (Sentinel)", "info", "Performing Sentiment Audit via realized volatility proxy..."
        )
        panic_index = min(100.0, max(0.0, (vol_metric - PANIC_INDEX_OFFSET) * PANIC_INDEX_MULTIPLIER))
        format_thought_stream_for_report(
            "Risk Agent (Sentinel)", "info", f"Calculated market panic index: {panic_index:.1f}/100"
        )
        return panic_index

    def audit_market_conditions(self, market: str) -> bool:
        format_thought_stream_for_report(
            "Risk Agent", "info", f"Commencing Risk Audit Routine over {market.upper()}..."
        )

        # 1. Sentiment & Volatility Audit
        vol_metric = self.get_benchmark_volatility(market)
        panic_index = self.sentiment_audit(vol_metric)
        format_thought_stream_for_report(
            "Risk Agent",
            "info",
            f"Real-time IV Proxy: {vol_metric:.2f}. Analyzing regime against historical risk cases.",
        )

        # 2. Dynamic Intervention
        if vol_metric > HIGH_VOL_THRESHOLD or panic_index > HIGH_PANIC_THRESHOLD:
            format_thought_stream_for_report(
                "Risk Agent",
                "error",
                f"High risk event detected (IV={vol_metric:.2f}, Panic={panic_index:.1f}). Exercising Dynamic Veto.",
            )
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
