module.exports = {
  apps: [
    {
      name: "alpha-api",
      script: "uv",
      args: "run python api_server.py --port 18000",
      interpreter: "none",
      windowsHide: true,
      env: {
        NODE_ENV: "development",
        PORT: 18000,
        PYTHONPATH: "."
      },
      error_file: "./artifacts/logs/api-error.log",
      out_file: "./artifacts/logs/api-out.log",
      autorestart: true,
      max_memory_restart: "1G"
    },
    {
      name: "alpha-web",
      script: "npm",
      args: "run dev -- --port 15173",
      cwd: "./qlib-dashboard",
      interpreter: "none",
      windowsHide: true,
      shell: true, // 核心：在 Windows 下必须开启 shell 才能运行 npm
      env: {
        NODE_ENV: "development",
        VITE_PORT: 15173,
        VITE_API_URL: "http://localhost:18000"
      },
      error_file: "./artifacts/logs/web-error.log",
      out_file: "./artifacts/logs/web-out.log",
      autorestart: true
    },
    {
      name: "alpha-mcp",
      script: "uv",
      args: "run python src/api/mcp_server.py",
      interpreter: "none",
      windowsHide: true,
      env: {
        PYTHONPATH: "."
      },
      error_file: "./artifacts/logs/mcp-error.log",
      out_file: "./artifacts/logs/mcp-out.log",
      autorestart: true
    }
  ]
};
