"""Tests for src.optimization.factor_state."""
import pytest
from src.optimization.factor_state import FactorState, FactorRecord, FactorCatalog


class TestFactorRecord:
    def test_validated_is_active(self):
        r = FactorRecord("f1", "expr", "momentum", FactorState.VALIDATED)
        assert r.is_active
        assert not r.is_proposed

    def test_proposed_is_not_active(self):
        r = FactorRecord("f2", "expr", "volatility", FactorState.PROPOSED)
        assert r.is_proposed
        assert not r.is_active

    def test_validate_from_proposed(self):
        r = FactorRecord("f1", "expr", "momentum", FactorState.PROPOSED)
        v = r.validate("hash123")
        assert v.state == FactorState.VALIDATED
        assert v.implementation_hash == "hash123"
        assert r.state == FactorState.PROPOSED  # original unchanged

    def test_validate_from_validated_fails(self):
        r = FactorRecord("f1", "expr", "momentum", FactorState.VALIDATED)
        with pytest.raises(ValueError, match="only validate from PROPOSED"):
            r.validate("h")

    def test_retire(self):
        r = FactorRecord("f1", "expr", "m", FactorState.VALIDATED)
        retired = r.retire()
        assert retired.state == FactorState.RETIRED


class TestFactorCatalog:
    def test_add_and_query(self):
        cat = FactorCatalog()
        cat.add(FactorRecord("f1", "e1", "momentum", FactorState.VALIDATED, ("us", "cn")))
        cat.add(FactorRecord("f2", "e2", "momentum", FactorState.PROPOSED, ("us",)))
        cat.add(FactorRecord("f3", "e3", "volatility", FactorState.VALIDATED, ("cn",)))

        assert cat.total_count == 3
        assert cat.validated_count == 2
        assert cat.proposed_count == 1

        assert len(cat.validated("us")) == 1  # f1
        assert len(cat.validated("cn")) == 2  # f1, f3
        assert len(cat.proposed("us")) == 1   # f2
        assert len(cat.proposed("cn")) == 0

        by_fam = cat.by_family("us")
        assert len(by_fam["momentum"]) == 2

    def test_duplicate_rejected(self):
        cat = FactorCatalog()
        cat.add(FactorRecord("f1", "e", "m", FactorState.VALIDATED))
        with pytest.raises(ValueError, match="duplicate"):
            cat.add(FactorRecord("f1", "e2", "m2", FactorState.PROPOSED))

    def test_state_summary(self):
        cat = FactorCatalog()
        cat.add(FactorRecord("f1", "e", "m", FactorState.VALIDATED))
        cat.add(FactorRecord("f2", "e", "m", FactorState.VALIDATED))
        cat.add(FactorRecord("f3", "e", "m", FactorState.PROPOSED))
        cat.add(FactorRecord("f4", "e", "m", FactorState.RETIRED))
        summary = cat.state_summary()
        assert summary == {"validated": 2, "proposed": 1, "retired": 1}
