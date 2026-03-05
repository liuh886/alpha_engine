import json
import os
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
    Returns the top candidates that passed guardrails.
    """
    try:
        # Run inference script and capture output
        cmd = [sys.executable, "-m", "src.inference", "--market", market]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        
        # Check if report was generated
        report_path = PROJECT_ROOT / "reports" / "watchlist_report.md"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            return f"Inference completed for {market.upper()} market.\n\n{content}"
        else:
            return f"Inference failed or no signals generated. Log:\n{result.stdout}\nError:\n{result.stderr}"
    except Exception as e:
        return f"Error running inference: {str(e)}"

@mcp.tool()
def run_backtest(market: str = "us", start_date: str = "2024-01-01", end_date: str = "2024-12-31"):
    """
    Run a strategy backtest for the specified market and date range.
    Returns the alpha/excess return summary.
    """
    try:
        # Assuming there's a backtest script in scripts/ or src/
        # Using orchestrator as it handles complex tasks
        cmd = [
            sys.executable, "-m", "src.orchestrator", 
            "rebacktest", 
            "--market", market, 
            "--start_time", start_date, 
            "--end_time", end_date
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        
        # Look for the generated report
        report_dir = PROJECT_ROOT / "reports" / market
        if report_dir.exists():
            # Find the latest HTML or JSON report
            reports = list(report_dir.glob("*.html"))
            if reports:
                # We can't return HTML easily in text, but we can return the path
                return f"Backtest finished. Report generated at: {reports[-1].name}"
        
        return f"Backtest completed. Summary:\n{result.stdout}"
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
            sys.executable, "scripts/update_data.py", 
            "--market", market, 
            "--lookback-days", str(lookback_days)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Data Update Log for {market.upper()}:\n{result.stdout}"
    except Exception as e:
        return f"Error updating data: {str(e)}"

if __name__ == "__main__":
    mcp.run()
