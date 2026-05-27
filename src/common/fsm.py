from collections.abc import Callable
from enum import Enum
from typing import Any

from src.common.logging import get_logger


class State(Enum):
    INIT = "INIT"
    DATA_SYNC = "DATA_SYNC"
    FEATURE_ENG = "FEATURE_ENG"
    INFERENCE = "INFERENCE"
    RISK_AUDIT = "RISK_AUDIT"
    EXECUTION = "EXECUTION"
    HALTED = "HALTED"
    SUCCESS = "SUCCESS"


class TradingFSM:
    """
    Roadmap Item [2/3] FSM-driven Workflows
    Replaces orchestrator logic with a mathematical State Machine.
    
    NOTE: Currently in STUB/DESIGN phase. 
    Methods prefixed with '_execute_mock' or returning static context 
    are placeholders for future integration with low-latency execution engines.
    """

    def __init__(self):
        self.current_state = State.INIT
        self.context: dict[str, Any] = {}
        self.transitions: dict[State, Callable[[], State]] = {
            State.INIT: self._init_pipeline,
            State.DATA_SYNC: self._sync_data,
            State.FEATURE_ENG: self._build_features,
            State.INFERENCE: self._run_inference,
            State.RISK_AUDIT: self._audit_risk,
            State.EXECUTION: self._execute_mock_trades,
        }
        self.history: list[str] = []

    def run(self) -> dict[str, Any]:
        """Executes the FSM loop until terminal state."""
        self._log(f"Starting pipeline from {self.current_state.value}")

        while self.current_state not in [State.SUCCESS, State.HALTED]:
            handler = self.transitions.get(self.current_state)
            if not handler:
                self._log(f"No handler for state {self.current_state}! Halting.")
                self.current_state = State.HALTED
                break

            try:
                next_state = handler()
                self._log(f"Transition: {self.current_state.value} -> {next_state.value}")
                self.current_state = next_state
            except Exception as e:
                self._log(f"CRITICAL ERROR in {self.current_state.value}: {e}")
                self.current_state = State.HALTED
                self.context["error"] = str(e)

        return {
            "final_state": self.current_state.value,
            "context": self.context,
            "history": self.history,
        }

    def _log(self, msg: str):
        self.history.append(msg)
        get_logger("FSM").info(msg)

    # State Handlers
    def _init_pipeline(self) -> State:
        self.context["start_time"] = "time.now()"
        return State.DATA_SYNC

    def _sync_data(self) -> State:
        # FUTURE: Integrate with DataService.check_readiness()
        if self.context.get("force_data_fail"):
            return State.HALTED
        self.context["data_synced"] = True
        return State.FEATURE_ENG

    def _build_features(self) -> State:
        # FUTURE: Trigger Qlib feature engineering pipeline
        return State.INFERENCE

    def _run_inference(self) -> State:
        # FUTURE: Load RECOMMENDED model and generate real-time signal
        self.context["inference_complete"] = True
        self.context["proposed_trades"] = []  # Placeholder
        return State.RISK_AUDIT

    def _audit_risk(self) -> State:
        # FUTURE: Integrate with RiskAgent.audit_market_conditions()
        if self.context.get("risk_veto"):
            self._log("Risk Auditor vetoed the proposed trades!")
            return State.HALTED
        return State.EXECUTION

    def _execute_mock_trades(self) -> State:
        # NOTE: This remains MOCK until Paper Trading engine is ready.
        self.context["trades_executed"] = True
        return State.SUCCESS
