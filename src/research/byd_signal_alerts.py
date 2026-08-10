"""Decision-grade signals for the formal BYD v1.2 convex-momentum model.

The alert layer consumes the frozen base, paired and trend-state observations.
It does not refit or search. The exact continuous target weight is reproduced
from the formal model contract and evaluated for next eligible open execution.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE,
    CONVEX_POWER,
    FULL_INCREMENT_MOMENTUM,
    MAX_FINANCED_INCREMENT,
)

ASSETS = ("BYD", "515180", "CASH")
TELEGRAM_MESSAGE_LIMIT = 4096
MODEL_ID = CANDIDATE


def _normalise_weights(raw: Mapping[str, Any] | None) -> dict[str, float]:
    if raw is None:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}


def _momentum_scale(momentum_20: float) -> float:
    normalized = max(float(momentum_20), 0.0) / FULL_INCREMENT_MOMENTUM
    return min(normalized, 1.0) ** CONVEX_POWER


def _target_weights(
    *,
    base_target: float,
    expansion_active: bool,
    momentum_20: float,
) -> tuple[dict[str, float], float, float]:
    scale = _momentum_scale(momentum_20)
    increment = MAX_FINANCED_INCREMENT * scale if expansion_active else 0.0
    byd_weight = float(base_target) + increment
    etf_weight = 0.0 if increment > 0.0 else 1.0 - float(base_target)
    cash_weight = 1.0 - byd_weight - etf_weight
    weights = {
        "BYD": byd_weight,
        "515180": etf_weight,
        "CASH": cash_weight,
    }
    if abs(sum(weights.values()) - 1.0) > 1e-12:
        raise ValueError("BYD v1.2 target weights do not sum to one")
    if byd_weight > 1.125 + 1e-12:
        raise ValueError("BYD v1.2 target exceeds the formal leverage cap")
    return weights, scale, increment


def _orders(
    current: Mapping[str, float],
    target: Mapping[str, float],
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


def _weights_changed(
    current: Mapping[str, float],
    target: Mapping[str, float],
) -> bool:
    return any(abs(float(target[a]) - float(current[a])) > 1e-12 for a in ASSETS)


def _mode(base_target: float, increment: float) -> str:
    if increment > 0.0:
        return "convex_expansion"
    if base_target >= 0.99:
        return "offense"
    return "defense"


def _mode_label(mode: str, target: Mapping[str, float]) -> str:
    if mode == "convex_expansion":
        return f"凸动量扩张（BYD {float(target['BYD']):.1%}）"
    if mode == "offense":
        return "进攻（100% BYD）"
    return "防守（75% BYD / 25% 515180）"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.{digits}%}"


def build_byd_signal_alert(
    shadow_obs: Mapping[str, Any],
    paired_obs: Mapping[str, Any],
    expansion_obs: Mapping[str, Any],
    previous_alert: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    signal_dates = {
        str(shadow_obs.get("signal_date", "")),
        str(paired_obs.get("signal_date", "")),
        str(expansion_obs.get("signal_date", "")),
    }
    if len(signal_dates) != 1 or "" in signal_dates:
        raise ValueError("BYD signal source dates do not agree")
    signal_date = next(iter(signal_dates))

    factors = expansion_obs.get("factors", {})
    if not isinstance(factors, Mapping):
        raise ValueError("BYD expansion factors are missing")
    base_target = float(shadow_obs.get("base_target_position", 0.75))
    expansion_active = bool(expansion_obs.get("trend_expansion_active", False))
    momentum_20 = float(factors.get("mom_20", 0.0))
    target_weights, scale, increment = _target_weights(
        base_target=base_target,
        expansion_active=expansion_active,
        momentum_20=momentum_20,
    )

    prior_weights = None
    if previous_alert is not None:
        raw_prior = previous_alert.get("target_weights")
        if isinstance(raw_prior, Mapping):
            prior_weights = raw_prior
    current_weights = _normalise_weights(prior_weights or target_weights)
    changed = previous_alert is None or _weights_changed(current_weights, target_weights)

    data_freshness_ok = bool(
        shadow_obs.get("prospective_eligible", False)
        and paired_obs.get("prospective_eligible", False)
        and expansion_obs.get("prospective_eligible", False)
    )
    open_eligible = bool(
        shadow_obs.get("open_research_eligible", False)
        and paired_obs.get("common_open_eligible", False)
        and expansion_obs.get("common_open_eligible", False)
    )
    should_alert = bool(changed and data_freshness_ok and open_eligible)

    mode = _mode(base_target, increment)
    previous_mode = str(previous_alert.get("target_mode")) if previous_alert is not None else None
    if previous_alert is None:
        transition_type = "initialize"
        transition_label = "启用正式 BYD v1.2 信号"
    elif changed:
        transition_type = "rebalance"
        transition_label = "调整目标仓位"
    else:
        transition_type = "no_change"
        transition_label = "目标仓位不变"

    order_rows = _orders(current_weights, target_weights)
    turnover_units = float(sum(row["weight_change"] for row in order_rows))
    fingerprint_payload = {
        "model_id": MODEL_ID,
        "signal_date": signal_date,
        "target_weights": target_weights,
        "momentum_scale": scale,
        "financed_increment": increment,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]

    chain = shadow_obs.get("chain_linked_adjusted_ohlcv", {})
    primary = shadow_obs.get("primary_raw_ohlcv", {})
    if not isinstance(chain, Mapping):
        chain = {}
    if not isinstance(primary, Mapping):
        primary = {}

    alert: dict[str, Any] = {
        "schema_version": "byd_v1_2_signal_v2",
        "model_id": MODEL_ID,
        "experiment_id": MODEL_ID,
        "research_only": True,
        "trade_ready": False,
        "should_alert": should_alert,
        "fingerprint": fingerprint,
        "signal_date": signal_date,
        "latest_data_date": signal_date,
        "data_freshness_ok": data_freshness_ok,
        "open_research_eligible": open_eligible,
        "execution_time": "next_common_independently_confirmed_eligible_open_t_plus_1",
        "transition_type": transition_type,
        "transition_label": transition_label,
        "previous_mode": previous_mode,
        "target_mode": mode,
        "target_mode_label": _mode_label(mode, target_weights),
        "base_target": base_target,
        "expansion_active": expansion_active,
        "momentum_scale": scale,
        "financed_increment": increment,
        "current_weights": current_weights,
        "target_weights": target_weights,
        "orders": order_rows,
        "turnover_units": turnover_units,
        "transaction_cost_bps": 20.0,
        "estimated_transaction_cost": turnover_units * 20.0 / 10_000.0,
        "price_context": {
            "byd_close": float(chain.get("close", primary.get("close", 0.0))),
            "byd_open": float(chain.get("open", primary.get("open", 0.0))),
        },
        "factor_context": {
            "market_state": str(factors.get("market_state", "")),
            "vol_state": str(factors.get("vol_state", "")),
            "drawdown_252": float(factors.get("drawdown_252", 0.0)),
            "mom_20": momentum_20,
            "mom_60": float(factors.get("mom_60", 0.0)),
            "momentum_scale": scale,
            "financed_increment": increment,
        },
        "source_identity": {
            "shadow_data_version": str(shadow_obs.get("data_version", "")),
            "paired_data_version": str(paired_obs.get("data_version", "")),
            "expansion_data_version": str(expansion_obs.get("data_version", "")),
        },
    }
    if should_alert:
        alert["title"] = f"[BYD v1.2 信号] {signal_date} {_mode_label(mode, target_weights)}"
    else:
        alert["title"] = f"[BYD v1.2 评估] {signal_date} {_mode_label(mode, target_weights)}"
    alert["markdown"] = _render_markdown(alert)
    alert["telegram_text"] = _render_telegram(alert)
    return alert


def _order_lines(alert: Mapping[str, Any], *, markdown: bool) -> list[str]:
    labels = {"buy": "买入", "sell": "卖出"}
    rows: list[str] = []
    for item in alert.get("orders", []):
        asset = str(item["asset"])
        action = (
            "融资"
            if asset == "CASH" and item["side"] == "sell"
            else "还款"
            if asset == "CASH"
            else labels[str(item["side"])]
        )
        text = (
            f"{action} {float(item['weight_change']):.2%} {asset} "
            f"({float(item['from_weight']):.2%} → {float(item['to_weight']):.2%})"
        )
        rows.append(f"- **{text}**" if markdown else f"• {text}")
    if rows:
        return rows
    return ["- 当前仓位与目标一致"] if markdown else ["• 当前仓位与目标一致"]


def _render_markdown(alert: Mapping[str, Any]) -> str:
    factors = alert["factor_context"]
    target = alert["target_weights"]
    freshness = "通过" if alert["data_freshness_ok"] else "失败：禁止执行"
    eligibility = "通过" if alert["open_research_eligible"] else "隔离"
    lines = [
        f"## {alert['title']}",
        "",
        "> 研究信号，非自动订单。`research_only=true`，`trade_ready=false`。",
        "",
        "### 决策",
        "",
        f"- 信号时间：**{alert['signal_date']} A股收盘后**",
        "- 计划执行：**下一共同确认有效开盘**",
        f"- 数据新鲜度：**{freshness}**",
        f"- 开盘资格：**{eligibility}**",
        f"- 状态：**{alert['target_mode_label']}**",
        f"- BYD：**{float(target['BYD']):.2%}**",
        f"- 515180：**{float(target['515180']):.2%}**",
        f"- 现金/融资：**{float(target['CASH']):.2%}**",
        "",
        "### 调仓",
        "",
        *_order_lines(alert, markdown=True),
        f"- 组合换手：**{float(alert['turnover_units']):.4f}**",
        f"- 估算交易成本：**{_fmt_pct(alert['estimated_transaction_cost'], 4)}**",
        "",
        "### 凸动量预算",
        "",
        f"- 冻结趋势状态：**{'激活' if alert['expansion_active'] else '未激活'}**",
        f"- 20日动量：**{_fmt_pct(factors['mom_20'])}**",
        f"- 60日动量：**{_fmt_pct(factors['mom_60'])}**",
        f"- 动量缩放：**{_fmt_pct(alert['momentum_scale'])}**",
        f"- 融资增量：**{_fmt_pct(alert['financed_increment'])}**",
        f"- 252日回撤：**{_fmt_pct(factors['drawdown_252'])}**",
        f"- 市场/波动状态：**{factors['market_state']} / {factors['vol_state']}**",
        "",
        "### 执行纪律",
        "",
        "- 只按下一共同确认有效开盘执行；无效开盘保留待执行目标。",
        "- 目标仓位是连续值，不得人工四舍五入为固定 110% 档位。",
        "- 实际成交价格、滑点和融资成本可能与回测假设不同。",
        "",
        f"<!-- signal-fingerprint:{alert['fingerprint']} -->",
    ]
    return "\n".join(lines) + "\n"


def _render_telegram(alert: Mapping[str, Any]) -> str:
    target = alert["target_weights"]
    factors = alert["factor_context"]
    lines = [
        f"🔔 Alpha Engine BYD v1.2｜{alert['transition_label']}",
        "",
        f"信号：{alert['signal_date']} 收盘",
        "执行：下一共同确认有效开盘",
        f"状态：{alert['target_mode_label']}",
        f"目标：BYD {float(target['BYD']):.2%}｜515180 {float(target['515180']):.2%}｜现金 {float(target['CASH']):.2%}",
        f"动量：20日 {float(factors['mom_20']):.2%}｜缩放 {float(alert['momentum_scale']):.2%}",
        f"融资增量：{float(alert['financed_increment']):.2%}",
        "",
        *_order_lines(alert, markdown=False),
        "",
        "研究信号，不是自动订单。",
    ]
    return "\n".join(lines)[:TELEGRAM_MESSAGE_LIMIT]
