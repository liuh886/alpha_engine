const path = require("path");
const isWin = process.platform === "win32";
const baseDir = __dirname;

module.exports = {
  apps: [
    {
      name: "alpha-hub",
      // On Windows: .pyw file runs via pythonw (no console window).
      // On Linux/macOS: uv run python api_server.py
      script: isWin
        ? path.join(baseDir, "pm2_launcher.js")
        : "api_server.py",
      interpreter: isWin ? "node" : "uv",
      args: isWin ? "api_server.py" : "run python api_server.py",
      cwd: baseDir,
      env: {
        PYTHONPATH: baseDir,
        PORT: 8000,
        TRADING_STATIC_SITE_DIR: "qlib-dashboard/dist",
        PYTHONUNBUFFERED: "1",
      },
      // Log files (for pm2 logs / pm2 log tailing)
      out_file: path.join(baseDir, "logs", "alpha-hub-out.log"),
      error_file: path.join(baseDir, "logs", "alpha-hub-err.log"),
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      max_memory_restart: '2G',
      listen_timeout: 5000,
      kill_timeout: 5000,
      max_restarts: 10,
      min_uptime: 5000,
    }
  ]
};
