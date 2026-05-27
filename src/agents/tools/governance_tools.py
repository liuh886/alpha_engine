import datetime
import os


def append_to_human_run_log(status: str, message: str) -> bool:
    """
    Append a globally readable log entry to a persistent run log.

    Args:
        status: e.g., 'SUCCESS', 'FAILURE', 'WARNING'
        message: The key metric or message to record.

    Returns:
        bool: True if appended successfully.
    """
    os.makedirs("artifacts", exist_ok=True)
    log_path = "artifacts/agent_run_history.md"

    # Auto-initialize header if it doesn't exist
    if not os.path.exists(log_path):
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Agentic Alpha Engine: Run History\n\n*This document contains human-readable logs of decisions and operations taken autonomously by the AI Agents.*\n\n---\n\n"
                )
        except Exception:
            pass

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"**[{timestamp}]** `[{status.upper()}]` {message}\n\n"

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)
        return True
    except Exception as e:
        print(f"Error appending to human run log: {e}")
        return False


def format_thought_stream_for_report(agent: str, level: str, thought_text: str) -> bool:
    """
    Writes the Agent's thought stream to a local state file
    so the dashboard GUI can pick it up and display it.
    """
    import json

    os.makedirs("artifacts", exist_ok=True)
    filepath = "artifacts/agent_thought_stream.json"

    logs = []
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append(
        {
            "id": str(datetime.datetime.now().timestamp()),
            "date": datetime.datetime.now().isoformat(),
            "agent": agent,
            "level": level,
            "thought": thought_text,
        }
    )

    # keep trailing 50
    logs = logs[-50:]

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
