import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_trade_ticket_path_is_under_reports_dir(tmp_path: Path):
    from src.reporting.generate import trade_ticket_path

    p = trade_ticket_path("us", "2025-12-31", reports_dir=tmp_path)
    assert p == tmp_path / "us" / "trade_tickets" / "trade_ticket_2025-12-31.md"

