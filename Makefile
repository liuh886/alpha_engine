.PHONY: doctor data train-cn train-us train-cn-xgb train-us-xgb walk-forward-cn walk-forward-us backtest breakfast report research-bundle static-pwa weekly-research check-decay weekly-report help test typecheck lint clean ci

PYTHON = PYTHONPATH=. python3

help:
	@echo "Alpha Engine - Research Task Runner"
	@echo "-----------------------------------"
	@echo "  make doctor          Run environment self-check"
	@echo "  make data            Update market data"
	@echo "  make research-bundle Export the canonical research artifact bundle"
	@echo "  make static-pwa      Build the zero-API Research Artifact Studio"
	@echo "  make backtest        Run the zero-barrier backtest pipeline"
	@echo "  make breakfast       Generate the daily research report"
	@echo "  make weekly-research Run the full weekly research cycle"
	@echo "  make check-decay     Check Active factors for alpha decay"
	@echo "  make weekly-report   Generate the weekly research report"
	@echo "  make lint            Run Python and frontend lint"
	@echo "  make typecheck       Run Python and TypeScript checks"
	@echo "  make test            Run Python and frontend unit tests"
	@echo "  make ci              Run local research and static-product gates"
	@echo ""
	@echo "Advanced research targets:"
	@echo "  make train-cn          Train the CN LGBM model"
	@echo "  make train-us          Train the US LGBM model"
	@echo "  make train-cn-xgb      Train the CN XGBoost model"
	@echo "  make train-us-xgb      Train the US XGBoost model"
	@echo "  make walk-forward-cn   Run CN walk-forward validation"
	@echo "  make walk-forward-us   Run US walk-forward validation"
	@echo "  make report            Generate the latest backtest reports"

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

static-pwa:
	@echo "Building the zero-API Research Artifact Studio..."
	@cd qlib-dashboard && npm ci && npm run build

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

backtest:
	@echo "Running Zero-Barrier Backtest..."
	@uv run python -m src.orchestrator run --skip_train

breakfast:
	@echo "Generating Morning Research Report..."
	@uv run python scripts/generate_breakfast.py

weekly-research:
	$(PYTHON) scripts/weekly_research.py

check-decay:
	$(PYTHON) scripts/check_factor_decay.py

weekly-report:
	$(PYTHON) scripts/generate_weekly_report.py

lint:
	@echo "Running Python and frontend lint..."
	@ruff check .
	@cd qlib-dashboard && npm run lint

typecheck:
	@echo "Running Python and TypeScript checks..."
	@mypy src/release src/models/metric_contract.py
	@cd qlib-dashboard && npx tsc --noEmit

test:
	@echo "Running Python and frontend unit tests..."
	@pytest tests/ --strict-markers
	@cd qlib-dashboard && npm test

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
	rm -rf runs/*.log
	rm -rf artifacts/tmp/*

ci:
	@echo "=== Gate 0: Retired Web boundary ==="
	uv run python scripts/check_legacy_web_boundary.py
	@echo "=== Gate 1: Ruff lint ==="
	ruff check .
	@echo "=== Gate 2: Mypy type check ==="
	mypy src/release src/models/metric_contract.py
	@echo "=== Gate 3: Full pytest collection ==="
	pytest --collect-only -q
	@echo "=== Gate 4: Python tests ==="
	pytest tests -q --strict-markers
	@echo "=== Gate 5: npm ci ==="
	cd qlib-dashboard && npm ci
	@echo "=== Gate 6: TypeScript type check ==="
	cd qlib-dashboard && npx tsc --noEmit
	@echo "=== Gate 7: Frontend lint ==="
	cd qlib-dashboard && npm run lint
	@echo "=== Gate 8: Frontend unit tests ==="
	cd qlib-dashboard && npm test
	@echo "=== Gate 9: Static PWA build ==="
	cd qlib-dashboard && npm run build
	@echo "=== Gate 10: Release gate verification ==="
	uv run python scripts/release_gate.py --candidate rc_20260620 --run-quality-gates --evidence-dir artifacts/release_gates
	@echo "=== Gate 11: Package build ==="
	uv build
	@echo "=== All research and static-product gates passed ==="
