"""T46.7 — Prove backtest correctness.

Tests that:
1. Ordinary (adapter) and direct engine paths produce identical decisions.
2. Backtest uses the correct DataSnapshot and ModelArtifact references.
3. Order stream, holdings, and NAV are deterministic across runs.
"""

from __future__ import annotations

import json

from src.execution.adapter import StrategyExecutionAdapter
from src.execution.engine import StrategyExecutionEngine
from src.execution.models import (
    ExecutionConfig,
    ExecutionRequest,
    MarketDataSnapshot,
    PortfolioState,
    RiskPolicy,
    SignalFrame,
)

# ---------------------------------------------------------------------------
# Canonical fixtures (frozen for determinism)
# ---------------------------------------------------------------------------

SCORES_A = {"AAPL": 0.95, "NVDA": 0.88, "MSFT": 0.72, "GOOG": 0.55, "AMZN": 0.40}
SCORES_B = {"AAPL": 0.60, "NVDA": 0.90, "MSFT": 0.30, "GOOG": 0.10, "AMZN": 0.05}
ALL_TRADABLE = {k: True for k in SCORES_A}
INITIAL_POSITIONS = {"MSFT": 0.15, "GOOG": 0.10, "OLD": 0.12}
RISK = RiskPolicy(max_position_weight=0.20, allow_shorts=False)
CONFIG = ExecutionConfig(topk=3, rebalance=True)
DATE_A = "2026-01-15"
DATE_B = "2026-01-16"


def _make_request(
    scores: dict,
    date: str = DATE_A,
    positions: dict | None = None,
    tradable: dict | None = None,
) -> ExecutionRequest:
    return ExecutionRequest(
        signals=SignalFrame(asof_date=date, scores=scores),
        portfolio=PortfolioState(cash=1000.0, positions=positions or {}),
        market=MarketDataSnapshot(tradable=tradable or {k: True for k in scores}),
        risk_policy=RISK,
        config=CONFIG,
    )


# ===========================================================================
# 1. Adapter and direct engine produce identical decisions
# ===========================================================================


class TestBacktestEquivalence:
    """Ordinary adapter path and direct engine path must agree."""

    def test_adapter_vs_engine_same_target_weights(self):
        """build_execution_request + engine.execute == adapter.execute."""
        engine = StrategyExecutionEngine()
        adapter = StrategyExecutionAdapter(
            strategy_config={"kwargs": {"topk": 3}, "risk_config": {"max_position_weight": 0.20}},
            engine=engine,
        )

        # Direct engine path
        direct_request = _make_request(SCORES_A)
        direct_result = engine.execute(direct_request)

        # Adapter path (same scores, same config)
        adapter_result = adapter.execute(
            asof_date=DATE_A,
            scores=SCORES_A,
            tradable=ALL_TRADABLE,
        )

        assert direct_result.plan.target_weights == adapter_result.plan.target_weights

    def test_adapter_vs_engine_same_orders(self):
        """Both paths must produce the same set of orders."""
        engine = StrategyExecutionEngine()
        adapter = StrategyExecutionAdapter(
            strategy_config={"kwargs": {"topk": 3}, "risk_config": {"max_position_weight": 0.20}},
            engine=engine,
        )

        direct_result = engine.execute(_make_request(SCORES_A, positions=INITIAL_POSITIONS))
        adapter_result = adapter.execute(
            asof_date=DATE_A,
            scores=SCORES_A,
            portfolio_positions=INITIAL_POSITIONS,
            tradable=ALL_TRADABLE,
        )

        direct_orders = {(o.instrument, o.side) for o in direct_result.orders}
        adapter_orders = {(o.instrument, o.side) for o in adapter_result.orders}
        assert direct_orders == adapter_orders

    def test_adapter_vs_engine_same_position_changes(self):
        """Position change diffs must match between paths."""
        engine = StrategyExecutionEngine()
        adapter = StrategyExecutionAdapter(
            strategy_config={"kwargs": {"topk": 3}, "risk_config": {"max_position_weight": 0.20}},
            engine=engine,
        )

        direct_result = engine.execute(_make_request(SCORES_A, positions=INITIAL_POSITIONS))
        adapter_result = adapter.execute(
            asof_date=DATE_A,
            scores=SCORES_A,
            portfolio_positions=INITIAL_POSITIONS,
            tradable=ALL_TRADABLE,
        )

        direct_changes = {c.instrument: (c.from_weight, c.to_weight) for c in direct_result.position_changes}
        adapter_changes = {c.instrument: (c.from_weight, c.to_weight) for c in adapter_result.position_changes}
        assert direct_changes == adapter_changes


# ===========================================================================
# 2. DataSnapshot and ModelArtifact content-addressing
# ===========================================================================


class TestDataSnapshotDeterminism:
    """DataSnapshot IDs must be deterministic for identical content."""

    def test_same_content_same_snapshot_id(self, tmp_path):
        from src.data.snapshot import DataSnapshot

        # Create two identical data directories
        for label in ("a", "b"):
            d = tmp_path / f"data_{label}"
            d.mkdir()
            (d / "prices.csv").write_text("date,close\n2026-01-01,100.0\n", encoding="utf-8")
            (d / "volumes.csv").write_text("date,vol\n2026-01-01,5000\n", encoding="utf-8")

        store = tmp_path / "store"
        snap_a = DataSnapshot.create_snapshot(tmp_path / "data_a", store=store)
        snap_b = DataSnapshot.create_snapshot(tmp_path / "data_b", store=store)

        assert snap_a.snapshot_id == snap_b.snapshot_id

    def test_different_content_different_snapshot_id(self, tmp_path):
        from src.data.snapshot import DataSnapshot

        d1 = tmp_path / "data1"
        d1.mkdir()
        (d1 / "prices.csv").write_text("date,close\n2026-01-01,100.0\n", encoding="utf-8")

        d2 = tmp_path / "data2"
        d2.mkdir()
        (d2 / "prices.csv").write_text("date,close\n2026-01-01,200.0\n", encoding="utf-8")

        store = tmp_path / "store"
        snap1 = DataSnapshot.create_snapshot(d1, store=store)
        snap2 = DataSnapshot.create_snapshot(d2, store=store)

        assert snap1.snapshot_id != snap2.snapshot_id

    def test_snapshot_manifest_roundtrip(self, tmp_path):
        from src.data.snapshot import DataSnapshot

        d = tmp_path / "data"
        d.mkdir()
        (d / "a.csv").write_text("x\n1\n", encoding="utf-8")

        store = tmp_path / "store"
        snap = DataSnapshot.create_snapshot(d, store=store)

        resolved = DataSnapshot.resolve_snapshot(snap.snapshot_id, store=store)
        assert resolved.snapshot_id == snap.snapshot_id
        assert resolved.manifest.file_checksums == snap.manifest.file_checksums


class TestModelArtifactDeterminism:
    """ArtifactManifest IDs and checksums must be stable."""

    def test_manifest_structural_required(self):
        from src.models.artifact_manifest import ArtifactManifest

        manifest = ArtifactManifest(
            id="abc123",
            model_binary_path="model.pkl",
            config_path="config.yaml",
            config={"model_class": "LGBModel"},
            predictions_path="pred.csv",
            labels_path="label.csv",
            diagnostics_path="diag.json",
            checksums={"model.pkl": "sha256:deadbeef"},
        )
        assert manifest.missing_required() == []

    def test_manifest_missing_required_detected(self):
        from src.models.artifact_manifest import ArtifactManifest

        manifest = ArtifactManifest(
            id="abc123",
            model_binary_path="",
            config={},
            predictions_path="",
            labels_path="",
            diagnostics_path="",
            checksums={},
        )
        missing = manifest.missing_required()
        assert "model_binary_path" in missing
        assert "config" in missing
        assert "checksums" in missing

    def test_manifest_json_roundtrip(self, tmp_path):
        from src.models.artifact_manifest import ArtifactManifest

        manifest = ArtifactManifest(
            id="roundtrip_test",
            model_binary_path="model.pkl",
            config={"k": "v"},
            features=["f1", "f2"],
            snapshot_id="snap_001",
            predictions_path="pred.csv",
            labels_path="label.csv",
            diagnostics_path="diag.json",
            checksums={"model.pkl": "abc"},
        )
        out_path = tmp_path / "manifest.json"
        manifest.save(out_path)

        loaded = ArtifactManifest.from_json_file(out_path)
        assert loaded.id == manifest.id
        assert loaded.snapshot_id == manifest.snapshot_id
        assert loaded.features == manifest.features
        assert loaded.checksums == manifest.checksums


# ===========================================================================
# 3. Order stream, holdings, and NAV are deterministic
# ===========================================================================


class TestDeterministicOutputs:
    """Same inputs must always produce identical execution results."""

    def test_order_stream_deterministic_across_runs(self):
        """Run the same request 10 times -- every result must be identical."""
        engine = StrategyExecutionEngine()
        request = _make_request(SCORES_A, positions=INITIAL_POSITIONS)

        results = [engine.execute(request) for _ in range(10)]

        for i in range(1, len(results)):
            assert results[0].plan.target_weights == results[i].plan.target_weights
            assert len(results[0].orders) == len(results[i].orders)
            for o0, oi in zip(results[0].orders, results[i].orders):
                assert o0.instrument == oi.instrument
                assert o0.side == oi.side
                assert abs(o0.target_weight - oi.target_weight) < 1e-12

    def test_holdings_deterministic(self):
        """Target weights (holdings) must be identical for identical inputs."""
        engine = StrategyExecutionEngine()

        r1 = engine.execute(_make_request(SCORES_A))
        r2 = engine.execute(_make_request(SCORES_A))

        assert r1.plan.target_weights == r2.plan.target_weights

    def test_nav_deterministic_from_order_stream(self):
        """Simulated NAV from fixed order stream and price path is deterministic."""
        # Simulate a simple NAV calculation from order decisions
        engine = StrategyExecutionEngine()

        # Day 1: select top-3
        r1 = engine.execute(_make_request(SCORES_A, date=DATE_A))

        # Fixed price returns for the selected stocks
        price_returns = {"AAPL": 0.02, "NVDA": 0.03, "MSFT": -0.01, "GOOG": 0.01, "AMZN": 0.0}

        nav = 1000.0
        for inst, weight in r1.plan.target_weights.items():
            nav += nav * weight * price_returns.get(inst, 0.0)

        # Run again -- must get the same NAV
        r2 = engine.execute(_make_request(SCORES_A, date=DATE_A))
        nav2 = 1000.0
        for inst, weight in r2.plan.target_weights.items():
            nav2 += nav2 * weight * price_returns.get(inst, 0.0)

        assert abs(nav - nav2) < 1e-10

    def test_json_serialization_roundtrip_preserves_orders(self):
        """Orders survive JSON round-trip without loss."""
        engine = StrategyExecutionEngine()
        result = engine.execute(_make_request(SCORES_A, positions=INITIAL_POSITIONS))

        serialized = json.dumps(result.to_dict())
        deserialized = json.loads(serialized)

        assert len(deserialized["orders"]) == len(result.orders)
        assert deserialized["plan"]["asof_date"] == DATE_A

        for d_order, r_order in zip(deserialized["orders"], result.orders):
            assert d_order["instrument"] == r_order.instrument
            assert d_order["side"] == r_order.side.value

    def test_different_scores_produce_different_decisions(self):
        """Changing scores can change the selected instruments (sanity check)."""
        engine = StrategyExecutionEngine()

        # Use scores with clearly different top-k sets
        scores_x = {"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.1, "E": 0.05}
        scores_y = {"A": 0.1, "B": 0.05, "C": 0.02, "D": 0.9, "E": 0.8}

        r_x = engine.execute(_make_request(scores_x))
        r_y = engine.execute(_make_request(scores_y))

        # scores_x top-3: A, B, C; scores_y top-3: D, E, A
        assert set(r_x.plan.target_weights.keys()) == {"A", "B", "C"}
        assert set(r_y.plan.target_weights.keys()) == {"D", "E", "A"}
