.PHONY: doctor data train train-cn train-us train-cn-xgb train-us-xgb walk-forward-cn walk-forward-us backtest breakfast report dashboard all help test typecheck lint clean dev legacy-web-dev research-bundle weekly-research check-decay weekly-report ci smoke

PYTHON = PYTHONPATH=. python3

help:
	@echo "Alpha Engine - Task Runner"
	@echo "--------------------------"
	@echo "  make doctor          Run environment self-check"
	@echo "  make data            Update market data (default: cn)"
	@echo "  make research-bundle Export the canonical static research bundle"
	@echo "  make backtest        Run zero-barrier backtest pipeline"
	@echo "  make breakfast       Generate daily research report markdown"
	@echo "  make lint            Format and lint code using Ruff and Prettier"
	@echo "  make test            Run pytest test suite"
	@echo "  make typecheck       Run mypy type checking"
	@echo "  make clean           Remove generated files"
	@echo "  make weekly-research Run full weekly research cycle"
	@echo "  make check-decay     Check Active factors for alpha decay"
	@echo "  make weekly-report   Generate weekly research report"
	@echo "  make ci              Run all CI quality gates locally"
	@echo ""
	@echo "Deprecated migration-only targets:"
	@echo "  make dev             Compatibility alias; starts the legacy local Web stack"
	@echo "  make legacy-web-dev  Start deprecated Vite + FastAPI development servers"
	@echo "  make smoke           Validate deprecated API container stack"
	@echo ""
	@echo "Advanced/Internal Targets:"
	@echo "  make train-cn          Train LGBM model for CN market"
	@echo "  make train-us          Train LGBM model for US market"
	@echo "  make train-cn-xgb      Train XGBoost model for CN market"
	@echo "  make train-us-xgb      Train XGBoost model for US market"
	@echo "  make walk-forward-cn   Walk-forward validation for CN market"
	@echo "  make walk-forward-us   Walk-forward validation for US market"
	@echo "  make report            Generate latest backtest reports (legacy)"

doctor:
	$(PYTHON) scripts/doctor.py

data:
	$(PYTHON) scripts/update_data.py

research-bundle:
	@echo "Exporting static artifact source..."
	@uv run python scripts/export_static_site_data.py --market all --output artifacts/site/data
	@echo "Building versioned research bundle..."
	@uv run python scripts/export_research_bundle.py --source artifacts/site --output artifacts/research-bundle
	@echo "Open artifacts/research-bundle from the Research Artifact Studio Library."

train-cn:
	$(PYTHON) -m src.orchestrator run --market cn --tag LGBM_AUTO --profile configs/strategy_profile_cn.json

train-us:
	$(PYTHON) -m src.orchestrator run --market us --tag LGBM_AUTO --profile configs/strategy_profile_us.json

train-cn-xgb:
	$(PYTHON) -m src.orchestrator run --market cn --model_type xgb --tag XGB_AUTO --profile configs/strategy_profile_cn.json

train-us-xgb:
	$(PYTHON) -m src.orchestrator run --market us --model_type xgb --tag XGB_AUTO --profile configs/strategy_profile_us.json

walk-forward-cn:
	$(PYTHON) -m src.orchestrator run --market cn --model_type lgbm --tag WF_LGBM --profile configs/strategy_profile_cn.json --walk_forward

walk-forward-us:
	$(PYTHON) -m src.orchestrator run --market us --model_type lgbm --tag WF_LGBM --profile configs/strategy_profile_us.json --walk_forward

report:
	$(PYTHON) -m src.reporting.generate --market all

dev:
	@echo "DEPRECATED: the FastAPI/local-Web stack is frozen and scheduled for removal under issue #316."
	@$(MAKE) legacy-web-dev

legacy-web-dev:
	@echo "Starting deprecated Dashboard (Vite) and FastAPI server for migration compatibility..."
	@cd qlib-dashboard && (npm run dev -- --port 5173 &)
	@uv run python api_server.py &
	@echo "Legacy services started at http://localhost:5173 and http://localhost:8000"
	@echo "Do not add new features or dependencies to this path."

backtest:
	@echo "Running Zero-Barrier Backtest..."
	@uv run python -m src.orchestrator run --skip_train

breakfast:
	@echo "Generating Morning Trading Report..."
	@uv run python scripts/generate_breakfast.py

lint:
	@echo "Formatting and linting code..."
	@ruff format .
	@ruff check --fix .
	@if [ -d "qlib-dashboard/node_modules" ]; then cd qlib-dashboard && npx prettier --write .; fi

test:
	@echo "Running pytest..."
	@pytest tests/

typecheck:
	@echo "Running mypy..."
	@mypy src/

weekly-research:
	$(PYTHON) scripts/weekly_research.py

check-decay:
	$(PYTHON) scripts/check_factor_decay.py

weekly-report:
	$(PYTHON) scripts/generate_weekly_report.py

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
	rm -rf runs/*.log
	rm -rf artifacts/tmp/*

ci:
	@echo "=== Gate 0: Legacy Web boundary ==="
	uv run python scripts/check_legacy_web_boundary.py
	@echo "=== Gate 1: Ruff lint ==="
	ruff check .
	@echo "=== Gate 2: Mypy type check (ratcheted scope) ==="
	mypy src/release src/models/metric_contract.py
	@echo "=== Gate 3: Pytest (zero-unapproved-skip) ==="
	pytest tests -q --strict-markers
	@echo "=== Gate 4: npm ci ==="
	cd qlib-dashboard && npm ci
	@echo "=== Gate 5: TypeScript type check ==="
	cd qlib-dashboard && npx tsc --noEmit
	@echo "=== Gate 6: Frontend lint ==="
	cd qlib-dashboard && npm run lint
	@echo "=== Gate 7: Frontend unit tests ==="
	cd qlib-dashboard && npm test
	@echo "=== Gate 8: Frontend build ==="
	cd qlib-dashboard && npm run build
	@echo "=== Gate 9: Release gate verification ==="
	uv run python scripts/release_gate.py --candidate rc_20260620 --run-quality-gates --evidence-dir artifacts/release_gates
	@echo "=== Gate 10: Package build ==="
	uv build
	@echo "=== All CI gates passed ==="

# ---------------------------------------------------------------------------
# DEPRECATED smoke test for the legacy API container stack.
# Kept temporarily for controlled retirement under issue #316.
# ---------------------------------------------------------------------------
SMOKE_COMPOSE_FILE = docker-compose.smoke.yml
smoke:
	@echo "DEPRECATED: validating the legacy API container stack scheduled for removal under issue #316."
	@echo "=== Smoke: building image ==="
	docker compose -f docker-compose.yml build api
	@echo "=== Smoke: generating ephemeral compose override ==="
	@printf '# Auto-generated by make smoke -- do not edit.\nservices:\n  api:\n    environment:\n      TRADING_UI_USER: smoke_user\n      TRADING_UI_PASSWORD: smoke_pass_12345\n      ALPHA_DEVELOPER_TOKEN: smoke_token_abc\n      ALPHA_ENGINE_ENV: production\n    ports:\n      - "127.0.0.1:18000:8000"\n    healthcheck:\n      test: ["CMD", "python", "/app/scripts/container-healthcheck.py"]\n      interval: 5s\n      timeout: 3s\n      retries: 10\n      start_period: 10s\n' > $(SMOKE_COMPOSE_FILE)
	@echo "=== Smoke: starting container ==="
	docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) up -d api
	@echo "=== Smoke: waiting for health endpoint ==="
	@i=0; \
	while [ $$i -lt 30 ]; do \
		if curl -sf http://127.0.0.1:18000/api/public/health > /dev/null 2>&1; then \
			echo "Health check passed."; \
			break; \
		fi; \
		i=$$((i + 1)); \
		sleep 2; \
	done; \
	if [ $$i -ge 30 ]; then \
		echo "FAIL: health endpoint did not respond within 60s"; \
		docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) logs api; \
		docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) down -v; \
		rm -f $(SMOKE_COMPOSE_FILE); \
		exit 1; \
	fi
	@echo "=== Smoke: checking readiness endpoint ==="
	@curl -sf http://127.0.0.1:18000/api/health/ready > /dev/null 2>&1 \
		&& echo "Readiness check returned 200." \
		|| echo "Readiness check returned non-200 (expected on fresh data volume -- not a failure)."
	@echo "=== Smoke: restarting container ==="
	docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) restart api
	@echo "=== Smoke: waiting for health after restart ==="
	@i=0; \
	while [ $$i -lt 30 ]; do \
		if curl -sf http://127.0.0.1:18000/api/public/health > /dev/null 2>&1; then \
			echo "Post-restart health check passed."; \
			break; \
		fi; \
		i=$$((i + 1)); \
		sleep 2; \
	done; \
	if [ $$i -ge 30 ]; then \
		echo "FAIL: health endpoint did not respond after restart within 60s"; \
		docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) logs api; \
		docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) down -v; \
		rm -f $(SMOKE_COMPOSE_FILE); \
		exit 1; \
	fi
	@echo "=== Smoke: tearing down ==="
	docker compose -f docker-compose.yml -f $(SMOKE_COMPOSE_FILE) down -v
	rm -f $(SMOKE_COMPOSE_FILE)
	@echo "=== Deprecated smoke test PASSED ==="
