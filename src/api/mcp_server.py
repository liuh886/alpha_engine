import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Define the project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# Create the MCP server instance
mcp = FastMCP("AlphaEngine Trading Assistant")

# --- Authentication ---
_DEVELOPER_TOKEN = os.environ.get("ALPHA_DEVELOPER_TOKEN")
if not _DEVELOPER_TOKEN:
    logger.warning(
        "ALPHA_DEVELOPER_TOKEN is not set. "
        "MCP tools will be accessible without authentication (development mode)."
    )


def _verify_token(token: str) -> bool:
    """Return True if *token* matches the configured developer token.

    When ``ALPHA_DEVELOPER_TOKEN`` is unset, every token is accepted (development mode).
    """
    if not _DEVELOPER_TOKEN:
        # Development mode -- allow everything.
        return True
    return token == _DEVELOPER_TOKEN


@mcp.tool()
def get_market_signals(token: str = "", market: str = "us"):
    """
    Run inference to get trading signals for the specified market (cn or us).
    If data gaps are detected, it returns a 'REPAIR_PROPOSAL' for the agent to decide.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        # Run inference script and capture output
        cmd = [sys.executable, "-m", "src.inference", "--market", market]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

        output = result.stdout
        # Basic pattern matching for data gaps in logs
        if (
            "Prediction length mismatch" in output
            or "All predictions for" in output
            or "NaN" in output
        ):
            proposal = {
                "status": "DATA_GAP_DETECTED",
                "market": market,
                "suggestion": "Run 'repair_market_data' with increased lookback_days.",
                "affected_symbols": "Multiple (check logs for details)",
            }
            return f"Data quality issues detected. \n\nPROPOSAL: {json.dumps(proposal, indent=2)}\n\nLog Snippet:\n{output[-500:]}"

        # Check if report was generated
        report_path = PROJECT_ROOT / "reports" / "watchlist_report.md"
        if report_path.exists():
            with open(report_path, encoding="utf-8") as f:
                content = f.read()
            return f"Inference completed for {market.upper()} market.\n\n{content}"
        else:
            return f"Inference failed. Log:\n{output}\nError:\n{result.stderr}"
    except Exception as e:
        return f"Error running inference: {str(e)}"


@mcp.tool()
def repair_market_data(token: str = "", market: str = "us", symbols: str = "all", lookback_days: int = 60):
    """
    Directional repair tool for fixing data gaps.
    Agent can specify specific market and lookback depth based on the inference proposal.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        # Using update_data.py with explicit lookback for repair
        cmd = [
            sys.executable,
            "scripts/update_data.py",
            "--market",
            market,
            "--lookback-days",
            str(lookback_days),
        ]
        # Future optimization: support --symbols filter in update_data.py
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Data Repair executed for {market.upper()} ({lookback_days} days). \nLog:\n{result.stdout}"
    except Exception as e:
        return f"Error in data repair: {str(e)}"


@mcp.tool()
def run_backtest(token: str = "", market: str = "us", start_date: str = "2024-01-01", end_date: str = "2024-12-31"):
    """
    Run a strategy backtest for the specified market and date range.
    Returns a structured JSON containing alpha/excess return summary (Sharpe, Drawdown, etc.).
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from qlib.workflow import R

        from src.common.metrics_extractor import MetricsExtractor

        # Run orchestrator command
        cmd = [
            sys.executable,
            "-m",
            "src.orchestrator",
            "rebacktest",
            "--market",
            market,
            "--start",
            start_date,
            "--end",
            end_date,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))

        # Search for the latest record in MLflow/Qlib workflow
        # Qlib's R.list_rec can help find the latest backtest
        try:
            # We filter by market to get relevant records
            recs = R.list_rec(experiment_name=market, recorder_name="backtest")
            if recs:
                # Get the most recent recorder
                latest_rec = recs[0]
                metrics = MetricsExtractor.extract_from_record(latest_rec)
                summary = MetricsExtractor.format_summary(metrics, market, start_date, end_date)
                return (
                    f"Backtest completed successfully.\n\nRESULTS: {json.dumps(summary, indent=2)}"
                )
        except Exception:
            pass

        return f"Backtest completed. Summary from log:\n{result.stdout[-1000:]}"
    except Exception as e:
        return f"Error running backtest: {str(e)}"


@mcp.tool()
def diagnose_platform(token: str = ""):
    """
    Run the 'doctor' diagnostic script to check the health of data and models.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        cmd = [sys.executable, "scripts/doctor.py"]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Platform Diagnosis Results:\n{result.stdout}\n{result.stderr}"
    except Exception as e:
        return f"Error running diagnosis: {str(e)}"


@mcp.tool()
def update_market_data(token: str = "", market: str = "us", lookback_days: int = 30):
    """
    Update the market data for the specified region to ensure inference uses the latest info.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        cmd = [
            sys.executable,
            "scripts/update_data.py",
            "--market",
            market,
            "--lookback-days",
            str(lookback_days),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        return f"Data Update Log for {market.upper()}:\n{result.stdout}"
    except Exception as e:
        return f"Error updating data: {str(e)}"


# ---------------------------------------------------------------------------
# Factor lifecycle MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
def define_factor(
    name: str,
    expression: str,
    category: str = "custom",
    direction: str = "long",
    lookback_days: int = 10,
    thesis: str = "",
    token: str = "",
) -> str:
    """Register a new factor expression in the factor registry.

    Validates the expression syntax first, then registers it at the Proposed stage.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_evaluator import validate_expression_syntax
        from src.research.factor_registry import FactorRegistry

        valid, err = validate_expression_syntax(expression)
        if not valid:
            return json.dumps({"status": "error", "message": f"Invalid expression syntax: {err}"})

        registry = FactorRegistry()
        factor_id = registry.register_factor(
            name=name,
            expression=expression,
            category=category,
            direction=direction,
            lookback_days=lookback_days,
            thesis=thesis,
        )
        return json.dumps({
            "status": "success",
            "factor_id": factor_id,
            "name": name,
            "stage": "Proposed",
            "message": f"Factor '{name}' registered with id {factor_id} at Proposed stage.",
        })
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return json.dumps({
                "status": "error",
                "message": f"Factor with name '{name}' already exists.",
            })
        return json.dumps({"status": "error", "message": f"Error defining factor: {e}"})


@mcp.tool()
def evaluate_factor(
    expression: str,
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    train_end: str = "",
    token: str = "",
) -> str:
    """Evaluate a factor expression and return IC, decay, quintile metrics.

    Args:
        expression: Qlib factor expression to evaluate.
        market: "us" or "cn".
        start_date: Start of evaluation window.
        end_date: End of evaluation window.
        train_end: If provided, IC/quintile metrics are computed only on
            data after this date (out-of-sample). Leave empty for in-sample.
        token: Authentication token.

    Returns a comprehensive JSON with all evaluation metrics and pass/fail verdict.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_evaluator import evaluate_factor as _evaluate_factor

        result = _evaluate_factor(
            expression=expression,
            market=market,
            start_date=start_date,
            end_date=end_date,
            train_end=train_end if train_end else None,
        )
        return json.dumps(result.to_dict())
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error evaluating factor: {e}"})


@mcp.tool()
def validate_factor(
    factor_id: int,
    market: str = "us",
    token: str = "",
) -> str:
    """Validate a registered factor by running evaluation and recording results.

    If the factor passes validation gates, it is promoted to the Validated stage.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_evaluator import evaluate_factor as _evaluate_factor
        from src.research.factor_registry import FactorRegistry

        registry = FactorRegistry()
        factor = registry.get_factor(factor_id)
        if factor is None:
            return json.dumps({"status": "error", "message": f"Factor with id {factor_id} not found."})

        expression = factor["expression"]
        eval_result = _evaluate_factor(expression=expression, market=market)

        metrics = eval_result.to_dict()
        registry.record_validation(factor_id, market, metrics)

        stage = factor["stage"]
        promoted = False
        if eval_result.passed:
            promoted = registry.promote(factor_id)
            if promoted:
                stage = "Validated"

        return json.dumps({
            "status": "success",
            "factor_id": factor_id,
            "name": factor["name"],
            "market": market,
            "passed": eval_result.passed,
            "fail_reasons": eval_result.fail_reasons,
            "metrics": {
                "ic": metrics["ic"],
                "rank_ic": metrics["rank_ic"],
                "icir": metrics["icir"],
                "t_stat": metrics["t_stat"],
                "positive_ratio": metrics["positive_ratio"],
                "quintile_spread": metrics["quintile_spread"],
            },
            "promoted": promoted,
            "stage": stage,
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error validating factor: {e}"})


@mcp.tool()
def register_factor_for_strategy(
    factor_id: int,
    strategy_config: str,
    weight: float = 1.0,
    token: str = "",
) -> str:
    """Register a validated factor for use in a strategy.

    The factor must be at least at the Validated stage. If it is currently
    Validated, it will be promoted to Active upon registration.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_registry import STAGE_ACTIVE, STAGE_VALIDATED, FactorRegistry

        registry = FactorRegistry()
        factor = registry.get_factor(factor_id)
        if factor is None:
            return json.dumps({"status": "error", "message": f"Factor with id {factor_id} not found."})

        stage = factor["stage"]
        stage_order = {"Proposed": 0, "Validated": 1, "Active": 2, "Deprecated": 3}
        if stage_order.get(stage, -1) < stage_order[STAGE_VALIDATED]:
            return json.dumps({
                "status": "error",
                "message": f"Factor '{factor['name']}' is at '{stage}' stage. Must be at least Validated to register for a strategy.",
            })

        registry.record_usage(factor_id, strategy_config, weight)

        promoted = False
        if stage == STAGE_VALIDATED:
            promoted = registry.promote(factor_id)

        return json.dumps({
            "status": "success",
            "factor_id": factor_id,
            "name": factor["name"],
            "strategy_config": strategy_config,
            "weight": weight,
            "promoted_to_active": promoted,
            "stage": STAGE_ACTIVE if promoted else stage,
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error registering factor for strategy: {e}"})


@mcp.tool()
def discover_factor(
    name: str,
    expression: str,
    market: str = "us",
    category: str = "custom",
    thesis: str = "",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    token: str = "",
) -> str:
    """One-call factor lifecycle tool: register, evaluate, validate, and promote.

    Performs the full factor discovery pipeline in a single call:
    1. Validate expression syntax
    2. Register factor in the registry (Proposed stage)
    3. Evaluate factor (IC, decay, quintile analysis)
    4. Record validation results
    5. If passed: promote to Validated, then to Active
    6. If failed: leave at Proposed with diagnostic info

    Returns a comprehensive JSON with all metrics, pass/fail verdict, and final stage.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_evaluator import (
            evaluate_factor as _evaluate_factor,
            validate_expression_syntax,
        )
        from src.research.factor_registry import FactorRegistry

        # Step 1: Validate expression syntax
        valid, err = validate_expression_syntax(expression)
        if not valid:
            return json.dumps({
                "status": "error",
                "stage": "Rejected",
                "message": f"Invalid expression syntax: {err}",
            })

        # Step 2: Register factor
        registry = FactorRegistry()
        try:
            factor_id = registry.register_factor(
                name=name,
                expression=expression,
                category=category,
                direction="long",
                lookback_days=10,
                thesis=thesis,
            )
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                return json.dumps({
                    "status": "error",
                    "message": f"Factor with name '{name}' already exists.",
                })
            raise

        # Step 3: Evaluate factor
        eval_result = _evaluate_factor(
            expression=expression,
            market=market,
            start_date=start_date,
            end_date=end_date,
        )
        metrics = eval_result.to_dict()

        # Step 4: Record validation
        registry.record_validation(factor_id, market, metrics)

        # Step 5-6: Promote based on results
        stage = "Proposed"
        if eval_result.passed:
            promoted_val = registry.promote(factor_id)  # Proposed -> Validated
            if promoted_val:
                stage = "Validated"
                promoted_act = registry.promote(factor_id)  # Validated -> Active
                if promoted_act:
                    stage = "Active"

        return json.dumps({
            "status": "success",
            "factor_id": factor_id,
            "name": name,
            "stage": stage,
            "market": market,
            "passed": eval_result.passed,
            "fail_reasons": eval_result.fail_reasons,
            "metrics": {
                "ic": metrics["ic"],
                "rank_ic": metrics["rank_ic"],
                "icir": metrics["icir"],
                "t_stat": metrics["t_stat"],
                "positive_ratio": metrics["positive_ratio"],
                "quintile_spread": metrics["quintile_spread"],
                "decay_1d": metrics["decay_1d"],
                "decay_5d": metrics["decay_5d"],
                "decay_10d": metrics["decay_10d"],
                "coverage": metrics["coverage"],
                "n_periods": metrics["n_periods"],
            },
            "quintile_returns": metrics["quintile_returns"],
            "message": (
                f"Factor '{name}' discovered and promoted to Active stage."
                if eval_result.passed
                else f"Factor '{name}' evaluation failed. Left at Proposed stage with diagnostic info."
            ),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error in factor discovery: {e}"})


@mcp.tool()
def scan_factor_pool(
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    auto_register: bool = False,
    token: str = "",
) -> str:
    """Scan the default factor pool (momentum, volatility, volume, mean-reversion).

    Evaluates all pre-built factors against validation gates and returns a
    ranked ScanReport as JSON.  When *auto_register* is True, factors that
    pass all gates are automatically registered in the FactorRegistry at the
    Proposed stage.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_scanner import DEFAULT_FACTOR_POOL, scan_factor_pool as _scan

        report = _scan(
            factor_pool=DEFAULT_FACTOR_POOL,
            market=market,
            start_date=start_date,
            end_date=end_date,
            auto_register=auto_register,
        )
        return json.dumps(report.to_dict())
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error scanning factor pool: {e}"})


@mcp.tool()
def load_factor_pool(path: str = "", token: str = "") -> str:
    """Load a custom factor pool from a YAML file.

    When *path* is empty, loads the default ``configs/factor_pool.yaml``.
    Returns a JSON summary with category counts and total factor count.

    Args:
        path: Path to a YAML factor pool file. Empty string uses the default.
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_library import load_factor_pool_from_yaml

        factors = load_factor_pool_from_yaml(path or None)
        summary: dict[str, int] = {}
        for f in factors:
            cat = f["category"]
            summary[cat] = summary.get(cat, 0) + 1
        summary["total"] = len(factors)
        return json.dumps({
            "status": "success",
            "source": path or "configs/factor_pool.yaml",
            "summary": summary,
            "factors": factors[:50],  # preview first 50
            "total_loaded": len(factors),
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error loading factor pool: {e}"})


@mcp.tool()
def get_factor_library(category: str = "", token: str = "") -> str:
    """Return the combinatorial factor library as JSON.

    The library contains 200+ factor expressions generated via combinatorial
    enumeration of base fields, transformations, and lookback windows.
    Optionally filter by category (momentum, volatility, volume,
    mean_reversion, technical, cross_field, composite).

    Args:
        category: Optional category filter. Empty string returns all factors.
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_library import get_factor_library_json

        return get_factor_library_json(category=category)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error getting factor library: {e}"})


# ---------------------------------------------------------------------------
# Factor-to-strategy compiler MCP tool
# ---------------------------------------------------------------------------


@mcp.tool()
def compile_strategy_with_factors(
    base_config: str = "us_lgbm_workflow.yaml",
    market: str = "us",
    merge_mode: str = "append",
    token: str = "",
) -> str:
    """Compile a strategy YAML config with Active factors from the registry.

    Loads the base workflow config, fetches all Active factors for the given
    market, and merges their Qlib expressions into the feature list.  Writes
    a new config file and returns a JSON summary.

    Args:
        base_config: Filename of the base workflow YAML (looked up in configs/).
        market: Market for factor filtering (us or cn).
        merge_mode: "append" adds factors to existing features; "replace" uses only factors.
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_compiler import compile_factors_to_config

        result = compile_factors_to_config(
            base_config_path=base_config,
            market=market,
            merge_mode=merge_mode,
        )
        return json.dumps(result.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error compiling strategy with factors: {e}"})


# ---------------------------------------------------------------------------
# Factor attribution MCP tool
# ---------------------------------------------------------------------------


@mcp.tool()
def attribute_factor_returns(
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    token: str = "",
) -> str:
    """Run factor return attribution analysis for all Active factors.

    Uses a cross-sectional factor model (OLS) to decompose portfolio returns
    into per-factor contributions. Returns a JSON report with per-factor
    return/risk contributions, exposures, IC values, and overall model fit.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_attribution import attribute_returns

        report = attribute_returns(
            market=market,
            start_date=start_date,
            end_date=end_date,
        )
        return json.dumps(report.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error in factor attribution: {e}"})


@mcp.tool()
def attribute_returns_rolling(
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    factor_ids_str: str = "",
    window_months: int = 12,
    step_months: int = 3,
    token: str = "",
) -> str:
    """Compute factor attribution over rolling time windows.

    Shows how factor contributions evolve over time by running the
    cross-sectional factor model on overlapping windows. Returns a JSON
    object with per-window AttributionReports, per-factor trend data, and
    human-readable window labels.

    Args:
        market: Market region ("us" or "cn").
        start_date: Start of the first window.
        end_date: End of the last window.
        factor_ids_str: Comma-separated factor IDs (e.g. "1,2,3"). Empty
            string uses all Active factors.
        window_months: Length of each attribution window in months.
        step_months: Step between consecutive windows in months.
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.factor_attribution import attribute_returns_rolling as _rolling

        factor_ids = None
        if factor_ids_str.strip():
            factor_ids = [int(x.strip()) for x in factor_ids_str.split(",") if x.strip()]

        result = _rolling(
            market=market,
            start_date=start_date,
            end_date=end_date,
            factor_ids=factor_ids,
            window_months=window_months,
            step_months=step_months,
        )
        return json.dumps(result.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error in rolling attribution: {e}"})


# ---------------------------------------------------------------------------
# Goal parsing MCP tool
# ---------------------------------------------------------------------------


@mcp.tool()
def parse_research_goal(goal: str, token: str = "") -> str:
    """Parse a natural language research goal into a structured JSON task.

    Supports Chinese and English keywords for market, factor categories,
    direction, and quality thresholds.  Returns a ResearchGoal dict that
    can be passed to ``run_research_cycle`` or ``run_iterative_research``.

    Examples::

        parse_research_goal("帮我找A股低波策略")
        parse_research_goal("Find US momentum factors with high IC")
        parse_research_goal("扫描所有市场的价值因子")

    Args:
        goal: Free-text research goal description.
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.agents.goal_parser import parse_research_goal as _parse

        parsed = _parse(goal)
        return json.dumps(parsed.to_dict(), indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error parsing goal: {e}"})


# ---------------------------------------------------------------------------
# Full research cycle MCP tool
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Experiment journal MCP tool
# ---------------------------------------------------------------------------


@mcp.tool()
def query_experiments(
    query: str = "summary",
    market: str = "us",
    token: str = "",
) -> str:
    """Query the unified experiment journal across factors, models, and walk-forward results.

    Supported query values:
    - "summary" -- overall stats across all registries
    - "tried" -- what experiments have been attempted
    - "failed" -- list all failed experiments with reasons
    - any other string -- free-text search across all registries

    Args:
        query: One of "summary", "tried", "failed", or a free-text search string.
        market: Market filter (us or cn).
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.experiment_journal import ExperimentJournal

        journal = ExperimentJournal()
        query_lower = query.strip().lower()

        if query_lower == "summary":
            result = journal.get_summary(market=market)
        elif query_lower == "tried":
            result = journal.what_have_i_tried(market=market)
        elif query_lower == "failed":
            result = journal.what_failed(market=market)
        else:
            result = journal.search_experiments(query=query, scope="all")

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error querying experiments: {e}"})


@mcp.tool()
def run_research_cycle(
    market: str = "us",
    goal: str = "Find alpha factors",
    token: str = "",
) -> str:
    """Execute a full automated research cycle: scan -> compile -> backtest -> attribute -> promote.

    Runs the end-to-end research loop that:
    1. Scans the default factor pool and registers passing factors
    2. Compiles top factors into a strategy YAML config
    3. Runs a backtest using the compiled config
    4. Attributes returns to the factors (cross-sectional OLS model)
    5. Auto-promotes qualifying factors through validation gates

    Returns a JSON summary with metrics from each phase.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.agents.research_loop import run_research_cycle as _run_cycle

        result = _run_cycle(
            market=market,
            goal_description=goal,
        )
        return json.dumps(result.to_dict(), indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error running research cycle: {e}"})


@mcp.tool()
def run_iterative_research(
    market: str = "us",
    goal: str = "Find alpha",
    max_iterations: int = 5,
    target_sharpe: float = 1.0,
    token: str = "",
) -> str:
    """Run multiple research cycles with automatic iteration until a target is met.

    Each cycle runs the full research loop (scan -> compile -> backtest ->
    attribute -> promote), then analyzes results to decide the next step:
    - scan_more: broaden factor pool if nothing passed FDR
    - adjust_hyperparams: tweak model parameters if backtest Sharpe is low
    - retry: try a different training window if attribution R² is low
    - stop: target achieved, diminishing returns, or total failure

    Returns a JSON array of CycleResult dicts, one per iteration.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.agents.research_loop import run_iterative_research as _run_iter

        results = _run_iter(
            market=market,
            goal=goal,
            max_iterations=max_iterations,
            target_sharpe=target_sharpe,
        )
        return json.dumps([r.to_dict() for r in results], indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error running iterative research: {e}"})


# ---------------------------------------------------------------------------
# Model FDR comparison MCP tool
# ---------------------------------------------------------------------------


@mcp.tool()
def compare_models_with_fdr(
    model_results_json: str,
    alpha: float = 0.05,
    token: str = "",
) -> str:
    """Apply FDR correction when comparing multiple model configurations.

    Accepts a JSON array of model results, each with at least
    ``model_id``, ``sharpe``, ``ic``, and either ``p_value`` or
    ``n_obs`` (to derive the p-value from the Sharpe ratio).

    Returns the same list with ``adjusted_p_value`` and
    ``fdr_significant`` added to each entry, plus a summary with the
    count of FDR-significant models.

    Example input::

        [
          {"model_id": "lgbm_v1",  "sharpe": 1.2, "ic": 0.05, "p_value": 0.01},
          {"model_id": "lgbm_v2",  "sharpe": 0.9, "ic": 0.03, "p_value": 0.04},
          {"model_id": "xgb_v1",   "sharpe": 1.5, "ic": 0.06, "n_obs": 500}
        ]

    Args:
        model_results_json: JSON string -- array of model result dicts.
        alpha: FDR threshold (default 0.05).
        token: Authentication token.
    """
    if not _verify_token(token):
        return "Authentication failed: invalid or missing token."
    try:
        from src.research.model_fdr import apply_model_fdr

        model_results = json.loads(model_results_json)
        if not isinstance(model_results, list):
            return json.dumps({"status": "error", "message": "Input must be a JSON array."})

        enriched = apply_model_fdr(model_results, alpha=alpha)

        n_significant = sum(1 for m in enriched if m.get("fdr_significant"))
        summary = {
            "status": "success",
            "n_models": len(enriched),
            "alpha": alpha,
            "n_fdr_significant": n_significant,
            "results": enriched,
        }
        return json.dumps(summary, indent=2, default=str)
    except json.JSONDecodeError as e:
        return json.dumps({"status": "error", "message": f"Invalid JSON input: {e}"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Error in model FDR comparison: {e}"})


if __name__ == "__main__":
    mcp.run()
