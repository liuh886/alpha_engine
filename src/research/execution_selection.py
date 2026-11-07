"""Frozen E6 position selection; all returns/accounting remain in the existing engine."""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Callable

import numpy as np

Selection = Callable[[int, str, np.ndarray, np.ndarray], np.ndarray]


def ranked_indices(scores: np.ndarray, symbols: list[str], tie: str, salt: str) -> list[int]:
    if len(set(symbols)) != len(symbols) or len(scores) != len(symbols) or not np.isfinite(scores).all():
        raise ValueError("ranking requires unique symbols and complete finite scores")
    if tie == "symbol_asc":
        keys = sorted(symbols)
    elif tie == "symbol_desc":
        keys = sorted(symbols, reverse=True)
    elif tie == "symbol_sha256":
        keys = sorted(symbols, key=lambda s: (hashlib.sha256(f"{salt}|{s}".encode()).hexdigest(), s))
    else:
        raise ValueError("unfrozen tie rule")
    ordinal = {s: i for i, s in enumerate(keys)}
    return sorted(range(len(symbols)), key=lambda i: (-float(scores[i]), ordinal[symbols[i]]))


def make_selection(arm: dict, *, symbols: list[str], calendar: list[str],
                   salt: str, top_k: int = 5) -> Selection:
    if (len(symbols) < top_k or top_k < 1 or arm["min_hold"] < 0 or
            arm["exit_rank"] < top_k or calendar != sorted(set(calendar))):
        raise ValueError("invalid frozen execution selection")
    positions = {s: i for i, s in enumerate(calendar)}
    entered: dict[int, int] = {}

    def select(step: int, fill_session: str, scores: np.ndarray, drifted: np.ndarray) -> np.ndarray:
        pos = positions[fill_session]
        if step == 0:
            entered.clear()
        elif arm["weekly"]:
            current_week = date.fromisoformat(fill_session).isocalendar()[:2]
            previous_week = date.fromisoformat(calendar[pos-1]).isocalendar()[:2]
            if current_week == previous_week:
                return drifted.copy()  # no hidden daily equal-weight resizing
        order = ranked_indices(scores, symbols, arm["tie"], salt)
        rank = {idx: n+1 for n, idx in enumerate(order)}
        incumbents = list(np.flatnonzero(drifted > 0))
        retained = [i for i in incumbents if
                    pos-entered[i] < arm["min_hold"] or
                    (arm["exit_rank"] > top_k and rank[i] <= arm["exit_rank"])]
        selected = retained + [i for i in order if i not in retained][:top_k-len(retained)]
        if len(selected) != top_k:
            raise ValueError("selection did not retain the frozen portfolio size")
        for i in selected:
            if i not in incumbents:
                entered[i] = pos
        entered_keys = set(selected)
        for i in list(entered):
            if i not in entered_keys:
                del entered[i]
        if (step and not arm["weekly"] and
                (arm["min_hold"] or arm["exit_rank"] > top_k) and
                set(selected) == set(incumbents)):
            return drifted.copy()
        target = np.zeros(len(symbols))
        target[selected] = 1.0/top_k
        return target

    return select
