import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import time

from src.assistant.job_service import JobService
from src.assistant.metadata_db import resolve_metadata_db_path

db_path = resolve_metadata_db_path(project_root)
svc = JobService(db_path=db_path, project_root=project_root)

jobs = svc.list_jobs(status="running")
print(f"Total running jobs: {len(jobs)}")
for j in jobs:
    elapsed = time.time() - j["started_at"] if j.get("started_at") else 0
    print(f"ID: {j['id']} | Type: {j['type']} | Elapsed: {elapsed:.1f}s | Cmd: {j.get('commands')}")
