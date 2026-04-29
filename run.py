import fire

from core.backtester import QlibRunner
from core.parser import import_strategy_class, load_strategy_unit
from core.reporter import StaticReporter


def main(strategy: str, start: str = "2025-10-23", end: str = "2026-01-23"):
    """
    AlphaEngine V2 MVP Entry Point.
    """
    print(f"🚀 AlphaEngine V2: Initializing '{strategy}'...")

    # 1. Load Configuration from Markdown
    try:
        config, unit_path = load_strategy_unit(strategy)
        print(f"✔ Config loaded from {unit_path}/README.md")
    except Exception as e:
        print(f"❌ Error loading strategy: {e}")
        return

    # 2. Dynamic Strategy Import
    try:
        # Default to BiweeklyTrendStrategy if not specified in config
        class_name = config.get("strategy_class", "BiweeklyTrendStrategy")
        strategy_class = import_strategy_class(unit_path, class_name)
        print(f"✔ Strategy class '{class_name}' imported.")
    except Exception as e:
        print(f"❌ Error importing strategy logic: {e}")
        return

    # 3. Execution
    try:
        runner = QlibRunner(config)
        results = runner.execute(start_time=start, end_time=end, strategy_class=strategy_class)
        print("✔ Simulation complete.")
    except Exception as e:
        print(f"❌ Execution failed: {e}")
        import traceback

        traceback.print_exc()
        return

    # 4. Reporting
    try:
        reporter = StaticReporter()
        report_name = f"reports/{strategy}_report.html"
        report_path = reporter.generate(results, output=report_name)
        print(f"✔ 100% Static Report generated: {report_path.absolute()}")
    except Exception as e:
        print(f"❌ Reporting failed: {e}")
        return

    print("\n✨ Done! AlphaEngine V2 MVP finished successfully.")


if __name__ == "__main__":
    fire.Fire(main)
