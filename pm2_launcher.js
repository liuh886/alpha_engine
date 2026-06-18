/**
 * PM2 launcher wrapper for Windows.
 * Spawns the target script as a hidden subprocess so no console window flashes.
 * Usage (in ecosystem.config.js): script = "pm2_launcher.js", args = "api_server.py"
 */
const { spawn } = require("child_process");
const path = require("path");

const script = process.argv[2];
if (!script) {
  console.error("Usage: node pm2_launcher.js <script> [args...]");
  process.exit(1);
}

const isWin = process.platform === "win32";
const pythonExe = isWin
  ? path.join(__dirname, ".venv", "Scripts", "python.exe")
  : "python";

const extraArgs = process.argv.slice(3);
const child = spawn(pythonExe, [script, ...extraArgs], {
  cwd: __dirname,
  stdio: "pipe",
  windowsHide: true,
  detached: true,
  env: { ...process.env, PYTHONPATH: __dirname },
});

// Pipe child output to pm2's stdout/stderr so logs are captured
if (child.stdout) child.stdout.pipe(process.stdout);
if (child.stderr) child.stderr.pipe(process.stderr);

child.on("exit", (code) => {
  process.exit(code ?? 1);
});

child.on("error", (err) => {
  console.error("Failed to start process:", err.message);
  process.exit(1);
});
