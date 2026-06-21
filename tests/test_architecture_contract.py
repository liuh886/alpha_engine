from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase1_domain_language_and_adrs_exist():
    assert (ROOT / "CONTEXT.md").exists()
    assert (ROOT / "docs" / "adr" / "0001-domain-and-evidence-first-architecture.md").exists()
    assert (ROOT / "docs" / "adr" / "0002-adapters-must-not-own-research-semantics.md").exists()
    assert (ROOT / "docs" / "adr" / "0003-single-user-local-quant-research-platform.md").exists()


def test_core_research_modules_do_not_import_heavy_runtime_adapters():
    forbidden = (
        "fastapi",
        "qlib",
        "mlflow",
        "src.api.",
        "src.workflows.hooks",
        "src.agents.research_loop",
    )
    for rel in (
        "src/research/evidence.py",
        "src/research/workflow.py",
        "src/research/workflow_store.py",
        "src/research/workflow_types.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), rel


def test_strategy_execution_domain_does_not_import_qlib():
    for path in (ROOT / "src" / "execution").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        import_lines = [
            line
            for line in text.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        assert not any("qlib" in line.lower() for line in import_lines), str(path)


def test_assistant_services_do_not_import_dashboard_job_command_builders():
    forbidden = (
        "src.dashboard.backtest_job",
        "src.dashboard.backtest_runner",
    )
    for path in (ROOT / "src" / "assistant" / "services").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        import_lines = [
            line
            for line in text.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        assert not any(token in line for token in forbidden for line in import_lines), str(path)
