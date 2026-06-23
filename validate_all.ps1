$ErrorActionPreference = "Stop"

Write-Host "=== Gate 1: Ruff lint ===" -ForegroundColor Cyan
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed" }

Write-Host "`n=== Gate 2: Mypy type check ===" -ForegroundColor Cyan
uv run mypy src/release src/models/metric_contract.py
if ($LASTEXITCODE -ne 0) { throw "Mypy failed" }

Write-Host "`n=== Gate 3: Pytest ===" -ForegroundColor Cyan
uv run pytest tests -q --strict-markers
if ($LASTEXITCODE -ne 0) { throw "Pytest failed" }

Write-Host "`n=== Gate 4: Release gate verification ===" -ForegroundColor Cyan
uv run python scripts/release_gate.py --run-quality-gates --evidence-dir artifacts/release_gates
if ($LASTEXITCODE -ne 0) { throw "Release gate failed" }

Write-Host "`n=== Gate 5: Package build ===" -ForegroundColor Cyan
uv build
if ($LASTEXITCODE -ne 0) { throw "uv build failed" }

Write-Host "`n=== Gate 6: npm install ===" -ForegroundColor Cyan
Push-Location qlib-dashboard
try {
    # Mitigate Windows EPERM lock issues from previous steps by cleaning up lingering processes
    Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process esbuild -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }

    Write-Host "`n=== Gate 7: TypeScript type check ===" -ForegroundColor Cyan
    npx tsc --noEmit
    if ($LASTEXITCODE -ne 0) { throw "tsc failed" }

    Write-Host "`n=== Gate 8: Frontend lint ===" -ForegroundColor Cyan
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw "lint failed" }

    Write-Host "`n=== Gate 9: Frontend unit tests ===" -ForegroundColor Cyan
    npm test
    if ($LASTEXITCODE -ne 0) { throw "npm test failed" }

    Write-Host "`n=== Gate 10: Frontend build ===" -ForegroundColor Cyan
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm build failed" }

    Write-Host "`n=== Gate 11: Playwright E2E tests ===" -ForegroundColor Cyan
    npx playwright test
    if ($LASTEXITCODE -ne 0) { throw "playwright test failed" }
} finally {
    Pop-Location
}

Write-Host "`n✅ All validation gates passed successfully!" -ForegroundColor Green
