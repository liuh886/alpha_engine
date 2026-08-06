"""Decision-grade, research-only alerts for the current BYD v1.2 baseline.

The alert layer never generates a new trading signal. It converts the latest
frozen v1.2 close decision (base V1.0 signal + v1.2 expansion overlay) into
an explicit next-open decision card. Alerts are emitted only for fresh state
changes with confirmed data eligibility.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

ASSETS = ("BYD", "515180", "CASH")
TELEGRAM_MESSAGE_LIMIT = 4096

STATE_LABELS = {
    0: "V1.0 防守 (75% BYD / 25% 515180)",
    1: "V1.0 进攻 (100% BYD)",
    2: "V1.2 趋势扩张 (110% BYD / -10% 融资)",
}

TRANSITION_LABELS = {
    "enter_defense": "进入防守",
    "enter_offense": "进入进攻",
    "expansion_on": "触发趋势扩张",
    "expansion_off": "退出趋势扩张",
    "rebalance": "调整组合",
}


def _normalise_weights(raw: Mapping[str, Any] | None) -> dict[str, float]:
    if raw is None:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}


def _decide_state(base_target: float, expansion_active: bool) -> int:
    """Map base signal + expansion overlay to combined state."""
    if expansion_active and base_target >= 0.99:
        return 2  # expansion: 110% BYD
    elif base_target >= 0.99:
        return 1  # offense: 100% BYD
    else:
        return 0  # defense: 75% BYD / 25% 515180


def _target_weights(state: int) -> dict[str, float]:
    if state == 2:
        return {"BYD": 1.10, "515180": 0.0, "CASH": -0.10}
    elif state == 1:
        return {"BYD": 1.00, "515180": 0.0, "CASH": 0.0}
    else:
        return {"BYD": 0.75, "515180": 0.25, "CASH": 0.0}


def _transition_type(current_state: int, target_state: int) -> str:
    mapping = {
        (0, 1): "enter_offense",
        (1, 0): "enter_defense",
        (1, 2): "expansion_on",
        (2, 1): "expansion_off",
        (0, 2): "expansion_on",    # defense → expansion (rare)
        (2, 0): "expansion_off",   # expansion → defense
    }
    return mapping.get((current_state, target_state), "rebalance")


def _orders(current: Mapping[str, float], target: Mapping[str, float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        delta = float(target[asset]) - float(current[asset])
        if abs(delta) <= 1e-12:
            continue
        rows.append({
            "asset": asset,
            "side": "buy" if delta > 0.0 else "sell",
            "weight_change": abs(delta),
            "from_weight": float(current[asset]),
            "to_weight": float(target[asset]),
        })
    return rows


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None: return "N/A"
    return f"{float(value):.{digits}%}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None: return "N/A"
    return f"{float(value):.{digits}f}"


def build_byd_signal_alert(
    shadow_obs: Mapping[str, Any],
    paired_obs: Mapping[str, Any] | None,
    expansion_obs: Mapping[str, Any] | None,
    previous_state: int | None = None,
) -> dict[str, Any]:
    """Build one deduplicatable next-open decision card for BYD.

    Parameters
    ----------
    shadow_obs : Latest BYD prospective shadow observation (contains base_target_position, factors, OHLCV)
    paired_obs : Latest BYD/515180 paired observation (contains ETF prices, eligibility)
    expansion_obs : Latest v1.2 trend-expansion observation (contains trend_expansion_active)
    previous_state : Previously reported combined state, or None for first run
    """

    base_target = float(shadow_obs.get("base_target_position", 0.75))
    expansion_active = bool((expansion_obs or {}).get("trend_expansion_active", False))
    target_state = _decide_state(base_target, expansion_active)

    signal_date = str(shadow_obs.get("signal_date", ""))
    latest_data_date = signal_date
    open_eligible = bool(shadow_obs.get("open_research_eligible", False))
    data_freshness_ok = bool(shadow_obs.get("prospective_eligible", False))

    target_weights = _target_weights(target_state)
    current_weights = _target_weights(previous_state) if previous_state is not None else target_weights

    should_alert = (
        previous_state is not None
        and target_state != previous_state
        and data_freshness_ok
        and open_eligible
    )

    fingerprint_payload = {
        "experiment_id": "byd_v1_2_relaxed_trend_expansion",
        "signal_date": signal_date,
        "base_target": base_target,
        "expansion_active": expansion_active,
        "target_state": target_state,
        "target_weights": target_weights,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]

    transition = _transition_type(
        previous_state if previous_state is not None else target_state,
        target_state,
    )

    order_rows = _orders(current_weights, target_weights)
    turnover_units = float(sum(r["weight_change"] for r in order_rows))

    factors = shadow_obs.get("factors", {})
    paired_factors = (paired_obs or {}).get("factors", {}) if isinstance(paired_obs, dict) else {}
    chain = shadow_obs.get("chain_linked_adjusted_ohlcv", {})
    primary = shadow_obs.get("primary_raw_ohlcv", {})

    alert = {
        "schema_version": "1.0",
        "experiment_id": "byd_v1_2_relaxed_trend_expansion",
        "research_only": True,
        "trade_ready": False,
        "should_alert": should_alert,
        "fingerprint": fingerprint,
        "signal_date": signal_date,
        "latest_data_date": latest_data_date,
        "data_freshness_ok": data_freshness_ok,
        "open_research_eligible": open_eligible,
        "execution_time": "next_cn_session_open_t_plus_1",
        "transition_type": transition,
        "transition_label": TRANSITION_LABELS.get(transition, transition),
        "previous_state": previous_state,
        "target_state": target_state,
        "target_state_label": STATE_LABELS[target_state],
        "base_target": base_target,
        "expansion_active": expansion_active,
        "current_weights": current_weights,
        "target_weights": target_weights,
        "orders": order_rows,
        "turnover_units": turnover_units,
        "transaction_cost_bps": 20.0,
        "estimated_transaction_cost": turnover_units * 20.0 / 10000.0,
        "price_context": {
            "byd_close": float(chain.get("close", primary.get("close", 0))),
            "byd_open": float(chain.get("open", primary.get("open", 0))),
        },
        "factor_context": {
            "market_state": str(factors.get("market_state", "")),
            "vol_state": str(factors.get("vol_state", "")),
            "drawdown_252": float(factors.get("drawdown_252", 0)),
            "momentum_accel_20_60": float(factors.get("momentum_accel_20_60", 0)),
            "open_return_autocorr_20": float(factors.get("open_return_autocorr_20", 0)),
            "distance_from_low_20": float(factors.get("distance_from_low_20", 0)),
        },
        "data_identity": {
            "data_version": str(shadow_obs.get("data_version", "")),
            "shadow_sha256": str(shadow_obs.get("provider_payload_sha256", "")),
        },
    }

    alert["title"] = (
        f"[BYD信号] {signal_date} "
        f"{STATE_LABELS[target_state]}"
    ) if should_alert else (
        f"[BYD信号] {signal_date} 无变化 ({STATE_LABELS[target_state]})"
    )

    alert["markdown"] = _render_markdown(alert)
    alert["telegram_text"] = _render_telegram(alert)
    return alert


def _order_lines(alert: Mapping[str, Any], *, markdown: bool) -> list[str]:
    side_labels = {"buy": "买入", "sell": "卖出"}
    rows = []
    for item in alert.get("orders", []):
        asset = str(item["asset"])
        if asset == "CASH":
            side = "融资" if item["side"] == "sell" else "还款"
            text = (
                f"{side} {float(item['weight_change']):.0%} 现金 "
                f"({float(item['from_weight']):.0%} → {float(item['to_weight']):.0%})"
            )
        else:
            text = (
                f"{side_labels[str(item['side'])]} "
                f"{float(item['weight_change']):.0%} {asset} "
                f"({float(item['from_weight']):.0%} → {float(item['to_weight']):.0%})"
            )
        rows.append(f"- **{text}**" if markdown else f"• {text}")
    return rows or (["- 当前仓位与信号一致"] if markdown else ["• 当前仓位与信号一致"])


def _render_markdown(alert: Mapping[str, Any]) -> str:
    price = alert.get("price_context", {})
    factors = alert.get("factor_context", {})
    freshness = "通过" if alert["data_freshness_ok"] else "失败：禁止执行"
    eligibility = "通过" if alert["open_research_eligible"] else "隔离（开盘数据未确认）"

    lines = [
        f"## {alert['title']}",
        "",
        "> 研究信号，非自动订单。当前模型未标记为可交易。",
        "",
        "### 决策摘要",
        "",
        f"- 信号时间：**{alert['signal_date']} A股收盘后**",
        f"- 计划执行：**下一A股交易日开盘**",
        f"- 数据新鲜度：**{freshness}**（最新数据 {alert['latest_data_date']}）",
        f"- 开盘确认：**{eligibility}**",
        f"- 状态变化：**{alert['transition_label']}**",
        f"- 目标状态：**{alert['target_state_label']}**",
        f"- V1.0 基准信号：**{'进攻 (100%)' if alert['base_target'] > 0.9 else '防守 (75%)'}**",
        f"- V1.2 趋势扩张：**{'激活' if alert['expansion_active'] else '未激活'}**",
        "",
        "### 目标调仓与成本",
        "",
        *_order_lines(alert, markdown=True),
        f"- 组合换手：**{float(alert['turnover_units']):.2f}**",
        f"- 模型成本估计：**{_fmt_pct(alert['estimated_transaction_cost'])}**（20 bps/换手单位）",
        "",
        "### 价格与趋势位置",
        "",
        f"- BYD 收盘：**{_fmt_num(price.get('byd_close'))}**",
        f"- BYD 开盘：**{_fmt_num(price.get('byd_open'))}**",
        f"- 市场状态：**{factors.get('market_state', 'N/A')}**",
        f"- 波动率状态：**{factors.get('vol_state', 'N/A')}**",
        f"- 252日回撤：**{_fmt_pct(factors.get('drawdown_252'))}**",
        f"- 20/60日动量加速：**{_fmt_num(factors.get('momentum_accel_20_60'), 4)}**",
        f"- 20日开盘收益自相关：**{_fmt_num(factors.get('open_return_autocorr_20'), 4)}**",
        f"- 距20日低点距离：**{_fmt_pct(factors.get('distance_from_low_20'))}**",
        "",
        "### V1.2 扩张触发条件",
        "",
        f"- 基准权重需为 100%（进攻状态）：**{'满足' if alert['base_target'] > 0.9 else '不满足'}**",
        f"- 市场状态需为 bull：**{'满足' if factors.get('market_state') == 'bull' else '不满足'}**",
        f"- 20日动量 > 1%：**{'满足' if float(factors.get('momentum_accel_20_60', 0)) > 0 else '不满足'}**",
        f"- 252日回撤 > -15%：**{'满足' if float(factors.get('drawdown_252', -1)) > -0.15 else '不满足'}**",
        "",
        "### 执行纪律",
        "",
        "- 模型假设按下一交易日开盘成交；实际滑点和成交价可能不同。",
        "- 若出现开盘隔离（open_quarantined），应延迟至下一确认开盘。",
        "- 提醒仅代表目标仓位变化，不代表保证获利。",
        "",
        f"<!-- signal-fingerprint:{alert['fingerprint']} -->",
    ]
    return "\n".join(lines) + "\n"


def _render_telegram(alert: Mapping[str, Any]) -> str:
    price = alert.get("price_context", {})
    factors = alert.get("factor_context", {})
    freshness = "✅" if alert["data_freshness_ok"] else "❌"
    eligibility = "✅" if alert["open_research_eligible"] else "⚠️ 隔离"

    lines = [
        f"🔔 Alpha Engine BYD v1.2｜{alert['transition_label']}",
        "",
        f"信号：{alert['signal_date']} A股收盘",
        "执行：下一A股交易日开盘",
        f"数据：{alert['latest_data_date']} {freshness} 开盘{eligibility}",
        f"状态：{alert['target_state_label']}",
        f"基准：{'进攻 100%' if alert['base_target'] > 0.9 else '防守 75%'}｜扩张：{'激活' if alert['expansion_active'] else '未激活'}",
        "",
        "【目标调仓】",
        *_order_lines(alert, markdown=False),
        f"• 换手 {float(alert['turnover_units']):.2f}｜成本约 {_fmt_pct(alert['estimated_transaction_cost'])}",
        "",
        "【价格与趋势】",
        f"• BYD 收盘 {_fmt_num(price.get('byd_close'))}｜开盘 {_fmt_num(price.get('byd_open'))}",
        f"• 市场：{factors.get('market_state', 'N/A')}｜波动率：{factors.get('vol_state', 'N/A')}",
        f"• 252日回撤 {_fmt_pct(factors.get('drawdown_252'))}",
        f"• 20/60动量加速 {_fmt_num(factors.get('momentum_accel_20_60'), 4)}",
        "",
        "研究信号，不自动下单。若数据异常或开盘隔离，暂停并记录偏离。",
        f"ID: {alert['fingerprint']}",
    ]
    text = "\n".join(lines) + "\n"
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        raise ValueError(f"Telegram alert exceeds {TELEGRAM_MESSAGE_LIMIT} chars")
    return text
