from __future__ import annotations

import datetime
from pathlib import Path


class GovernanceService:
    def __init__(self, project_root: str | Path):
        self._project_root = Path(project_root)
        self._readme_path = self._project_root / "README.md"

    def log_run_event(self, market: str, action: str, outcome: str, metric: str | None = None):
        """
        Automatically appends a run event to the Project README Module 6.
        Format: - YYYY-MM-DD: [Market] [Action] -> [Outcome] (Key Metric: [Metric])
        """
        if not self._readme_path.exists():
            return

        date_str = datetime.date.today().strftime("%Y-%m-%d")
        metric_str = f" (Key Metric: {metric})" if metric else ""
        log_line = f"- {date_str}: [{market.upper()}] {action} -> {outcome}{metric_str}\n"

        try:
            content = self._readme_path.read_text(encoding="utf-8")
            
            # Find Module 6: Run Log
            if "## Module 6: Run Log" in content:
                # Append to the end of the section
                parts = content.split("## Module 6: Run Log")
                if len(parts) == 2:
                    header = "## Module 6: Run Log"
                    body = parts[1]
                    # Find if there are more modules after 6 (unlikely but safe)
                    if "## Module" in body:
                        # Split by the next module
                        sub_parts = body.split("## Module", 1)
                        new_body = sub_parts[0].rstrip() + "\n" + log_line + "\n## Module" + sub_parts[1]
                        new_content = parts[0] + header + new_body
                    else:
                        new_content = parts[0] + header + body.rstrip() + "\n" + log_line
                    
                    self._readme_path.write_text(new_content, encoding="utf-8")
            else:
                # Append to the end of the file if section missing
                with open(self._readme_path, "a", encoding="utf-8") as f:
                    f.write(f"\n## Module 6: Run Log\n\n{log_line}")
        except Exception as e:
            print(f"Failed to log governance event: {e}")

    def update_task_status(self, task_slug: str, status: str = "DONE"):
        """
        Updates task status in Module 5: Next Actions.
        """
        if not self._readme_path.exists():
            return
        
        try:
            content = self._readme_path.read_text(encoding="utf-8")
            # Replace [ ] with [x] for the specific task
            if task_slug in content:
                # Simple replacement for demonstration
                # Real implementation would use regex for precision
                new_content = content.replace(f"- [ ] {task_slug}", f"- [x] {task_slug}")
                self._readme_path.write_text(new_content, encoding="utf-8")
        except Exception:
            pass
