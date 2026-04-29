import numpy as np
import pandas as pd


def calculate_max_drawdown(returns: pd.Series) -> float:
    cumulative = (1 + returns).cumprod()
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    return drawdown.min()


def calculate_annualized_return(returns: pd.Series, annualization_factor: int = 252) -> float:
    cumulative = (1 + returns).cumprod().iloc[-1]
    n_days = len(returns)
    if n_days == 0:
        return 0.0
    return (cumulative ** (annualization_factor / n_days)) - 1


def calculate_sharpe(
    returns: pd.Series, risk_free: float = 0.0, annualization_factor: int = 252
) -> float:
    mean_ret = returns.mean() * annualization_factor
    vol = returns.std() * np.sqrt(annualization_factor)
    if vol == 0:
        return 0.0
    return (mean_ret - risk_free) / vol


def get_metrics(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> dict:
    excess = strategy_returns - benchmark_returns

    return {
        "Annualized Return": calculate_annualized_return(strategy_returns),
        "Excess Return": calculate_annualized_return(excess),
        "Max Drawdown": calculate_max_drawdown(strategy_returns),
        "Sharpe Ratio": calculate_sharpe(strategy_returns),
        "Win Rate": (strategy_returns > 0).mean(),
    }
