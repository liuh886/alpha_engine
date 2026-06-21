import tempfile
from pathlib import Path

import pytest

from src.assistant.data_provenance_index import DataProvenanceIndex


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


def test_record_and_list(temp_db):
    idx = DataProvenanceIndex(db_path=temp_db)

    # Record a success
    idx.record(symbol="AAPL", market="us", source_used="yfinance", fallback_used=False)

    # Record a fallback
    idx.record(
        symbol="600519",
        market="cn",
        source_used="efinance",
        fallback_used=True,
        code="baostock_failed",
    )

    recent = idx.list_recent()
    assert len(recent) == 2

    # Order is DESC by created_at
    assert recent[0]["symbol"] == "600519"
    assert recent[0]["fallback_used"] == 1
    assert recent[0]["code"] == "baostock_failed"

    assert recent[1]["symbol"] == "AAPL"
    assert recent[1]["fallback_used"] == 0
    assert recent[1]["source_used"] == "yfinance"


def test_empty_values(temp_db):
    idx = DataProvenanceIndex(db_path=temp_db)
    idx.record(symbol=None, market=None)

    recent = idx.list_recent()
    assert len(recent) == 1
    assert recent[0]["symbol"] == ""
    assert recent[0]["market"] == ""
