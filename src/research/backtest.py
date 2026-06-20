import pandas as pd
from qlib.data.dataset.handler import DataHandler
from qlib.workflow import R
from qlib.workflow.record_temp import PortAnaRecord

from src.common.logging import get_logger

logger = get_logger(__name__)


def run_backtest(
    model: object, dataset: object, port_analysis_config: dict, recorder: object = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run inference and portfolio analysis.
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
        # Save both with and without .pkl suffix so PortAnaRecord's
        # SignalRecord dependency check (which looks for pred.pkl/label.pkl)
        # passes. R.save_objects uses the key as-is, while SignalRecord.generate
        # saves as pred.pkl.
        R.save_objects(pred=pred_score, label=labels)
        R.save_objects(**{"pred.pkl": pred_score, "label.pkl": labels})
        pa_record = PortAnaRecord(recorder, port_analysis_config)
        pa_record.generate()

    return pred_score, labels
