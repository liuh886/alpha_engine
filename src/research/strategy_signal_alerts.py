"""Deterministic, research-only alerts for the current QQQI/QQQ/TQQQ baseline.

The alert layer does not generate a new signal. It converts the latest frozen
v4.2 close decision and currently executed weights into an explicit next-open
rebalance instruction. A signal is alertable only when the close decision state
differs from the latest executed state.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

ASSETS = ("QQQI", "QQQ", "TQQQ")
STATE_LABELS = {
    0: "QQQI 防守",
    1: "50% QQQI / 50% QQQ 过渡",
    2: "25% QQQ / 75% TQQQ 杠杆恢复",
}
TRANSITION_LABELS = {
    "open_risk_bridge": "开启风险过渡",
    "open_leveraged_recovery": "直接进入杠杆恢复",
    "add_tqqq_leverage": "增加 TQQQ 杠杆",
    "reduce_tqqq_leverage": "降低 TQQQ 杠杆",
    "return_to_defense": "回到 QQQI 防守",
    "exit_to_defense": "退出杠杆并转入防守",
    "rebalance": "调整组合",
}
REASON_LABELS = {
    "enter_qqq_early_repair_vix_easing": "QQQ 出现早期价格修复且 VIX 回落",
    "enter_partial_tqqq_vix_normalized_vxn_not_stressed": (
        "价格修复进一步确认、VIX 已正常化且 VXN 未处于压力状态"
    ),
    "exit_partial_tqqq_vix_vxn_or_ma20": (
        "VIX/VXN 压力上升或 QQQ 跌破短期趋势条件"
    ),
    "defensive_price_or_vix_stress": "价格防线失守或 VIX 压力显著上升",
    "hold": "继续保持当前状态",
}


def _target_weights(contract: Mapping[str, Any], state: int) -> dict[str, float]:
    portfolio = contract["portfolio"]
    key_by_state = {0: "state_0", 1: "state_1_bridge", 2: "state_2"}
    if state not in key_by_state:
        raise ValueError(f"unsupported decision state: {state}")
    raw = portfolio[key_by_state[state]]
    weights = {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}
    if any(value < 0.0 for value in weights.values()):
        raise ValueError("target weights must be non-negative")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("target weights must sum to one")
    return weights


def _normalise_weights(raw: Mapping[str, Any] | None) -> dict[str, float]:
    if raw is None:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}


def _orders(
    current: Mapping[str, float], target: Mapping[str, float]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        delta = float(target[asset]) - float(current[asset])
        if abs(delta) <= 1e-12:
            continue
        rows.append(
            {
                "asset": asset,
                "side": "buy" if delta > 0.0 else "sell",
                "weight_change": abs(delta),
                "from_weight": float(current[asset]),
                "to_weight": float(target[asset]),
            }
        )
    return rows


def _transition_type(current_state: int, target_state: int) -> str:
    mapping = {
        (0, 1): "open_risk_bridge",
        (0, 2): "open_leveraged_recovery",
        (1, 2): "add_tqqq_leverage",
        (2, 1): "reduce_tqqq_leverage",
        (1, 0): "return_to_defense",
        (2, 0): "exit_to_defense",
    }
    return mapping.get((current_state, target_state), "rebalance")


def build_signal_alert(
    prospective_summary: Mapping[str, Any],
    baseline_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one deduplicatable next-open alert from a monitor summary."""

    snapshot = prospective_summary.get("bridge_latest_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("bridge_latest_snapshot is missing")
    executed = snapshot.get("latest_executed_position")
    signal = snapshot.get("latest_close_signal")
    if not isinstance(executed, Mapping) or not isinstance(signal, Mapping):
        raise ValueError("latest executed position or close signal is missing")

    current_state = int(executed["position_state"])
    target_state = int(signal["decision_state"])
    current_weights = _normalise_weights(executed.get("weights"))
    target_weights = _target_weights(baseline_contract, target_state)
    order_rows = _orders(current_weights, target_weights)
    should_alert = current_state != target_state and bool(order_rows)
    signal_date = str(signal["signal_date"])
    fingerprint_payload = {
        "experiment_id": baseline_contract["experiment_id"],
        "signal_date": signal_date,
        "current_state": current_state,
        "target_state": target_state,
        "target_weights": target_weights,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]

    transition = _transition_type(current_state, target_state)
    decision_reason = str(signal.get("decision_reason", ""))
    alert = {
        "schema_version": "1.1",
        "experiment_id": baseline_contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "should_alert": should_alert,
        "fingerprint": fingerprint,
        "signal_date": signal_date,
        "execution_time": "next_session_open",
        "transition_type": transition,
        "transition_label": TRANSITION_LABELS[transition],
        "current_state": current_state,
        "current_state_label": STATE_LABELS[current_state],
        "target_state": target_state,
        "target_state_label": STATE_LABELS[target_state],
        "current_weights": current_weights,
        "target_weights": target_weights,
        "orders": order_rows,
        "decision_reason": decision_reason,
        "decision_reason_label": REASON_LABELS.get(
            decision_reason, "策略冻结规则触发状态变化"
        ),
        "market_context": {
            "vix_close": float(signal["vix_close"]),
            "vxn_close": float(signal["vxn_close"]),
            "vix_stress": bool(signal["vix_stress"]),
            "vix_easing": bool(signal["vix_easing"]),
            "vix_normalized": bool(signal["vix_normalized"]),
            "vxn_stress": bool(signal["vxn_stress"]),
        },
    }
    alert["title"] = (
        f"[策略信号] {signal_date} "
        f"{STATE_LABELS[current_state]} → {STATE_LABELS[target_state]}"
    )
    alert["markdown"] = render_signal_alert_markdown(alert)
    return alert


def render_signal_alert_markdown(alert: Mapping[str, Any]) -> str:
    """Render a concise GitHub/Telegram friendly alert message."""

    side_labels = {"buy": "买入", "sell": "卖出"}
    orders = alert.get("orders", [])
    order_lines = [
        f"- **{side_labels[str(item['side'])]} {float(item['weight_change']):.0%} "
        f"{item['asset']}**（{float(item['from_weight']):.0%} → "
        f"{float(item['to_weight']):.0%}）"
        for item in orders
    ]
    if not order_lines:
        order_lines = ["- 当前仓位已与信号一致，无需调整。"]
    context = alert["market_context"]
    lines = [
        f"## {alert['title']}",
        "",
        "> 研究信号，不是自动订单；当前模型仍未标记为可交易。",
        "",
        f"- 信号时间：**{alert['signal_date']} 美股收盘后**",
        "- 计划执行：**下一美股交易日开盘**",
        f"- 状态变化：**{alert['transition_label']}**",
        f"- 当前状态：**{alert['current_state_label']}**",
        f"- 目标状态：**{alert['target_state_label']}**",
        f"- 触发解释：{alert['decision_reason_label']}",
        f"- 规则代码：`{alert['decision_reason']}`",
        "",
        "### 目标调仓",
        *order_lines,
        "",
        "### 市场条件",
        f"- VIX：**{float(context['vix_close']):.2f}**；"
        f"压力={bool(context['vix_stress'])}；"
        f"回落={bool(context['vix_easing'])}；"
        f"正常化={bool(context['vix_normalized'])}",
        f"- VXN：**{float(context['vxn_close']):.2f}**；"
        f"压力={bool(context['vxn_stress'])}",
        "",
        f"<!-- signal-fingerprint:{alert['fingerprint']} -->",
    ]
    return "\n".join(lines) + "\n"
