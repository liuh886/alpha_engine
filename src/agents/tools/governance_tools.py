import datetime
import os

from src.common.logging import get_logger

logger = get_logger(__name__)


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
        logger.error("Failed to append to human run log", error=str(e))
        return False


def format_thought_stream_for_report(agent: str, level: str, thought_text: str) -> bool:
    """
    Writes the Agent's thought stream to a local state file
    so the dashboard GUI can pick it up and display it.

    The *agent* parameter is normalized to ``"ResearchAssistant"`` — the
    codebase consolidated from four legacy agents (Alpha, Risk, Governance,
    Developer) into a single unified ResearchAssistant in T18/T19.  Legacy
    agent names are accepted for backward compatibility but are rewritten
    on write so the frontend never displays multi-agent identities.
    """
    import json

    # Normalize to unified identity (T18/T19 consolidation)
    normalized_agent = "ResearchAssistant"
    if agent != normalized_agent:
        import logging

        _log = logging.getLogger(__name__)
        _log.debug(
            "Normalizing legacy agent name in thought stream",
            legacy_agent=agent,
            normalized=normalized_agent,
        )

    os.makedirs("artifacts", exist_ok=True)
    filepath = "artifacts/agent_thought_stream.json"

    logs = []
    if os.path.exists(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                raw_logs = json.load(f)
            # Normalize legacy entries that use different field names
            for entry in raw_logs:
                if not isinstance(entry, dict):
                    continue
                normalized = {
                    "id": entry.get("id", ""),
                    "date": entry.get("date", entry.get("timestamp", "")),
                    "agent": entry.get("agent", "ResearchAssistant"),
                    "level": entry.get("level", "info"),
                    "thought": entry.get("thought", entry.get("message", "")),
                }
                # Generate versioned id for entries missing it
                if not normalized["id"] or "_" not in str(normalized["id"]):
                    normalized["id"] = f"legacy_{len(logs):04d}"
                logs.append(normalized)
        except Exception:
            logs = []

    now = datetime.datetime.now()
    logs.append(
        {
            "id": now.strftime("%Y%m%d_%H%M%S_%f"),
            "date": now.isoformat(),
            "agent": normalized_agent,
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
