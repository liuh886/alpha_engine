import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_generate_data_quality_summary(tmp_path: Path):
    from src.data.quality import generate_data_quality_summary

    provider = tmp_path / "data" / "watchlist"
    (provider / "calendars").mkdir(parents=True, exist_ok=True)
    (provider / "instruments").mkdir(parents=True, exist_ok=True)
    (provider / "calendars" / "day.txt").write_text("2026-02-04\n2026-02-05\n", encoding="utf-8")
    (provider / "instruments" / "us.txt").write_text(
        "AAPL\t2026-02-04\t2026-02-05\n", encoding="utf-8"
    )

    csv_dir = tmp_path / "data" / "csv_source"
    csv_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "date": ["2026-02-04", "2026-02-05"],
            "open": [1, 1],
            "high": [1, 1],
            "low": [1, 1],
            "close": [1, 1],
            "volume": [1, 1],
            "amount": [1, 1],
            "factor": [1, 1],
        }
    )
    df.to_csv(csv_dir / "AAPL.csv", index=False)

    out = generate_data_quality_summary(
        dataset_key="watchlist",
        freq="day",
        provider_uri=provider,
        csv_dir=csv_dir,
        markets=["us"],
    )
    assert out["ok"] is True
    assert out["latest_calendar_day"] == "2026-02-05"
    assert out["markets"]["us"]["instruments"] == 1
