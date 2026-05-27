const path = require("path");
const isWin = process.platform === "win32";
const baseDir = __dirname;

// On Windows, use a Node wrapper that spawns Python with windowsHide: true
// to prevent a visible console window from flashing on each restart.
// On Linux/macOS, run Python directly via uv.
const script = isWin
  ? path.join(baseDir, "pm2_launcher.js")
  : "uv";

module.exports = {
  apps: [
    {
      name: "alpha-hub",
      script: script,
      cwd: baseDir,
      args: isWin ? "api_server.py" : "run python api_server.py",
      interpreter: isWin ? "node" : "none",
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
      max_restarts: 10,
      min_uptime: 5000,
    }
  ]
};
