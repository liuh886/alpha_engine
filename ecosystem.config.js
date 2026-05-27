const path = require("path");
const isWin = process.platform === "win32";
const baseDir = __dirname;
const pythonExe = isWin
  ? path.join(baseDir, ".venv", "Scripts", "python.exe")
  : "uv";

module.exports = {
  apps: [
    {
      name: "alpha-hub",
      script: pythonExe,
      cwd: baseDir,
      args: isWin ? "api_server.py" : "run python api_server.py",
      interpreter: "none",
      env: {
        PYTHONPATH: baseDir,
        PORT: 8000,
        TRADING_STATIC_SITE_DIR: "qlib-dashboard/dist",
        TRADING_UI_USER: process.env.TRADING_UI_USER || "admin",
        TRADING_UI_PASSWORD: process.env.TRADING_UI_PASSWORD || "",
      },
      max_memory_restart: '2G',
      listen_timeout: 5000,
      kill_timeout: 5000,
      windowsHide: true,
      max_restarts: 10,
      min_uptime: 5000
    }
  ]
};
