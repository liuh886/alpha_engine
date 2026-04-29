from datetime import date


def is_rebalance_day(trade_step: int, rebalance_steps: int) -> bool:
    if rebalance_steps <= 0:
        return True
    return trade_step % rebalance_steps == 0


def can_sell(entry_date: date, current_date: date, min_hold_days: int) -> bool:
    if not entry_date or not current_date:
        return True
    delta = (current_date - entry_date).days
    return delta >= min_hold_days
