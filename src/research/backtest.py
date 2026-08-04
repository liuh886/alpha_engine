import pandas as pd
from qlib.data import D
from qlib.data.dataset.handler import DataHandler
from qlib.workflow import R
from qlib.workflow.record_temp import PortAnaRecord

from src.common.logging import get_logger

logger = get_logger(__name__)

_VECTORIZED_STRATEGY_CLASS = "VectorizedBiweeklyStrategy"


class VectorizedPrecomputeError(RuntimeError):
    """Required vectorized Qlib execution evidence could not be prepared."""


def _is_vectorized_strategy(port_analysis_config: dict) -> bool:
    """Check whether the port_analysis_config targets the vectorized strategy."""
    strat_cfg = port_analysis_config.get("strategy", {})
    return strat_cfg.get("class") == _VECTORIZED_STRATEGY_CLASS


def _precompute_for_vectorized(
    pred_score: pd.DataFrame,
    dataset: object,
    port_analysis_config: dict,
) -> dict[str, int | str]:
    """Pre-compute signals for VectorizedBiweeklyStrategy before backtest.

    Must be called BEFORE PortAnaRecord.generate() so the class-level
    _precomputed attribute is populated when Qlib instantiates the strategy.
    """
    try:
        from src.strategies.vectorized_engine import VectorizedSignalPrecomputer
        from src.strategies.vectorized_strategy import VectorizedBiweeklyStrategy

        # A failed refresh must never leave a prior run's class-level evidence
        # available to the next authoritative execution.
        VectorizedBiweeklyStrategy.set_precomputed(None)

        # Resolve instruments and date range from dataset config
        handler_kwargs = (
            dataset.handler_kwargs
            if hasattr(dataset, "handler_kwargs")
            else getattr(dataset, "_handler_kwargs", {})
        )
        instruments = handler_kwargs.get("instruments", [])
        start_time = handler_kwargs.get("start_time")
        end_time = handler_kwargs.get("end_time")

        if not instruments or not start_time or not end_time:
            raise VectorizedPrecomputeError(
                "Missing instruments or date range from dataset; refusing "
                "unverified slow-path fallback"
            )

        backtest_cfg = port_analysis_config.get("backtest", {})
        bt_start = backtest_cfg.get("start_time", start_time)
        bt_end = backtest_cfg.get("end_time", end_time)

        # Fetch close prices in one batch
        close_df = D.features(
            instruments,
            ["$close"],
            start_time=bt_start,
            end_time=bt_end,
        )

        if close_df.empty:
            raise VectorizedPrecomputeError(
                "Empty close data; refusing unverified slow-path fallback"
            )

        precomputer = VectorizedSignalPrecomputer(ma_window=60)
        signals = precomputer.precompute_from_frame(close_df, pred_df=pred_score)
        VectorizedBiweeklyStrategy.set_precomputed(signals)

        logger.info(
            "vectorized_precompute_done",
            n_dates=len(signals.dates),
            n_instruments=len(signals.instruments),
        )
        return {
            "status": "complete",
            "n_dates": len(signals.dates),
            "n_instruments": len(signals.instruments),
        }
    except VectorizedPrecomputeError:
        raise
    except Exception as exc:
        raise VectorizedPrecomputeError(
            "Vectorized Qlib precomputation failed; refusing unverified "
            f"slow-path fallback: {exc}"
        ) from exc


def run_backtest(
    model: object, dataset: object, port_analysis_config: dict, recorder: object = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run inference and portfolio analysis.

    When port_analysis_config.strategy.class is ``VectorizedBiweeklyStrategy``,
    signals are pre-computed before the Qlib backtest so the strategy can use
    vectorized operations instead of per-bar D.features() calls.
    """
    logger.info("Running inference for backtest")
    pred_score = model.predict(dataset)
    if isinstance(pred_score, pd.Series):
        pred_score = pred_score.to_frame("score")

    try:
        labels = dataset.prepare(segments="test", col_set="label", data_key="label")
    except KeyError:
        labels = dataset.prepare(segments="test", col_set="label", data_key=DataHandler.DK_L)

    if recorder:
        from src.research.backtest_execution_policy import build_execution_receipt

        precompute_status = "not_required"
        # Pre-compute signals for vectorized strategy before PortAnaRecord
        if _is_vectorized_strategy(port_analysis_config):
            precompute = _precompute_for_vectorized(
                pred_score, dataset, port_analysis_config
            )
            precompute_status = str(precompute["status"])
        execution_receipt = build_execution_receipt(
            "authoritative_qlib", precompute_status=precompute_status
        )

        # Save both with and without .pkl suffix so PortAnaRecord's
        # SignalRecord dependency check (which looks for pred.pkl/label.pkl)
        # passes. R.save_objects uses the key as-is, while SignalRecord.generate
        # saves as pred.pkl.
        R.save_objects(pred=pred_score, label=labels)
        R.save_objects(
            **{
                "pred.pkl": pred_score,
                "label.pkl": labels,
                "backtest_execution_receipt": execution_receipt.to_dict(),
            }
        )
        pa_record = PortAnaRecord(recorder, port_analysis_config)
        pa_record.generate()

    return pred_score, labels
