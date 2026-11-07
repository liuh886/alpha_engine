import json
from pathlib import Path

import pytest

from src.research.e6_execution import compare, contract

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    cfg=contract(ROOT/"configs/research_experiments/e6_us73_execution_policy_v1.json")
    rows=[]
    for arm in cfg["arms"]:
        for strategy in cfg["strategies"]:
            for fold in cfg["folds"]:
                rows.append({"arm_id":arm["id"],"configuration_id":strategy,"fold_id":fold,
                    "summary":{"net_return":.2 if strategy.startswith(('xgb','lgb')) else .1,
                        "turnover":10.,"sessions":100,"qqq_return":.05}})
    return cfg,rows


def test_predeclared_screen_rejects_excess_turnover_even_with_higher_returns():
    cfg,rows=fixture()
    assert compare(rows,cfg)["primary_model_screens"]["xgb_p03"] is True
    for row in rows:
        if row["configuration_id"]=="xgb_p03":
            row["summary"]["turnover"]=16.
    result=compare(rows,cfg)
    assert result["primary_model_screens"]["xgb_p03"] is False
    assert result["primary_model_screens"]["lgb_p05"] is True


def test_no_partial_matrix_or_unpaired_calendar_can_pass():
    cfg,rows=fixture()
    with pytest.raises(ValueError,match="incomplete"):
        compare(rows[:-1],cfg)
    rows[0]["summary"]["sessions"]-=1
    with pytest.raises(ValueError,match="calendar aligned"):
        compare(rows,cfg)


def test_contract_changes_require_new_identity(tmp_path):
    cfg,_=fixture()
    cfg["primary_forward_policy"]="daily_hash"
    path=tmp_path/"modified.json";path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match="frozen bytes"):
        contract(path)
