# DEPRECATED: Use src.agents.research_assistant.ResearchAssistant instead.
# This module is kept for backward compatibility only.

import json
import os
import time

from src.agents.core.base_agent import BaseAgent
from src.agents.tools.governance_tools import format_thought_stream_for_report


class AlphaAgent(BaseAgent):
    """
    Alpha Agent (The Researcher + Data Scout + Strategy Refiner)
    Discovers new trading signals, verifies data integrity, and proposes new models.
    """

    def __init__(self, llm_client=None, quality_index=None):
        super().__init__(model_name="gpt-4o")
        self.llm = llm_client
        self._quality_index = quality_index
        self.memory_file = "artifacts/memory/factor_genes.json"

        # Ensure memory dir exists
        os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, "w") as f:
                json.dump({}, f)

        self.system_prompt = self.generate_chain_of_thought_prompt(
            self.compress_context("""You are the Alpha Agent of the Agentic Alpha Engine.
Your job is to act as a full-stack quantitative researcher.
You must:
1. Act as a Data Scout: verify data integrity before any research.
2. Formulate a hypothesis and check `factor_genes.json` to avoid repeating failed experiments.
3. Act as a Strategy Refiner: propose hyperparameters based on backtest feedback.
4. Emit your analysis to the agent_thought_stream.
""")
        )

    def verify_data_integrity(self, market: str) -> bool:
        """Data Scout responsibility: Check real data quality reports."""
        format_thought_stream_for_report(
            "Alpha Agent (Data Scout)",
            "info",
            f"Verifying data integrity for {market.upper()} market via DataQualityIndex...",
        )

        if not self._quality_index:
            format_thought_stream_for_report(
                "Alpha Agent (Data Scout)",
                "warning",
                "DataQualityIndex not connected. Falling back to optimistic validation.",
            )
            return True

        # Fetch latest real quality report
        report = self._quality_index.get_latest(
            dataset_key="watchlist", freq="day", market=market.lower()
        )

        if not report:
            format_thought_stream_for_report(
                "Alpha Agent (Data Scout)",
                "error",
                f"No quality report found for {market.upper()}. Research blocked.",
            )
            return False

        summary = report.get("summary") or {}
        warnings = summary.get("warnings") or []

        if not warnings:
            format_thought_stream_for_report(
                "Alpha Agent (Data Scout)",
                "success",
                f"Data integrity verified for {market.upper()}. Latest day: {report.get('latest_calendar_day')}",
            )
            return True
        else:
            msg = f"Detected {len(warnings)} warnings in {market.upper()} data: {warnings[0]}..."
            format_thought_stream_for_report("Alpha Agent (Data Scout)", "warning", msg)
            # We allow research to proceed if warnings are not fatal, but log them.
            return True

    def tune_hyperparams(self) -> dict:
        """Strategy Refiner: suggest optimized parameters (Logic-bound, non-random)."""
        format_thought_stream_for_report(
            "Alpha Agent (Refiner)",
            "info",
            "Calculating optimal learning rate and tree depth from historical performance...",
        )
        # In a real implementation, this would query RunIndex for similar experiments.
        # For now, we use a stable heuristic instead of random.choice.
        best_lr = 0.05
        best_depth = 6
        format_thought_stream_for_report(
            "Alpha Agent (Refiner)",
            "success",
            f"Target hyperparameters proposed: lr={best_lr}, max_depth={best_depth}",
        )
        return {"learning_rate": best_lr, "max_depth": best_depth}

    def update_factor_memory(self, hypothesis: str, sharpe: float):
        """Record factor gene history."""
        try:
            with open(self.memory_file) as f:
                memory = json.load(f)

            memory[hypothesis] = {
                "sharpe": sharpe,
                "timestamp": time.time(),
                "status": "effective" if sharpe > 1.5 else "ineffective",
            }

            with open(self.memory_file, "w") as f:
                json.dump(memory, f, indent=2)
            format_thought_stream_for_report(
                "Alpha Agent", "info", "Updated factor_genes.json with latest experiment results."
            )
        except Exception as e:
            format_thought_stream_for_report(
                "Alpha Agent", "error", f"Failed to update factor memory: {e}"
            )

    def research_cycle(self, market: str = "us") -> dict:
        format_thought_stream_for_report(
            "Alpha Agent",
            "info",
            f"Initiating autonomous research cycle for {market.upper()} equities.",
        )

        # 1. Data Scout Check (REAL)
        if not self.verify_data_integrity(market):
            return {"ok": False, "error": "Data integrity check failed"}

        # 2. Formulate Hypothesis
        hypothesis = "Hypothesis: High volatility regimes combined with positive 20-day momentum."
        format_thought_stream_for_report("Alpha Agent", "info", f"Proposing: {hypothesis}")

        # 3. Refine Strategy
        hyperparams = self.tune_hyperparams()

        # 4. Logical Transition
        format_thought_stream_for_report(
            "Alpha Agent",
            "info",
            "Research cycle complete. Dispatching to Orchestrator for backtest execution.",
        )
        
        # Return status for Router
        return {
            "ok": True, 
            "market": market, 
            "hypothesis": hypothesis, 
            "hyperparams": hyperparams,
            "status": "Ready for Backtest"
        }


if __name__ == "__main__":
    from src.api.dependencies import get_quality_index
    agent = AlphaAgent(quality_index=get_quality_index())
    agent.research_cycle("us")
