import logging
from typing import Dict, Any, Callable, List, Optional
from enum import Enum

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
    Replaces spaghetti orchestrator logic with a mathematical State Machine.
    Ensures that bad data or Risk Vetoes physically block trade execution.
    """
    def __init__(self):
        self.current_state = State.INIT
        self.context: Dict[str, Any] = {}
        self.transitions: Dict[State, Callable[[], State]] = {
            State.INIT: self._init_pipeline,
            State.DATA_SYNC: self._sync_data,
            State.FEATURE_ENG: self._build_features,
            State.INFERENCE: self._run_inference,
            State.RISK_AUDIT: self._audit_risk,
            State.EXECUTION: self._execute_mock_trades
        }
        self.history: List[str] = []

    def run(self) -> Dict[str, Any]:
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
                
        return {"final_state": self.current_state.value, "context": self.context, "history": self.history}

    def _log(self, msg: str):
        self.history.append(msg)
        logging.getLogger("FSM").info(msg)

    # State Handlers
    def _init_pipeline(self) -> State:
        self.context["start_time"] = "time.now()"
        return State.DATA_SYNC

    def _sync_data(self) -> State:
        # Mocking data sync failure condition for demonstration
        if self.context.get("force_data_fail"):
            return State.HALTED
        self.context["data_synced"] = True
        return State.FEATURE_ENG
        
    def _build_features(self) -> State:
        return State.INFERENCE
        
    def _run_inference(self) -> State:
        self.context["inference_complete"] = True
        self.context["proposed_trades"] = [{"ticker": "AAPL", "weight": 0.05}]
        return State.RISK_AUDIT
        
    def _audit_risk(self) -> State:
        # If the risk agent flagged something, abort
        if self.context.get("risk_veto"):
            self._log("Risk Auditor vetoed the proposed trades!")
            return State.HALTED
        return State.EXECUTION
        
    def _execute_mock_trades(self) -> State:
        self.context["trades_executed"] = True
        return State.SUCCESS
