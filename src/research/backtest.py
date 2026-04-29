import pandas as pd
from qlib.data.dataset.handler import DataHandler
from qlib.workflow import R
from qlib.workflow.record_temp import PortAnaRecord


def run_backtest(
    model: object, dataset: object, port_analysis_config: dict, recorder: object = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run inference and portfolio analysis.
    """
    print("Running Inference for Backtest...")
    pred_score = model.predict(dataset)
    if isinstance(pred_score, pd.Series):
        pred_score = pred_score.to_frame("score")

    try:
        labels = dataset.prepare(segments="test", col_set="label", data_key="label")
    except KeyError:
        labels = dataset.prepare(segments="test", col_set="label", data_key=DataHandler.DK_L)

    if recorder:
        R.save_objects(pred=pred_score, label=labels)
        pa_record = PortAnaRecord(recorder, port_analysis_config)
        pa_record.generate()

    return pred_score, labels
