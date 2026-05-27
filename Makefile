.PHONY: doctor data train train-cn train-us backtest breakfast report dashboard all help test typecheck lint clean dev

PYTHON = PYTHONPATH=. python3

help:
	@echo "Qlib Trading Assistant - Task Runner"
	@echo "------------------------------------"
	@echo "  make dev      Start development servers (Dashboard + API)"
	@echo "  make doctor   Run environment self-check"
	@echo "  make data     Update market data (default: cn)"
	@echo "  make backtest Run zero-barrier backtest pipeline"
	@echo "  make breakfast Generate daily trading report markdown"
	@echo "  make lint     Format and lint code using Ruff and Prettier"
	@echo "  make test     Run pytest test suite"
	@echo "  make typecheck Run mypy type checking"
	@echo "  make clean    Remove generated files"
	@echo ""
	@echo "Advanced/Internal Targets:"
	@echo "  make train-cn  Train LGBM model for CN market"
	@echo "  make train-us  Train LGBM model for US market"
	@echo "  make report    Generate latest backtest reports (legacy)"

doctor:
	$(PYTHON) scripts/doctor.py

data:
	$(PYTHON) scripts/update_data.py

train-cn:
	$(PYTHON) -m src.orchestrator run --market cn --tag LGBM_AUTO --profile configs/strategy_profile_cn.json

train-us:
	$(PYTHON) -m src.orchestrator run --market us --tag LGBM_AUTO --profile configs/strategy_profile_us.json

report:
	$(PYTHON) -m src.reporting.generate --market all

dev:
	@echo "Starting Dashboard (Vite) and API Server in background..."
	@cd qlib-dashboard && (npm run dev -- --port 5173 &)
	@uv run python api_server.py &
	@echo "Services started. View at http://localhost:5173"
	@echo "Use 'kill %1' or 'kill %2' (or Ctrl+C for the API) to stop."
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

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
	rm -rf runs/*.log
	rm -rf artifacts/tmp/*
