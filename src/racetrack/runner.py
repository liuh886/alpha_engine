"""Racetrack Runner admission contract and registry.

Enforces Thesis-First gate (ThesisMissingError), closed candidate pool boundaries,
benchmark reference role isolation (UnauthorizedAssetError), and pure functional execution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os
import tempfile
import yaml

from src.racetrack.contracts import (
    EngineConfig,
    PriceMatrix,
    RebalanceEvent,
    SimulationResult,
    ThesisMissingError,
    UnauthorizedAssetError,
    LedgerOverwriteError,
    canonical_json_dumps,
)
from src.racetrack.engine import simulate_portfolio
from src.racetrack.ledger import EventLedger
from src.racetrack.pool_index import generate_pool_index_events


def create_us_pool_runner() -> RunnerContract:
    """Phase A's real, rule-bound US87 index racer; no formal/demo strategies."""
    runner_id = "us87_ew_pool_runner_v1"
    return RunnerContract(
        runner_id=runner_id,
        runner_version="1.0.0",
        pool_id="us_selected_equities_v2",
        benchmark_symbol="QQQ",
        thesis=(
            "Track the fixed US87 pool's equal-weight return under monthly rebalancing, "
            "rather than a single-name selection bet. It fails as a broad-market proxy "
            "when this selected pool is unrepresentative; missing prices and historical "
            "availability limitations remain explicit and do not establish tradability."
        ),
        selection_logic="Every declared US87 candidate retains a fixed 1/87 slot at rebalance; unavailable slots remain cash.",
        rebalance_logic="Initialize at the first replay close, then rebalance at the first observed session of each calendar month with the shared engine's friction; weights drift between rebalances.",
        events_generator=lambda matrix: generate_pool_index_events(
            matrix, "us_selected_equities_v2", runner_id=runner_id,
        ),
    )


def validate_runner_thesis(thesis: str | None) -> None:
    """Validate investment thesis substantive content.

    Raises:
        ThesisMissingError: If thesis is None, empty/whitespace, or shorter than 30 characters.
    """
    if thesis is None or not str(thesis).strip():
        raise ThesisMissingError(
            "Runner rejected: thesis cannot be empty. Every runner must have a written "
            "investment thesis explaining why it was built, what it bets on, and when it fails."
        )
    clean_thesis = str(thesis).strip()
    if len(clean_thesis) < 30:
        raise ThesisMissingError(
            f"Runner rejected: thesis is too terse ({len(clean_thesis)} chars < 30 chars threshold). "
            "Must provide a substantive written investment rationale."
        )


@dataclass
class RunnerContract:
    """Immutable competitive runner specification entity.

    Attributes:
        runner_id: Unique runner identifier (e.g. 'momentum_cross_section_v1').
        runner_version: Semantic version string (e.g. '1.0.0').
        pool_id: Declared candidate asset pool ID (e.g. 'us_selected_equities_v2').
        benchmark_symbol: Reference market benchmark (e.g. 'QQQ').
        thesis: Written investment thesis (strictly validated).
        selection_logic: Cross-sectional asset selection logic description.
        rebalance_logic: Weight allocation and rebalance schedule description.
        track_condition_associations: Market weather associations (e.g. {'VIX': 'headwind'}).
        target_symbols: Optional explicit list of assets intended for trading.
        events_generator: Optional callable to generate rebalance events.
    """

    runner_id: str
    runner_version: str
    pool_id: str
    benchmark_symbol: str
    thesis: str
    selection_logic: str
    rebalance_logic: str
    track_condition_associations: dict[str, str] = field(default_factory=dict)
    target_symbols: Sequence[str] | None = None
    events_generator: Callable[[PriceMatrix], list[RebalanceEvent]] | None = None

    def __post_init__(self) -> None:
        # Mandatory Thesis Gate: empty or < 30 chars strictly prohibited
        validate_runner_thesis(self.thesis)

        # Static benchmark reference isolation check
        if self.target_symbols is not None:
            for sym in self.target_symbols:
                if sym == self.benchmark_symbol:
                    raise UnauthorizedAssetError(
                        f"Benchmark reference '{sym}' cannot be targeted as a portfolio asset in runner '{self.runner_id}'"
                    )

    def generate_rebalance_events(self, matrix: PriceMatrix) -> list[RebalanceEvent]:
        """Generate rebalance events for the strategy given a PriceMatrix.

        Can be overridden by subclasses or provided via events_generator callable.
        """
        if self.events_generator is not None:
            return self.events_generator(matrix)
        raise NotImplementedError(
            "Subclasses must implement generate_rebalance_events or provide events_generator callable"
        )

    def run(
        self,
        matrix: PriceMatrix,
        ledger_path: Path | None = None,
        config: EngineConfig = EngineConfig(),
    ) -> SimulationResult:
        """Execute full replay simulation, write ledger if requested, and return SimulationResult.

        Raises:
            ValueError: If runner pool_id does not match matrix pool_id.
            UnauthorizedAssetError: If any targeted asset is outside matrix candidate symbols or is the benchmark.
        """
        if self.pool_id != matrix.pool_id:
            raise ValueError(
                f"Runner pool_id '{self.pool_id}' does not match matrix pool_id '{matrix.pool_id}'"
            )

        events = self.generate_rebalance_events(matrix)
        EventLedger.validate_events(events, self.runner_id, self.runner_version)

        # Closed pool and benchmark isolation verification
        for ev in events:
            for sym, weight in ev.target_weights.items():
                if weight > 0:
                    if sym == self.benchmark_symbol:
                        raise UnauthorizedAssetError(
                            f"Runner '{self.runner_id}' targeted benchmark reference symbol '{sym}'"
                        )
                    if sym not in matrix.candidate_symbols:
                        raise UnauthorizedAssetError(
                            f"Asset '{sym}' in runner '{self.runner_id}' is outside authorized candidate pool '{matrix.pool_id}'"
                        )

        # Simulation must succeed before evidence is created. Atomic no-clobber
        # linking rejects even a destination created concurrently after validation.
        result = simulate_portfolio(matrix=matrix, ledger_events=events, config=config)
        if ledger_path is not None:
            p = Path(ledger_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n", dir=p.parent, delete=False
                ) as f:
                    temporary = Path(f.name)
                    for ev in events:
                        f.write(canonical_json_dumps(ev.to_dict()) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.link(temporary, p)
                except FileExistsError as exc:
                    raise LedgerOverwriteError(f"Refusing to replace retained ledger: {p}") from exc
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

        return result


class RunnerRegistry:
    """Registry managing runner admission, whitelist verification, and batch simulation."""

    def __init__(
        self,
        pool_id: str = "us_selected_equities_v2",
        candidate_symbols: Sequence[str] | None = None,
        root_path: Path | None = None,
    ) -> None:
        self.pool_id = pool_id
        self._runners: dict[str, RunnerContract] = {}
        self.candidate_symbols: set[str] | None = None

        if candidate_symbols is not None:
            self.candidate_symbols = set(candidate_symbols)
        else:
            root = root_path or Path.cwd()
            pool_yaml = root / "configs" / "research_universes" / f"{pool_id}.yaml"
            try:
                with open(pool_yaml, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                raise ValueError(f"Failed to parse candidate pool YAML: {pool_yaml}") from exc
            if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
                raise ValueError(f"Invalid candidate pool configuration: {pool_yaml}")
            self.candidate_symbols = {str(symbol) for symbol in data["symbols"]}
        if not self.candidate_symbols:
            raise ValueError("Candidate whitelist cannot be empty; pool contains no symbols list")

    def register(self, runner: RunnerContract) -> None:
        """Register a new runner contract into the registry.

        Raises:
            ValueError: If runner_id is already registered or pool_id does not match registry pool_id.
            UnauthorizedAssetError: If runner declares target assets outside authorized pool or targets benchmark.
        """
        if runner.runner_id in self._runners:
            raise ValueError(f"Runner '{runner.runner_id}' is already registered in registry")

        if runner.pool_id != self.pool_id:
            raise ValueError(
                f"Runner pool_id '{runner.pool_id}' does not match registry pool_id '{self.pool_id}'"
            )

        # Whitelist assertion for declared target symbols
        if runner.target_symbols is not None:
            for sym in runner.target_symbols:
                if sym == runner.benchmark_symbol:
                    raise UnauthorizedAssetError(
                        f"Runner '{runner.runner_id}' targets benchmark reference symbol '{sym}'"
                    )
                if self.candidate_symbols is not None and sym not in self.candidate_symbols:
                    raise UnauthorizedAssetError(
                        f"Asset '{sym}' in runner '{runner.runner_id}' is outside authorized candidate pool '{self.pool_id}'"
                    )

        self._runners[runner.runner_id] = runner

    def get(self, runner_id: str) -> RunnerContract:
        """Retrieve registered runner by runner_id."""
        if runner_id not in self._runners:
            raise KeyError(f"Runner '{runner_id}' not found in registry")
        return self._runners[runner_id]

    def list_runners(self) -> list[RunnerContract]:
        """List all currently registered runners."""
        return list(self._runners.values())

    def evaluate_all(
        self,
        matrix: PriceMatrix,
        ledgers_dir: Path | None = None,
        config: EngineConfig = EngineConfig(),
    ) -> dict[str, SimulationResult]:
        """Evaluate all registered runners over the given PriceMatrix.

        Args:
            matrix: Aligned PriceMatrix.
            ledgers_dir: Optional directory to persist generated JSONL event ledgers.
            config: EngineConfig parameters.

        Returns:
            Dictionary mapping runner_id -> SimulationResult.
        """
        if matrix.pool_id != self.pool_id:
            raise ValueError(
                f"PriceMatrix pool_id '{matrix.pool_id}' does not match registry pool_id '{self.pool_id}'"
            )

        if self.candidate_symbols is None:
            self.candidate_symbols = set(matrix.candidate_symbols)

        results: dict[str, SimulationResult] = {}
        for runner_id, runner in self._runners.items():
            l_path = (Path(ledgers_dir) / f"{runner_id}.jsonl") if ledgers_dir is not None else None
            results[runner_id] = runner.run(matrix=matrix, ledger_path=l_path, config=config)

        return results
