const path = require("path");
const isWin = process.platform === "win32";
const baseDir = __dirname;

module.exports = {
  apps: [
    {
      name: "alpha-api",
      script: "api_server.py",
      cwd: baseDir,
      interpreter: isWin ? "powershell.exe" : "/bin/sh",
      interpreter_args: isWin ? "-NoProfile -Command uv run python" : "-c \"uv run python\"",
      env: {
        PYTHONPATH: baseDir,
        PORT: 8000,
        TRADING_UI_USER: "admin",
        TRADING_UI_PASSWORD: "alpha123"
      },
      listen_timeout: 5000,
      kill_timeout: 5000
    },
    {
      name: "alpha-dashboard",
      script: "./node_modules/vite/bin/vite.js",
      args: "dev --port 5174",
      cwd: path.join(baseDir, "qlib-dashboard"),
      env: {
        NODE_ENV: "development"
      }
    }
  ]
};
