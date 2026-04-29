import json
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Define the project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# Create the MCP server instance
mcp = FastMCP("AlphaEngine Trading Assistant")


@mcp.tool()
def get_market_signals(market: str = "us"):
    """
    Run inference to get trading signals for the specified market (cn or us).
    If data gaps are detected, it returns a 'REPAIR_PROPOSAL' for the agent to decide.
    """
    try:
        # Run inference script and capture output
        cmd = [sys.executable, "-m", "src.inference", "--market", market]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

        output = result.stdout
        # Basic pattern matching for data gaps in logs
        if (
            "Prediction length mismatch" in output
            or "All predictions for" in output
            or "NaN" in output
        ):
            proposal = {
                "status": "DATA_GAP_DETECTED",
                "market": market,
                "suggestion": "Run 'repair_market_data' with increased lookback_days.",
                "affected_symbols": "Multiple (check logs for details)",
            }
            return f"Data quality issues detected. \n\nPROPOSAL: {json.dumps(proposal, indent=2)}\n\nLog Snippet:\n{output[-500:]}"

        # Check if report was generated
        report_path = PROJECT_ROOT / "reports" / "watchlist_report.md"
        if report_path.exists():
            with open(report_path, encoding="utf-8") as f:
                content = f.read()
            return f"Inference completed for {market.upper()} market.\n\n{content}"
        else:
            return f"Inference failed. Log:\n{output}\nError:\n{result.stderr}"
    except Exception as e:
        return f"Error running inference: {str(e)}"


@mcp.tool()
def repair_market_data(market: str = "us", symbols: str = "all", lookback_days: int = 60):
    """
    Directional repair tool for fixing data gaps.
    Agent can specify specific market and lookback depth based on the inference proposal.
    """
    try:
        # Using update_data.py with explicit lookback for repair
        cmd = [
            sys.executable,
            "scripts/update_data.py",
            "--market",
            market,
            "--lookback-days",
            str(lookback_days),
        ]
        # Future optimization: support --symbols filter in update_data.py
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Data Repair executed for {market.upper()} ({lookback_days} days). \nLog:\n{result.stdout}"
    except Exception as e:
        return f"Error in data repair: {str(e)}"


@mcp.tool()
def run_backtest(market: str = "us", start_date: str = "2024-01-01", end_date: str = "2024-12-31"):
    """
    Run a strategy backtest for the specified market and date range.
    Returns a structured JSON containing alpha/excess return summary (Sharpe, Drawdown, etc.).
    """
    try:
        from qlib.workflow import R

        from src.common.metrics_extractor import MetricsExtractor

        # Run orchestrator command
        cmd = [
            sys.executable,
            "-m",
            "src.orchestrator",
            "rebacktest",
            "--market",
            market,
            "--start",
            start_date,
            "--end",
            end_date,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

        # Search for the latest record in MLflow/Qlib workflow
        # Qlib's R.list_rec can help find the latest backtest
        try:
            # We filter by market to get relevant records
            recs = R.list_rec(experiment_name=market, recorder_name="backtest")
            if recs:
                # Get the most recent recorder
                latest_rec = recs[0]
                metrics = MetricsExtractor.extract_from_record(latest_rec)
                summary = MetricsExtractor.format_summary(metrics, market, start_date, end_date)
                return (
                    f"Backtest completed successfully.\n\nRESULTS: {json.dumps(summary, indent=2)}"
                )
        except Exception:
            pass

        return f"Backtest completed. Summary from log:\n{result.stdout[-1000:]}"
    except Exception as e:
        return f"Error running backtest: {str(e)}"


@mcp.tool()
def diagnose_platform():
    """
    Run the 'doctor' diagnostic script to check the health of data and models.
    """
    try:
        cmd = [sys.executable, "scripts/doctor.py"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Platform Diagnosis Results:\n{result.stdout}\n{result.stderr}"
    except Exception as e:
        return f"Error running diagnosis: {str(e)}"


@mcp.tool()
def update_market_data(market: str = "us", lookback_days: int = 30):
    """
    Update the market data for the specified region to ensure inference uses the latest info.
    """
    try:
        cmd = [
            sys.executable,
            "scripts/update_data.py",
            "--market",
            market,
            "--lookback-days",
            str(lookback_days),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Data Update Log for {market.upper()}:\n{result.stdout}"
    except Exception as e:
        return f"Error updating data: {str(e)}"


if __name__ == "__main__":
    mcp.run()
