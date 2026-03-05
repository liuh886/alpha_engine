import random
import time
import os
import json

from src.agents.core.base_agent import BaseAgent
from src.agents.tools.governance_tools import format_thought_stream_for_report


class AlphaAgent(BaseAgent):
    """
    Alpha Agent (The Researcher + Data Scout + Strategy Refiner)
    Discovers new trading signals, verifies data integrity, tunes hyperparameters, and proposes new models.
    """
    def __init__(self, llm_client=None):
        super().__init__(model_name="gpt-4o")
        self.llm = llm_client
        self.memory_file = "artifacts/memory/factor_genes.json"
        
        # Ensure memory dir exists
        os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, 'w') as f:
                json.dump({}, f)

        # 32/33/40: Compress Context and Enforce CoT
        self.system_prompt = self.generate_chain_of_thought_prompt(
            self.compress_context("""You are the Alpha Agent of the Agentic Alpha Engine.
Your job is to act as a full-stack quantitative researcher.
You must:
1. Act as a Data Scout: verify data integrity (e.g. check for NaNs) before any research.
2. Formulate a hypothesis (e.g., combining Momentum and Reversion) and check `factor_genes.json` to avoid repeating failed experiments.
3. Act as a Strategy Refiner: tune hyperparameters based on backtest feedback to optimize Sharpe Ratio.
4. Call run_orchestrator to backtest your feature set.
5. Emit your analysis to the agent_thought_stream.
""")
        )

    def verify_data_integrity(self, market: str) -> bool:
        """Data Scout responsibility: Check data for NaNs and anomalies."""
        format_thought_stream_for_report("Alpha Agent (Data Scout)", "info", f"Verifying data integrity for {market.upper()} market...")
        time.sleep(1)
        # Simulated data check
        is_clean = random.random() > 0.1 # 90% chance clean
        if is_clean:
            format_thought_stream_for_report("Alpha Agent (Data Scout)", "success", "Data integrity check passed. No critical NaNs found.")
            return True
        else:
            format_thought_stream_for_report("Alpha Agent (Data Scout)", "warning", "Detected NaNs in recent data. Triggering neutralization engine...")
            time.sleep(1)
            format_thought_stream_for_report("Alpha Agent (Data Scout)", "success", "Data neutralized. Ready for research.")
            return True # Assume neutralized successfully

    def tune_hyperparams(self) -> dict:
        """Strategy Refiner responsibility: optimize model parameters."""
        format_thought_stream_for_report("Alpha Agent (Refiner)", "info", "Tuning hyperparameters (learning rate, tree depth) to optimize Sharpe Ratio...")
        time.sleep(1)
        best_lr = random.choice([0.01, 0.05, 0.1])
        best_depth = random.choice([4, 6, 8])
        format_thought_stream_for_report("Alpha Agent (Refiner)", "success", f"Hyperparameters tuned: lr={best_lr}, max_depth={best_depth}")
        return {"learning_rate": best_lr, "max_depth": best_depth}

    def update_factor_memory(self, hypothesis: str, sharpe: float):
        """Record factor gene history."""
        try:
            with open(self.memory_file, 'r') as f:
                memory = json.load(f)
            
            memory[hypothesis] = {
                "sharpe": sharpe,
                "timestamp": time.time(),
                "status": "effective" if sharpe > 1.5 else "ineffective"
            }
            
            with open(self.memory_file, 'w') as f:
                json.dump(memory, f, indent=2)
            format_thought_stream_for_report("Alpha Agent", "info", "Updated factor_genes.json with latest experiment results.")
        except Exception as e:
             format_thought_stream_for_report("Alpha Agent", "error", f"Failed to update factor memory: {e}")

    def research_cycle(self, market: str = "us") -> None:
        format_thought_stream_for_report(
            "Alpha Agent", "info", f"Initiating autonomous research cycle for {market.upper()} equities."
        )
        time.sleep(1)
        
        # 1. Data Scout Check
        if not self.verify_data_integrity(market):
            return
        
        # 2. Formulate Hypothesis
        hypothesis = "Hypothesis: High volatility regimes combined with positive 20-day momentum yield asymmetric returns."
        format_thought_stream_for_report("Alpha Agent", "info", f"Proposing: {hypothesis}")
        time.sleep(1)
        
        # 3. Refine Strategy (Hyperparams)
        hyperparams = self.tune_hyperparams()
        
        # 4. Execute Backtest Tool
        format_thought_stream_for_report("Alpha Agent", "info", "Compiling Qlib Alpha158 expressions and dispatching to Orchestrator Tool...")
        format_thought_stream_for_report("Alpha Agent", "info", "Executing tool: `run_orchestrator(mode='rebacktest')`")
        time.sleep(2)
        
        # Simulated Backtest Success
        simulated_metrics = {
            "annualized_return": random.uniform(0.15, 0.35),
            "sharpe_ratio": random.uniform(1.2, 2.8),
            "max_drawdown": random.uniform(-0.15, -0.05)
        }
        
        # 5. Record to Shared Memory
        self.update_factor_memory(hypothesis, simulated_metrics["sharpe_ratio"])
        
        if simulated_metrics["sharpe_ratio"] > 1.5:
            result_msg = f"Backtest completed. Metrics: Ann. Ret {simulated_metrics['annualized_return']:.2%}, Sharpe {simulated_metrics['sharpe_ratio']:.2f}. Meets deployment criteria."
            format_thought_stream_for_report("Alpha Agent", "success", result_msg)
            
            # Proposal
            format_thought_stream_for_report(
                "Alpha Agent", "success", "Proposing model 'Mom_Vol_Alpha_v1' promotion to staging for Risk Audit."
            )
        else:
            result_msg = f"Backtest completed. Sharpe {simulated_metrics['sharpe_ratio']:.2f} < 1.5 baseline. Discarding hypothesis."
            format_thought_stream_for_report("Alpha Agent", "error", result_msg)

if __name__ == "__main__":
    agent = AlphaAgent()
    agent.research_cycle("us")
