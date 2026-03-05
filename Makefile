.PHONY: doctor data train backtest report dashboard all help

PYTHON = python

help:
	@echo "Qlib Trading Assistant - Task Runner"
	@echo "------------------------------------"
	@echo "  make dev      Start development servers (Dashboard + API)"
	@echo "  make doctor   Run environment self-check"
	@echo "  make data     Update market data (default: cn)"
	@echo "  make backtest Run zero-barrier backtest pipeline"
	@echo "  make breakfast Generate daily trading report markdown"
	@echo "  make lint     Format and lint code using Ruff and Prettier"
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
	@echo "Starting Dashboard (Vite) and API Server..."
	@start cmd /c "cd qlib-dashboard && npm run dev"
	@start cmd /c "uv run python api_server.py"
	@echo "Services started. View at http://localhost:5173"

backtest:
	@echo "Running Zero-Barrier Backtest..."
	@uv run python cli.py backtest

breakfast:
	@echo "Generating Morning Trading Report..."
	@uv run python cli.py breakfast

lint:
	@echo "Formatting and linting code..."
	@uv run ruff format .
	@uv run ruff check --fix .
	@prettier --write .

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('.pytest_cache')]"
	rm -rf runs/*.log
	rm -rf artifacts/tmp/*
