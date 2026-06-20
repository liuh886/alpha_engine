"""Tests for SignalProvenance metadata on SignalGrade and SignalPerformance."""


from src.strategies.signal_grade_engine import (
    SignalGrade,
    SignalPerformance,
    SignalProvenance,
)


def _make_provenance(**overrides) -> SignalProvenance:
    defaults = {
        "model_version_id": "lgbm-v2.1.0",
        "run_id": "run-abc-123",
        "prediction_checksum": "sha256:deadbeef",
        "snapshot_id": "snap-20260618",
        "validity_expiry": "2026-06-28T00:00:00Z",
    }
    defaults.update(overrides)
    return SignalProvenance(**defaults)


# ------------------------------------------------------------------
# 1. SignalGrade with provenance serializes correctly
# ------------------------------------------------------------------
class TestSignalGradeProvenanceSerialization:
    def test_grade_with_provenance_serializes(self):
        prov = _make_provenance()
        grade = SignalGrade(
            symbol="AAPL", date="2026-06-18", grade="AAA",
            rank=0, total_stocks=500, score=0.95, percentile=99.8,
            provenance=prov,
        )
        d = grade.to_dict()
        assert d["symbol"] == "AAPL"
        assert d["provenance"]["model_version_id"] == "lgbm-v2.1.0"
        assert d["provenance"]["run_id"] == "run-abc-123"
        assert d["provenance"]["prediction_checksum"] == "sha256:deadbeef"
        assert d["provenance"]["snapshot_id"] == "snap-20260618"
        assert d["provenance"]["validity_expiry"] == "2026-06-28T00:00:00Z"

    # ------------------------------------------------------------------
    # 2. SignalGrade without provenance serializes (backward compat)
    # ------------------------------------------------------------------
    def test_grade_without_provenance_backward_compat(self):
        grade = SignalGrade(
            symbol="MSFT", date="2026-06-18", grade="AA",
            rank=5, total_stocks=500, score=0.88, percentile=98.0,
        )
        d = grade.to_dict()
        assert "provenance" not in d
        assert grade.provenance is None

    # ------------------------------------------------------------------
    # 3. SignalPerformance with provenance
    # ------------------------------------------------------------------
    def test_performance_with_provenance(self):
        prov = _make_provenance()
        perf = SignalPerformance(
            grade="AAA", total_occurrences=42, positive_count=30,
            negative_count=12, win_rate=0.7143, mean_return=0.035,
            cumulative_return=0.50, median_return=0.03, max_return=0.12,
            min_return=-0.04, avg_score=0.91, provenance=prov,
        )
        d = perf.to_dict()
        assert d["grade"] == "AAA"
        assert d["provenance"]["model_version_id"] == "lgbm-v2.1.0"
        assert d["provenance"]["run_id"] == "run-abc-123"

    def test_performance_without_provenance_backward_compat(self):
        perf = SignalPerformance(
            grade="V", total_occurrences=10, positive_count=3,
            negative_count=7, win_rate=0.3, mean_return=-0.01,
            cumulative_return=-0.10, median_return=-0.015, max_return=0.02,
            min_return=-0.05, avg_score=0.45,
        )
        d = perf.to_dict()
        assert "provenance" not in d
        assert perf.provenance is None

    # ------------------------------------------------------------------
    # 4. Provenance fields are preserved in to_dict()
    # ------------------------------------------------------------------
    def test_provenance_fields_preserved_in_grade_dict(self):
        prov = _make_provenance(
            model_version_id="xgb-v3.0",
            run_id="run-xyz-999",
            prediction_checksum="md5:cafebabe",
            snapshot_id="snap-20260619",
            validity_expiry="2026-07-01T00:00:00Z",
        )
        grade = SignalGrade(
            symbol="TSLA", date="2026-06-19", grade="VVV",
            rank=499, total_stocks=500, score=-0.92, percentile=0.2,
            provenance=prov,
        )
        d = grade.to_dict()
        p = d["provenance"]
        assert p["model_version_id"] == "xgb-v3.0"
        assert p["run_id"] == "run-xyz-999"
        assert p["prediction_checksum"] == "md5:cafebabe"
        assert p["snapshot_id"] == "snap-20260619"
        assert p["validity_expiry"] == "2026-07-01T00:00:00Z"

    def test_provenance_fields_preserved_in_performance_dict(self):
        prov = _make_provenance(snapshot_id="snap-custom")
        perf = SignalPerformance(
            grade="AA", total_occurrences=20, positive_count=15,
            negative_count=5, win_rate=0.75, mean_return=0.02,
            cumulative_return=0.20, median_return=0.018, max_return=0.08,
            min_return=-0.03, avg_score=0.85, provenance=prov,
        )
        d = perf.to_dict()
        assert d["provenance"]["snapshot_id"] == "snap-custom"

    # ------------------------------------------------------------------
    # 5. Missing provenance is None, not empty string
    # ------------------------------------------------------------------
    def test_missing_provenance_is_none_not_empty(self):
        grade = SignalGrade(
            symbol="GOOG", date="2026-06-18", grade="A",
            rank=100, total_stocks=500, score=0.6, percentile=80.0,
        )
        assert grade.provenance is None
        assert grade.provenance != ""
        d = grade.to_dict()
        assert "provenance" not in d

    def test_performance_missing_provenance_is_none_not_empty(self):
        perf = SignalPerformance(
            grade="VV", total_occurrences=5, positive_count=1,
            negative_count=4, win_rate=0.2, mean_return=-0.008,
            cumulative_return=-0.04, median_return=-0.01, max_return=0.01,
            min_return=-0.03, avg_score=0.55,
        )
        assert perf.provenance is None
        assert perf.provenance != ""
        d = perf.to_dict()
        assert "provenance" not in d


# ------------------------------------------------------------------
# 6. SignalProvenance frozen dataclass
# ------------------------------------------------------------------
class TestSignalProvenanceFrozen:
    def test_frozen_immutability(self):
        prov = _make_provenance()
        try:
            prov.model_version_id = "changed"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass

    def test_provenance_to_dict(self):
        prov = _make_provenance()
        d = prov.to_dict()
        assert len(d) == 5
        assert set(d.keys()) == {
            "model_version_id", "run_id", "prediction_checksum",
            "snapshot_id", "validity_expiry",
        }

    def test_provenance_equality(self):
        p1 = _make_provenance()
        p2 = _make_provenance()
        assert p1 == p2

    def test_provenance_inequality(self):
        p1 = _make_provenance()
        p2 = _make_provenance(run_id="different")
        assert p1 != p2
