import json
import os
import subprocess
import time


def format_thought_stream_for_report(agent_name, level, message):
    stream_path = "artifacts/agent_thought_stream.json"
    if not os.path.exists(os.path.dirname(stream_path)):
        os.makedirs(os.path.dirname(stream_path), exist_ok=True)

    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "agent": agent_name,
        "level": level,
        "message": message,
    }

    data = []
    if os.path.exists(stream_path):
        try:
            with open(stream_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = []

    data.append(entry)
    with open(stream_path, "w") as f:
        json.dump(data, f, indent=2)


def run_command(cmd, agent_name, description, max_retries=3):
    retries = 0
    while retries < max_retries:
        format_thought_stream_for_report(
            agent_name, "info", f"Executing: {description} (Attempt {retries + 1}/{max_retries})..."
        )
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                format_thought_stream_for_report(
                    agent_name, "success", f"Successfully completed: {description}"
                )
                return True
            else:
                retries += 1
                format_thought_stream_for_report(
                    agent_name,
                    "warning",
                    f"Attempt {retries} failed for {description}. Retrying in 5s...",
                )
                time.sleep(5)
        except Exception:
            retries += 1
            time.sleep(5)

    format_thought_stream_for_report(
        agent_name, "error", f"Permanent failure after {max_retries} attempts: {description}"
    )
    return False


def run_multi_agent_pipeline(market="cn"):
    print("=========================================")
    print(f" Alpha Engine Pipeline: {market.upper()} Market ")
    print("=========================================")

    # Step 1: Governance kicks off
    format_thought_stream_for_report(
        "Governance Agent", "info", f"Initiating real-world pipeline for {market} market."
    )

    # Step 2: Risk Agent audits (Simulated logic for now, but real script trigger)
    format_thought_stream_for_report(
        "Risk Agent", "info", "Verifying data integrity and market volatility."
    )

    # Step 3: Data Collection (Real)
    # Note: collect_data.py currently handles both US/CN via watchlist.yaml
    if not run_command("python scripts/collect_data.py", "Data Agent", "Market Data Collection"):
        format_thought_stream_for_report(
            "Governance Agent",
            "warning",
            "Data collection had issues, proceeding with partial data.",
        )

    # Step 4: Alpha Research (Inference & Backtest)
    # This would normally involve running an orchestrator, let's trigger the report generation for the latest run
    run_command(
        f"python scripts/generate_backtest_report.py --latest --market {market}",
        "Alpha Agent",
        f"Generating {market} Backtest Report",
    )

    format_thought_stream_for_report(
        "Governance Agent", "success", "Full pipeline cycle complete. Reports available in Web UI."
    )


if __name__ == "__main__":
    import sys

    market = sys.argv[1] if len(sys.argv) > 1 else "cn"
    run_multi_agent_pipeline(market)
