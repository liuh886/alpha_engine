"""
Windowless launcher for Alpha Engine API server.
Use with pm2 on Windows to avoid console window popups.

.pyw files are executed by pythonw.exe automatically (no console window).
stdout/stderr are redirected to log files so pm2 can tail them.
"""
import sys
import runpy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Redirect stdout/stderr to log files (pythonw closes them by default)
log_out = open(LOG_DIR / "alpha-hub-out.log", "a", encoding="utf-8", buffering=1)
log_err = open(LOG_DIR / "alpha-hub-err.log", "a", encoding="utf-8", buffering=1)
sys.stdout = log_out
sys.stderr = log_err

# Ensure project root is in sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Run api_server.py as __main__ (triggers uvicorn.run())
runpy.run_path(str(PROJECT_ROOT / "api_server.py"), run_name="__main__")
