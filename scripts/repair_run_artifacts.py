import sys
from pathlib import Path

from qlib.workflow import R

# Project setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init


def repair_run(run_id, market="us"):
    print(f"Repairing Run {run_id} for {market}...")

    # Init qlib
    cfg = build_qlib_init_cfg({}, market=market)
    safe_qlib_init(cfg)

    from qlib.workflow.record_temp import PortAnaRecord, SigAnaRecord

    # Get recorder
    exp_name = f"workflow_{market}"
    try:
        rec = R.get_recorder(recorder_id=run_id, experiment_name=exp_name)
    except:
        print(f"Could not get recorder {run_id}")
        return

    print("Generating PortAnaRecord...")
    # Mock port_analysis_config
    port_analysis_config = {
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {
                "time_per_step": "day",
                "generate_portfolio_metrics": True,
            },
        },
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy",
            "kwargs": {
                "model": None,
                "dataset": None,
                "topk": 50,
                "n_drop": 5,
            },
        },
        "backtest": {
            "start_time": "2025-01-01",
            "end_time": "2026-02-27",
            "account": 100000,
            "benchmark": "QQQ" if market == "us" else "000300",
            "exchange_kwargs": {
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            },
        },
    }

    pa_record = PortAnaRecord(rec, port_analysis_config)
    pa_record.generate()

    print("Generating SigAnaRecord...")
    sa_record = SigAnaRecord(rec, {})
    sa_record.generate()

    print(f"Successfully repaired {run_id}.")


if __name__ == "__main__":
    import fire

    fire.Fire(repair_run)
