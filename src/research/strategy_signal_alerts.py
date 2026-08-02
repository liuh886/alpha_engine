"""Decision-grade, research-only alerts for the current QQQI/QQQ/TQQQ baseline.

The alert layer never generates a new trading signal. It converts the latest
frozen v4.2 close decision and currently executed weights into an explicit
next-open decision card. Alerts are emitted only for fresh state changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

ASSETS = ("QQQI", "QQQ", "TQQQ")
TELEGRAM_MESSAGE_LIMIT = 4096
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


def _fmt_percent(value: Any, digits: int = 2) -> str:
    if value is None:
        return "不可用"
    return f"{float(value):.{digits}%}"


def _fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "不可用"
    return f"{float(value):.{digits}f}"


def _decision_support(
    policy: Mapping[str, Any] | None, transition: str
) -> dict[str, str]:
    if policy is None:
        return {}
    root = policy.get("alert_decision_support", {})
    if not isinstance(root, Mapping):
        return {}
    transitions = root.get("transitions", {})
    if not isinstance(transitions, Mapping):
        return {}
    raw = transitions.get(transition, {})
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def build_signal_alert(
    prospective_summary: Mapping[str, Any],
    baseline_contract: Mapping[str, Any],
    baseline_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one deduplicatable next-open decision card from a monitor summary."""

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
    signal_date = str(signal["signal_date"])
    latest_data_date = str(prospective_summary.get("latest_data_date") or signal_date)
    data_freshness_ok = signal_date == latest_data_date
    should_alert = (
        current_state != target_state and bool(order_rows) and data_freshness_ok
    )
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
    turnover_units = float(sum(row["weight_change"] for row in order_rows))
    cost_bps = float(
        baseline_contract["portfolio"]["transaction_cost_bps_per_turnover_unit"]
    )
    estimated_transaction_cost = turnover_units * cost_bps / 10_000.0
    provider_identity = prospective_summary.get("data_identity", {})
    if not isinstance(provider_identity, Mapping):
        provider_identity = {}
    support = _decision_support(baseline_policy, transition)

    alert = {
        "schema_version": "2.0",
        "experiment_id": baseline_contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "should_alert": should_alert,
        "fingerprint": fingerprint,
        "signal_date": signal_date,
        "latest_data_date": latest_data_date,
        "data_freshness_ok": data_freshness_ok,
        "execution_time": "next_session_open",
        "transition_type": transition,
        "transition_label": TRANSITION_LABELS[transition],
        "current_state": current_state,
        "current_state_label": STATE_LABELS[current_state],
        "current_state_entry_date": executed.get("state_entry_date"),
        "current_state_age_sessions": executed.get("state_age_sessions"),
        "target_state": target_state,
        "target_state_label": STATE_LABELS[target_state],
        "current_weights": current_weights,
        "target_weights": target_weights,
        "orders": order_rows,
        "turnover_units": turnover_units,
        "transaction_cost_bps_per_turnover_unit": cost_bps,
        "estimated_transaction_cost": estimated_transaction_cost,
        "decision_reason": decision_reason,
        "decision_reason_label": REASON_LABELS.get(
            decision_reason, "策略冻结规则触发状态变化"
        ),
        "price_context": dict(signal.get("price_context", {})),
        "volatility_context": dict(signal.get("volatility_context", {})),
        "decision_support": support,
        "data_context": {
            "mode": provider_identity.get("mode"),
            "bundle_id": provider_identity.get("bundle_id"),
            "selected_providers": provider_identity.get("selected_providers"),
            "latest_data_date": latest_data_date,
        },
    }
    alert["title"] = (
        f"[策略信号] {signal_date} "
        f"{STATE_LABELS[current_state]} → {STATE_LABELS[target_state]}"
    )
    alert["markdown"] = render_signal_alert_markdown(alert)
    alert["telegram_text"] = render_signal_alert_telegram(alert)
    return alert


def _order_lines(alert: Mapping[str, Any], *, markdown: bool) -> list[str]:
    side_labels = {"buy": "买入", "sell": "卖出"}
    rows = []
    for item in alert.get("orders", []):
        text = (
            f"{side_labels[str(item['side'])]} "
            f"{float(item['weight_change']):.0%} {item['asset']} "
            f"（{float(item['from_weight']):.0%} → "
            f"{float(item['to_weight']):.0%}）"
        )
        rows.append(f"- **{text}**" if markdown else f"• {text}")
    if rows:
        return rows
    return [
        "- 当前仓位已与信号一致，无需调整。"
        if markdown
        else "• 当前仓位已与信号一致，无需调整。"
    ]


def render_signal_alert_markdown(alert: Mapping[str, Any]) -> str:
    """Render the durable, detailed GitHub decision record."""

    price = alert.get("price_context", {})
    vol = alert.get("volatility_context", {})
    support = alert.get("decision_support", {})
    freshness = "通过" if alert["data_freshness_ok"] else "失败：禁止执行"
    age = alert.get("current_state_age_sessions")
    age_text = f"{int(age)} 个交易日" if age is not None else "不可用"
    lines = [
        f"## {alert['title']}",
        "",
        "> 研究信号，不是自动订单；当前模型仍未标记为可交易。",
        "",
        "### 决策摘要",
        "",
        f"- 信号时间：**{alert['signal_date']} 美股收盘后**",
        "- 计划执行：**下一美股交易日开盘**",
        f"- 数据新鲜度：**{freshness}**（最新数据 {alert['latest_data_date']}）",
        f"- 状态变化：**{alert['transition_label']}**",
        f"- 当前状态：**{alert['current_state_label']}**，已持续 **{age_text}**",
        f"- 目标状态：**{alert['target_state_label']}**",
        f"- 触发解释：{alert['decision_reason_label']}",
        f"- 规则代码：`{alert['decision_reason']}`",
        "",
        "### 目标调仓与模型成本",
        "",
        *_order_lines(alert, markdown=True),
        f"- 组合换手单位：**{float(alert['turnover_units']):.2f}**",
        f"- 模型成本估计：**{_fmt_percent(alert['estimated_transaction_cost'])}**"
        f"（{float(alert['transaction_cost_bps_per_turnover_unit']):.0f} bps/换手单位）",
        "",
        "### 价格与趋势位置",
        "",
        f"- QQQ 收盘：**{_fmt_number(price.get('qqq_close'))}**",
        f"- 相对 MA20 / MA50 / MA200："
        f"**{_fmt_percent(price.get('qqq_vs_ma20'))} / "
        f"{_fmt_percent(price.get('qqq_vs_ma50'))} / "
        f"{_fmt_percent(price.get('qqq_vs_ma200'))}**",
        f"- 63日高点回撤：**{_fmt_percent(price.get('shock_drawdown_now'))}**；"
        f"冲击记忆={bool(price.get('shock_memory', False))}",
        f"- 修复条件：早期={bool(price.get('early_repair', False))}；"
        f"中期={bool(price.get('medium_repair', False))}；"
        f"二次确认={bool(price.get('secondary_confirmation', False))}",
        "",
        "### 波动率条件",
        "",
        f"- VIX：**{_fmt_number(vol.get('vix_close'))}**；"
        f"正常阈值={_fmt_number(vol.get('vix_q_normal'))}；"
        f"压力阈值={_fmt_number(vol.get('vix_q_stress'))}；"
        f"距20日峰值={_fmt_percent(vol.get('vix_retreat_from_peak'))}",
        f"- VXN：**{_fmt_number(vol.get('vxn_close'))}**；"
        f"正常阈值={_fmt_number(vol.get('vxn_q_normal'))}；"
        f"压力阈值={_fmt_number(vol.get('vxn_q_stress'))}；"
        f"距20日峰值={_fmt_percent(vol.get('vxn_retreat_from_peak'))}",
        "",
        "### 决策证据与后续观察",
        "",
        f"- 信号置信层级：**{support.get('confidence', '未配置')}**",
        f"- 历史证据：{support.get('historical_evidence', '未配置')}",
        f"- 下一确认条件：{support.get('next_confirmation', '按冻结状态机继续观察')}",
        f"- 失效/反转条件：{support.get('invalidation', '按冻结状态机继续观察')}",
        f"- 主要风险：{support.get('principal_risk', '历史样本较短，结果存在集中度风险')}",
        "",
        "### 执行纪律",
        "",
        "- 模型假设按下一交易日开盘成交；实际滑点、税费和成交价可能不同。",
        "- 若出现数据异常、停牌或极端跳空，应暂停并记录偏离，不能默默修改模型证据。",
        "- 提醒仅代表目标仓位变化，不代表保证获利。",
        "",
        f"<!-- signal-fingerprint:{alert['fingerprint']} -->",
    ]
    return "\n".join(lines) + "\n"


def render_signal_alert_telegram(alert: Mapping[str, Any]) -> str:
    """Render a plain-text Telegram card that remains below Telegram limits."""

    price = alert.get("price_context", {})
    vol = alert.get("volatility_context", {})
    support = alert.get("decision_support", {})
    age = alert.get("current_state_age_sessions")
    age_text = f"{int(age)}日" if age is not None else "未知"
    freshness = "✅" if alert["data_freshness_ok"] else "❌ 禁止执行"
    lines = [
        f"🔔 Alpha Engine v4.2｜{alert['transition_label']}",
        "",
        f"信号：{alert['signal_date']} 收盘",
        "执行：下一美股交易日开盘",
        f"数据：{alert['latest_data_date']} {freshness}",
        f"状态：{alert['current_state_label']}（已{age_text}） → {alert['target_state_label']}",
        "",
        "【目标调仓】",
        *_order_lines(alert, markdown=False),
        f"• 换手 {float(alert['turnover_units']):.2f}；"
        f"模型成本约 {_fmt_percent(alert['estimated_transaction_cost'])}",
        "",
        "【为什么现在】",
        f"• {alert['decision_reason_label']}",
        f"• QQQ {_fmt_number(price.get('qqq_close'))}；"
        f"距 MA20/50/200：{_fmt_percent(price.get('qqq_vs_ma20'))} / "
        f"{_fmt_percent(price.get('qqq_vs_ma50'))} / "
        f"{_fmt_percent(price.get('qqq_vs_ma200'))}",
        f"• 63日高点回撤 {_fmt_percent(price.get('shock_drawdown_now'))}；"
        f"早期修复={bool(price.get('early_repair', False))}；"
        f"中期确认={bool(price.get('medium_repair', False))}",
        f"• VIX {_fmt_number(vol.get('vix_close'))}"
        f"（正常/压力阈值 {_fmt_number(vol.get('vix_q_normal'))}/"
        f"{_fmt_number(vol.get('vix_q_stress'))}）",
        f"• VXN {_fmt_number(vol.get('vxn_close'))}"
        f"（压力阈值 {_fmt_number(vol.get('vxn_q_stress'))}）",
        "",
        "【证据与风险】",
        f"• 置信层级：{support.get('confidence', '未配置')}",
        f"• 历史：{support.get('historical_evidence', '未配置')}",
        f"• 下一确认：{support.get('next_confirmation', '按冻结状态机观察')}",
        f"• 反转条件：{support.get('invalidation', '按冻结状态机观察')}",
        f"• 风险：{support.get('principal_risk', '样本较短，结果存在集中度风险')}",
        "",
        "研究信号，不自动下单。若数据异常、停牌或极端跳空，暂停并记录偏离。",
        f"ID: {alert['fingerprint']}",
    ]
    text = "\n".join(lines) + "\n"
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        raise ValueError(f"Telegram alert exceeds {TELEGRAM_MESSAGE_LIMIT} characters")
    return text
