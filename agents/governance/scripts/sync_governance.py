import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.common.commands import get_supported_commands, get_utility_commands


def sync_scripts_readme():
    readme_path = PROJECT_ROOT / "scripts" / "README.md"
    if not readme_path.exists():
        print(f"Skipping {readme_path}: Not found")
        return

    content = readme_path.read_text(encoding="utf-8")

    # Generate Supported Entrypoints section
    supported_text = "## Supported entrypoints\n\n"
    for cmd in get_supported_commands():
        supported_text += f"- **{cmd.name}** ({cmd.priority} - {cmd.description}):\n"
        supported_text += f"  - `{cmd.command}`\n"

    # Generate Utilities section
    utility_text = "## Utilities (use as needed)\n\n"
    for cmd in get_utility_commands():
        utility_text += f"- {cmd.name}: `{cmd.command}`\n"

    # Replace sections using markers or simple regex
    new_content = re.sub(
        r"## Supported entrypoints\n.*?(?=\n## Utilities)", supported_text, content, flags=re.DOTALL
    )
    new_content = re.sub(
        r"## Utilities \(use as needed\)\n.*?(?=\n## Legacy)",
        utility_text,
        new_content,
        flags=re.DOTALL,
    )

    if new_content != content:
        readme_path.write_text(new_content, encoding="utf-8")
        print(f"Updated {readme_path}")
    else:
        print(f"No changes for {readme_path}")


def sync_workflow():
    workflow_path = PROJECT_ROOT / "Workflows" / "trading_execution_bus.workflow.md"
    if not workflow_path.exists():
        print(f"Skipping {workflow_path}: Not found")
        return

    content = workflow_path.read_text(encoding="utf-8")

    # Sync task_ids in frontmatter
    task_ids = [c.task_id for c in get_supported_commands() if c.task_id]
    task_ids_text = "task_ids:\n" + "\n".join([f"  - {tid}" for tid in task_ids])

    new_content = re.sub(r"task_ids:\n.*?(?=\n---)", task_ids_text, content, flags=re.DOTALL)

    # Sync Step 3 mapping
    mapping_text = "### Step 3 - Execute Supported Entrypoint (Task Step / Manual Step)\nPrefer runtime task runner when the selected operation maps to a registered task:\n"
    for cmd in get_supported_commands():
        if cmd.task_id:
            mapping_text += f"- `{cmd.id}` -> `{cmd.task_id}`\n"

    new_content = re.sub(
        r"### Step 3 - Execute Supported Entrypoint .*?(?=\n\nExample:)",
        mapping_text,
        new_content,
        flags=re.DOTALL,
    )

    if new_content != content:
        workflow_path.write_text(new_content, encoding="utf-8")
        print(f"Updated {workflow_path}")
    else:
        print(f"No changes for {workflow_path}")


if __name__ == "__main__":
    sync_scripts_readme()
    sync_workflow()
    print("Governance synchronization complete.")
