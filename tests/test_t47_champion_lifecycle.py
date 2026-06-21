"""T47.1: Champion/Challenger lifecycle management tests.

Verify:
- One Champion per market
- Challenger evaluation against Champion
- Atomic promotion (failed promotion leaves Champion unchanged)
- Rollback to previous Champion
- History tracking
- Evidence binding enforcement
"""

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path():
    """Temporary SQLite database for isolated tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def registry_with_models(db_path):
    """Populate a ModelRegistryIndex with test model versions."""
    from src.assistant.model_registry_index import ModelRegistryIndex

    idx = ModelRegistryIndex(db_path=db_path)

    # Model 1: STAGING, good metrics
    idx.upsert_entry(
        {
            "id": "mv_champion_v1",
            "tag": "cn_lgbm_v1",
            "name": "CN LGBM v1",
            "market": "cn",
            "model_type": "lgbm",
            "stage": "RECOMMENDED",
            "artifact_id": "art_champion_v1",
            "data_snapshot_id": "snap_20260601",
            "walk_forward": {"gate_passed": True, "ic_ir": 0.5, "mean_ic": 0.04},
            "inference_passed": True,
            "backtest": {
                "metrics": {
                    "excess_return_with_cost": 0.25,
                    "annualized_return": 0.30,
                    "max_drawdown": -0.15,
                    "information_ratio": 1.2,
                }
            },
        }
    )

    # Model 2: STAGING, better metrics (potential challenger)
    idx.upsert_entry(
        {
            "id": "mv_challenger_v2",
            "tag": "cn_lgbm_v2",
            "name": "CN LGBM v2",
            "market": "cn",
            "model_type": "lgbm",
            "stage": "RECOMMENDED",
            "artifact_id": "art_challenger_v2",
            "data_snapshot_id": "snap_20260601",
            "walk_forward": {"gate_passed": True, "ic_ir": 0.6, "mean_ic": 0.05},
            "inference_passed": True,
            "backtest": {
                "metrics": {
                    "excess_return_with_cost": 0.35,
                    "annualized_return": 0.40,
                    "max_drawdown": -0.10,
                    "information_ratio": 1.5,
                }
            },
        }
    )

    # Model 3: CANDIDATE, not gate-passed
    idx.upsert_entry(
        {
            "id": "mv_candidate",
            "tag": "cn_lgbm_candidate",
            "name": "CN LGBM Candidate",
            "market": "cn",
            "model_type": "lgbm",
            "stage": "CANDIDATE",
            "artifact_id": "art_candidate",
            "walk_forward": {"gate_passed": False},
            "backtest": {"metrics": {"excess_return_with_cost": 0.10}},
        }
    )

    # Model 4: STAGING but worse metrics (should fail challenge)
    idx.upsert_entry(
        {
            "id": "mv_worse",
            "tag": "cn_lgbm_worse",
            "name": "CN LGBM Worse",
            "market": "cn",
            "model_type": "lgbm",
            "stage": "STAGING",
            "artifact_id": "art_worse",
            "data_snapshot_id": "snap_20260601",
            "walk_forward": {"gate_passed": True, "ic_ir": 0.35, "mean_ic": 0.02},
            "backtest": {
                "metrics": {
                    "excess_return_with_cost": 0.05,
                    "annualized_return": 0.08,
                    "max_drawdown": -0.30,
                    "information_ratio": 0.3,
                }
            },
        }
    )

    yield idx


# ---------------------------------------------------------------------------
# Champion declaration
# ---------------------------------------------------------------------------


def test_declare_champion_requires_staging_or_recommended(db_path, registry_with_models):
    """Cannot declare a CANDIDATE model as Champion."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models  # inject pre-populated registry

    with pytest.raises(ValueError, match="cannot be declared Champion"):
        mgr.declare_champion("cn", "mv_candidate")


def test_declare_champion_succeeds_for_recommended(db_path, registry_with_models):
    """A RECOMMENDED model can be declared Champion."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    record = mgr.declare_champion("cn", "mv_champion_v1", reason="Initial champion")
    assert record.market == "cn"
    assert record.model_version_id == "mv_champion_v1"
    assert record.artifact_id == "art_champion_v1"

    # Verify it's stored
    champion = mgr.get_champion("cn")
    assert champion is not None
    assert champion.model_version_id == "mv_champion_v1"


def test_declare_champion_supersedes_previous(db_path, registry_with_models):
    """Declaring a new Champion supersedes the old one."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1", reason="First")
    mgr.declare_champion("cn", "mv_challenger_v2", reason="Replacement")

    champion = mgr.get_champion("cn")
    assert champion.model_version_id == "mv_challenger_v2"
    assert champion.previous_champion_id == "mv_champion_v1"


def test_declare_champion_rejects_nonexistent_model(db_path):
    """Cannot declare a nonexistent model as Champion."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)

    with pytest.raises(ValueError, match="Model version not found"):
        mgr.declare_champion("cn", "nonexistent_id")


# ---------------------------------------------------------------------------
# Challenger evaluation
# ---------------------------------------------------------------------------


def test_evaluate_challenger_passes_better_metrics(db_path, registry_with_models):
    """A challenger with better metrics passes evaluation."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1")

    result = mgr.evaluate_challenger("cn", "mv_challenger_v2")
    assert result.passed is True
    assert len(result.failure_reasons) == 0
    assert len(result.comparison_details) > 0


def test_evaluate_challenger_fails_worse_metrics(db_path, registry_with_models):
    """A challenger with worse metrics fails evaluation."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1")

    result = mgr.evaluate_challenger("cn", "mv_worse")
    assert result.passed is False
    assert len(result.failure_reasons) > 0


def test_evaluate_challenger_passes_when_no_champion(db_path, registry_with_models):
    """When no Champion exists, any valid challenger auto-passes."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    result = mgr.evaluate_challenger("cn", "mv_champion_v1")
    assert result.passed is True
    assert result.champion_id is None


def test_evaluate_challenger_rejects_unknown_id(db_path, registry_with_models):
    """Unknown challenger ID fails evaluation."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    result = mgr.evaluate_challenger("cn", "nonexistent")
    assert result.passed is False
    assert "not found" in result.failure_reasons[0]


# ---------------------------------------------------------------------------
# Promotion atomicity
# ---------------------------------------------------------------------------


def test_promote_challenger_succeeds(db_path, registry_with_models):
    """Successful promotion updates the Champion."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1")
    record = mgr.promote_challenger("cn", "mv_challenger_v2", reason="Better IR")

    assert record.model_version_id == "mv_challenger_v2"
    champion = mgr.get_champion("cn")
    assert champion.model_version_id == "mv_challenger_v2"


def test_promote_challenger_fails_atomic(db_path, registry_with_models):
    """Failed promotion leaves the current Champion unchanged."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1")

    with pytest.raises(ValueError, match="Challenge failed"):
        mgr.promote_challenger("cn", "mv_worse")

    # Champion should still be the original
    champion = mgr.get_champion("cn")
    assert champion.model_version_id == "mv_champion_v1"


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def test_rollback_to_specific_version(db_path, registry_with_models):
    """Rollback to a specific previous version."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1", reason="First")
    mgr.declare_champion("cn", "mv_challenger_v2", reason="Upgrade")

    record = mgr.rollback("cn", target_version_id="mv_champion_v1")
    assert record is not None
    assert record.model_version_id == "mv_champion_v1"

    champion = mgr.get_champion("cn")
    assert champion.model_version_id == "mv_champion_v1"


def test_rollback_auto_finds_previous(db_path, registry_with_models):
    """Auto-rollback finds the previous Champion from history."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1", reason="First")
    mgr.declare_champion("cn", "mv_challenger_v2", reason="Upgrade")

    record = mgr.rollback("cn")  # auto-find previous
    assert record is not None
    # Should have restored mv_champion_v1 (the replaced champion from history)
    assert record.model_version_id == "mv_champion_v1"


def test_rollback_none_when_no_previous(db_path):
    """Rollback returns None when there's no Champion."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    result = mgr.rollback("cn")
    assert result is None


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------


def test_champion_history_records_events(db_path, registry_with_models):
    """Promotion and demotion events are recorded in history."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1", reason="Initial")
    mgr.declare_champion("cn", "mv_challenger_v2", reason="Better")

    history = mgr.get_history("cn")
    assert len(history) >= 2

    # Most recent first
    assert history[0]["action"] == "promoted"
    assert history[0]["model_version_id"] == "mv_challenger_v2"


def test_clear_champion_records_demotion(db_path, registry_with_models):
    """Clearing a Champion records a demotion event."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1")
    mgr._champion_index.clear_champion("cn")

    champion = mgr.get_champion("cn")
    assert champion is None

    history = mgr.get_history("cn")
    assert any(h["action"] == "demoted" for h in history)


# ---------------------------------------------------------------------------
# Cross-market isolation
# ---------------------------------------------------------------------------


def test_champions_isolated_by_market(db_path, registry_with_models):
    """Champions for different markets don't interfere."""
    from src.assistant.champion_manager import ChampionManager

    mgr = ChampionManager(db_path)
    mgr._registry = registry_with_models

    mgr.declare_champion("cn", "mv_champion_v1")

    # US has no Champion
    assert mgr.get_champion("us") is None

    # CN Champion is unaffected
    champion = mgr.get_champion("cn")
    assert champion.model_version_id == "mv_champion_v1"
