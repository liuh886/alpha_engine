"""Tests for XGBoost workflow YAML configuration."""

import yaml


def test_us_xgb_config_loads():
    """US XGB YAML parses and has correct model class."""
    with open("configs/us_xgb_workflow.yaml") as f:
        cfg = yaml.safe_load(f)

    assert cfg["task"]["model"]["class"] == "XGBModel"
    assert cfg["task"]["model"]["module_path"] == "qlib.contrib.model.xgboost"


def test_cn_xgb_config_loads():
    """CN XGB YAML parses and has correct model class."""
    with open("configs/cn_xgb_workflow.yaml") as f:
        cfg = yaml.safe_load(f)

    assert cfg["task"]["model"]["class"] == "XGBModel"
    assert cfg["task"]["model"]["module_path"] == "qlib.contrib.model.xgboost"


def test_us_xgb_model_kwargs():
    """US XGB config has the required hyperparameters."""
    with open("configs/us_xgb_workflow.yaml") as f:
        cfg = yaml.safe_load(f)

    kwargs = cfg["task"]["model"]["kwargs"]
    assert kwargs["max_depth"] == 6
    assert kwargs["learning_rate"] == 0.05
    assert kwargs["n_estimators"] == 1000
    assert kwargs["subsample"] == 0.8
    assert kwargs["colsample_bytree"] == 0.8
    assert kwargs["early_stopping_rounds"] == 50
    assert kwargs["eval_metric"] == "rmse"


def test_cn_xgb_model_kwargs():
    """CN XGB config has the required hyperparameters."""
    with open("configs/cn_xgb_workflow.yaml") as f:
        cfg = yaml.safe_load(f)

    kwargs = cfg["task"]["model"]["kwargs"]
    assert kwargs["max_depth"] == 6
    assert kwargs["learning_rate"] == 0.05
    assert kwargs["n_estimators"] == 1000
    assert kwargs["subsample"] == 0.8
    assert kwargs["colsample_bytree"] == 0.8
    assert kwargs["early_stopping_rounds"] == 50
    assert kwargs["eval_metric"] == "rmse"


def test_xgb_config_preserves_features_and_labels():
    """XGB config retains the same feature set as LGBM."""
    with open("configs/us_lgbm_workflow.yaml") as f:
        lgbm_cfg = yaml.safe_load(f)
    with open("configs/us_xgb_workflow.yaml") as f:
        xgb_cfg = yaml.safe_load(f)

    lgbm_features = lgbm_cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"][
        "kwargs"
    ]["config"]["feature"]
    xgb_features = xgb_cfg["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["data_loader"][
        "kwargs"
    ]["config"]["feature"]
    assert lgbm_features == xgb_features


def test_xgb_config_preserves_segments():
    """XGB config retains the same train/valid/test segments."""
    with open("configs/us_lgbm_workflow.yaml") as f:
        lgbm_cfg = yaml.safe_load(f)
    with open("configs/us_xgb_workflow.yaml") as f:
        xgb_cfg = yaml.safe_load(f)

    lgbm_seg = lgbm_cfg["task"]["dataset"]["kwargs"]["segments"]
    xgb_seg = xgb_cfg["task"]["dataset"]["kwargs"]["segments"]
    assert lgbm_seg == xgb_seg


def test_xgb_config_preserves_port_analysis():
    """XGB config retains the same port_analysis_config."""
    with open("configs/us_lgbm_workflow.yaml") as f:
        lgbm_cfg = yaml.safe_load(f)
    with open("configs/us_xgb_workflow.yaml") as f:
        xgb_cfg = yaml.safe_load(f)

    assert lgbm_cfg["port_analysis_config"] == xgb_cfg["port_analysis_config"]


def test_xgb_config_preserves_market_and_benchmark():
    """XGB config retains market and benchmark settings."""
    with open("configs/us_xgb_workflow.yaml") as f:
        us_cfg = yaml.safe_load(f)
    with open("configs/cn_xgb_workflow.yaml") as f:
        cn_cfg = yaml.safe_load(f)

    assert us_cfg["market"] == "us"
    assert us_cfg["benchmark"] == "QQQ"
    assert cn_cfg["market"] == "cn"
    assert cn_cfg["benchmark"] == "000300"


def test_xgb_model_class_resolves():
    """XGBModel class can be imported from qlib.contrib.model.xgboost."""
    from qlib.contrib.model.xgboost import XGBModel

    assert XGBModel is not None
