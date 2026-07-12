"""Real-Qlib CI tests for spec-bound execution and market-specific sessions."""

from __future__ import annotations

import json
import subprocess
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.build_market_providers import build_market_provider
from src.research.cn_qlib_execution_adapter import (
    QlibCNExecutionRuntime,
    execute_cn_qlib_plan,
)
from src.research.paradigm import load_research_paradigm_spec
from src.research.spec_bound_execution import execute_spec_bound_research

FIXTURE_DIR = Path("tests/fixtures/cn_qlib_ci")


def test_cn_spec_bound_adapter_with_real_qlib_provider(tmp_path: Path) -> None:
    provider_dir = tmp_path / "qlib_data"
    subprocess.run(
        [
            sys.executable,
            str(FIXTURE_DIR / "build_fixture.py"),
            "--output",
            str(provider_dir),
        ],
        check=True,
    )

    spec = load_research_paradigm_spec(FIXTURE_DIR / "paradigm.yaml")
    runtime = QlibCNExecutionRuntime(provider_uri=provider_dir)
    result = execute_spec_bound_research(
        spec,
        partial(execute_cn_qlib_plan, runtime=runtime),
        output_dir=tmp_path / "research_runs",
    )

    assert result["status"] == "passed"
    assert result["contract_identity_verified"] is True

    run_dir = Path(result["run_dir"])
    identity = json.loads(
        (run_dir / "execution_identity.json").read_text(encoding="utf-8")
    )
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    readiness = json.loads(
        (run_dir / "data_readiness.json").read_text(encoding="utf-8")
    )
    windows = json.loads(
        (run_dir / "walk_forward_windows.json").read_text(encoding="utf-8")
    )

    assert identity["matched"] is True
    assert status["status"] == "passed"
    assert status["research_only"] is True
    assert status["trade_ready"] is False
    assert readiness["sufficient"] is True
    assert len(readiness["retained_symbols"]) >= 8
    assert len(windows["windows"]) >= 3
    assert (run_dir / "walk_forward_stability.json").is_file()
    assert (run_dir / "model_decision_pack.json").is_file()
    assert (run_dir / "metrics_summary.json").is_file()
    for path in status["evidence_paths"].values():
        assert Path(path).is_file()


def _write_market_csv(
    path: Path,
    dates: list[str],
    closes: list[float],
) -> None:
    close = np.asarray(closes, dtype=float)
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.arange(len(close), dtype=float) + 1_000.0,
            "amount": close * (np.arange(len(close), dtype=float) + 1_000.0),
            "factor": np.ones(len(close), dtype=float),
        }
    )
    frame.to_csv(path, index=False)


def _query_forward_return(
    *,
    repository_root: Path,
    market: str,
    symbol: str,
    start: str,
    end: str,
) -> dict:
    script = r"""
import json
import sys
from pathlib import Path

market = sys.argv[1]
root = Path(sys.argv[2])
symbol = sys.argv[3]
start = sys.argv[4]
end = sys.argv[5]

if market == "cn":
    from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime
    runtime = QlibCNExecutionRuntime()
else:
    from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
    runtime = QlibUSExecutionRuntime()

runtime.initialize(root)
frame = runtime.features(
    [symbol],
    ["Ref($close, -10) / $close - 1"],
    start,
    end,
)
frame.columns = ["forward_return"]
rows = frame.reset_index().dropna(subset=["forward_return"])
first = rows.iloc[0]
print(json.dumps({
    "date": str(first["datetime"].date()),
    "value": float(first["forward_return"]),
    "provider": runtime.metadata(),
}))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            market,
            str(repository_root),
            symbol,
            start,
            end,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_real_qlib_forward_return_uses_each_market_own_tenth_session(
    tmp_path: Path,
) -> None:
    csv_dir = tmp_path / "data" / "csv_source"
    csv_dir.mkdir(parents=True)

    cn_dates = [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
        "2026-01-13",
        "2026-01-14",
        "2026-01-15",
        "2026-01-16",
        "2026-01-19",
        "2026-01-20",
    ]
    us_dates = [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-12",
        "2026-01-13",
        "2026-01-14",
        "2026-01-15",
        "2026-01-16",
        "2026-01-20",
        "2026-01-21",
    ]
    cn_close = [100.0 + index for index in range(len(cn_dates))]
    us_close = [200.0 + index for index in range(len(us_dates))]
    _write_market_csv(csv_dir / "000069.csv", cn_dates, cn_close)
    _write_market_csv(csv_dir / "AAPL.csv", us_dates, us_close)

    cn_manifest = build_market_provider(
        csv_dir=csv_dir,
        provider_dir=tmp_path / "data" / "providers" / "cn",
        market="cn",
    )
    us_manifest = build_market_provider(
        csv_dir=csv_dir,
        provider_dir=tmp_path / "data" / "providers" / "us",
        market="us",
    )

    cn_result = _query_forward_return(
        repository_root=tmp_path,
        market="cn",
        symbol="000069",
        start=cn_dates[0],
        end=cn_dates[-1],
    )
    us_result = _query_forward_return(
        repository_root=tmp_path,
        market="us",
        symbol="AAPL",
        start=us_dates[0],
        end=us_dates[-1],
    )

    assert cn_dates[10] == "2026-01-19"
    assert us_dates[10] == "2026-01-20"
    assert cn_result["date"] == cn_dates[0]
    assert us_result["date"] == us_dates[0]
    assert np.isclose(
        cn_result["value"],
        cn_close[10] / cn_close[0] - 1.0,
    )
    assert np.isclose(
        us_result["value"],
        us_close[10] / us_close[0] - 1.0,
    )
    assert cn_result["provider"]["provider_identity_sha256"] == cn_manifest[
        "provider_identity_sha256"
    ]
    assert us_result["provider"]["provider_identity_sha256"] == us_manifest[
        "provider_identity_sha256"
    ]
    assert cn_result["provider"]["provider_uri"].endswith("data/providers/cn")
    assert us_result["provider"]["provider_uri"].endswith("data/providers/us")
