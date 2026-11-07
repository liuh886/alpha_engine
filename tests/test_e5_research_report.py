"""Report attribution ranks by numeric value after canonical JSON sorting."""
import json

import pytest

from src.research.e5_research_report import FOLDS, collect, render
from src.research.e5_score_reconstruction import SHORTLIST, sha


def fixture_results(tmp_path):
    for cfg in SHORTLIST:
        for fold in FOLDS:
            path = tmp_path / cfg / fold
            path.mkdir(parents=True)
            names = ("original-daily.parquet", "original-assets.parquet",
                     "delayed-daily.parquet", "delayed-assets.parquet")
            for name in names:
                (path / name).write_bytes(b"test-data")
            summary = {"net_return": .2, "qqq_return": .1, "sessions": 100,
                "net_excess": .1, "max_drawdown": -.1,"turnover": 5.,
                "cost_loss_cumulative": .01,"max_drifted_weight": .25,
                "top5_positive_pnl_share": .9,"mean_new_names_per_day": 1.,
                "asset_pnl_nav_units":{"ZZZ": .2,"AAA":-.1,"MID": .1}}
            row = {"configuration_id":cfg,"fold_id":fold,"original":summary,"delayed":summary,
                   "evaluator_code_sha256":{"pipeline":"a"},"source_snapshot_sha256":"b",
                   "parity":{"status":"E4_DAILY_AND_AGGREGATE_PARITY_PASS"},
                   "signal_ic":{"rank_ic_5d":{"mean":.1}},"research_only":True,"trade_ready":False,
                   "files":{name:sha(path / name) for name in names},
                   "score_diagnostics":{"decision_dates":100,"top5_cutoff_tied_decisions":10,
                       "published_signal_set_differs_from_engine_holdings_dates":5}}
            (path / "result.json").write_text(json.dumps(row,sort_keys=True))


def test_report_ranks_actual_pnl_not_alphabetical_symbol_order(tmp_path):
    fixture_results(tmp_path)
    report = collect(tmp_path)
    text = render(report)
    assert report["verified_config_folds"] == 32
    assert text.index("|ZZZ|20.00|") < text.index("|AAA|-10.00|")


def test_rejects_mixed_revisions_and_unpaired_benchmark(tmp_path):
    fixture_results(tmp_path)
    path = tmp_path / "xgb_p03" / FOLDS[1] / "result.json"
    row = json.loads(path.read_text())
    row["evaluator_code_sha256"] = {"pipeline":"changed"}
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError,match="mixes evaluator"):
        collect(tmp_path)
    row["evaluator_code_sha256"] = {"pipeline":"a"}
    row["original"]["qqq_return"] = .2
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError,match="not aligned"):
        collect(tmp_path)
