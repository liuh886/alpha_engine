.PHONY: help doctor lint typecheck test ci

help:
	@echo "Alpha Engine - Five-strategy research console"
	@echo "  uv run alpha data --help      Governed incremental data preparation"
	@echo "  uv run alpha ops --help       Decision evidence and current operating status"
	@echo "  uv run alpha research --help  Explicit research, training and replay"
	@echo "  Frontend development and build: see README.md"
	@echo ""
	@echo "Maintenance:"
	@echo "  make doctor     Diagnose current evidence and operating health"
	@echo "  make lint       Run Python and frontend lint"
	@echo "  make typecheck  Run Python and TypeScript checks"
	@echo "  make test       Run Python and frontend unit tests"
	@echo "  make ci         Run the full local release checks"

doctor:
	uv run python scripts/doctor.py

lint:
	@echo "Running Python and frontend lint..."
	@ruff check .
	@cd qlib-dashboard && npm run lint

typecheck:
	@echo "Running Python and TypeScript checks..."
	@mypy src/release src/models/metric_contract.py src/research/economics.py src/research/replay_comparison.py src/research/ranker_execution.py src/research/ranker_training.py src/research/us_x1_3_current_target.py src/data/listing_lifecycle.py src/data/symbol_identity.py src/data/snapshot_manifest.py src/factors/ranker_snapshot.py src/governance/active_strategy_catalog.py src/research/formal_baseline.py src/artifacts/system_health.py src/data/model_data_bundle.py src/data/snapshot.py src/data/market_provider.py src/artifacts/formal_bundle_reader.py src/governance/strategy_runtime_capabilities.py src/research/factor_identity.py
	@cd qlib-dashboard && npx tsc --noEmit

test:
	@echo "Running Python and frontend unit tests..."
	@pytest tests/ --strict-markers
	@cd qlib-dashboard && npm test

ci:
	uv run python scripts/release_gate.py --run-quality-gates --evidence-dir artifacts/release_gates
