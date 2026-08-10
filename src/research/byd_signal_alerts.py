"""Decision-grade signals for the formal BYD v1.3 allocation model.

The alert layer does not reproduce model logic. It consumes the final immutable
V1.3 prospective observation, which already binds the exact V1.2 core/expansion
path to the frozen low-vol recovery lifecycle. This module only detects target
changes and renders governed human-readable evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from src.research.byd_v1_3_low_vol_recovery import MODEL_ID

ASSETS = ("BYD", "515180", "CASH")
TELEGRAM_MESSAGE_LIMIT = 4096
SCHEMA_VERSION = "byd_v1_3_signal_v1"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _normalise_weights(raw: Mapping[str, Any] | None) -> dict[str, float]:
    if raw is None:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}


def _candidate_target(observation: Mapping[str, Any]) -> dict[str, float]:
    if observation.get("schema_version") != "byd_v1_3_low_vol_prospective_v1":
        raise ValueError("unsupported BYD v1.3 governed observation schema")
    if observation.get("candidate_model_id") != MODEL_ID:
        raise ValueError("BYD governed observation has the wrong model identity")
    targets = _mapping(observation.get("targets"), "observation.targets")
    raw = _mapping(targets.get(MODEL_ID), f"observation.targets.{MODEL_ID}")
    target = {
        "BYD": float(raw.get("byd_weight", 0.0)),
        "515180": float(raw.get("etf_weight", 0.0)),
        "CASH": float(raw.get("cash_weight", 0.0)),
    }
    if abs(sum(target.values()) - 1.0) > 1e-12:
        raise ValueError("BYD v1.3 governed target weights do not sum to one")
    if target["BYD"] > 1.125 + 1e-12:
        raise ValueError("BYD v1.3 governed target exceeds the formal leverage cap")
    return target


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


def _weights_changed(current: Mapping[str, float], target: Mapping[str, float]) -> bool:
    return any(abs(float(target[a]) - float(current[a])) > 1e-12 for a in ASSETS)


def _mode(
    *,
    target: Mapping[str, float],
    champion: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> str:
    if lifecycle.get("overlay_decision_active") is True:
        return "low_vol_recovery"
    if float(champion.get("financed_increment", 0.0)) > 0.0:
        return "convex_expansion"
    if float(target["BYD"]) >= 0.99:
        return "offense"
    return "defense"


def _mode_label(mode: str, target: Mapping[str, float]) -> str:
    if mode == "low_vol_recovery":
        return "低波动恢复再风险（100% BYD）"
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
    observation: Mapping[str, Any],
    previous_alert: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    signal_date = str(observation.get("signal_date") or "")
    if not signal_date:
        raise ValueError("BYD v1.3 governed observation has no signal date")
    target_weights = _candidate_target(observation)
    factors = _mapping(observation.get("factors"), "observation.factors")
    champion = _mapping(observation.get("champion"), "observation.champion")
    lifecycle = _mapping(observation.get("lifecycle"), "observation.lifecycle")
    detector = _mapping(observation.get("detector"), "observation.detector")
    confirmation = _mapping(
        observation.get("entry_confirmation"), "observation.entry_confirmation"
    )

    required_factors = {"market_state", "vol_state", "mom_20", "mom_60", "drawdown_252"}
    if not required_factors.issubset(factors):
        raise ValueError("BYD v1.3 governed factor context is incomplete")

    prior_weights: Mapping[str, Any] | None = None
    if previous_alert is not None:
        raw_prior = previous_alert.get("target_weights")
        if isinstance(raw_prior, Mapping):
            prior_weights = raw_prior
    current_weights = _normalise_weights(prior_weights or target_weights)
    changed = previous_alert is None or _weights_changed(current_weights, target_weights)

    data_freshness_ok = bool(
        observation.get("data_version")
        and observation.get("source")
        and observation.get("common_open_eligible") is not None
    )
    open_eligible = bool(observation.get("common_open_eligible", False))
    mode = _mode(target=target_weights, champion=champion, lifecycle=lifecycle)
    previous_mode = str(previous_alert.get("target_mode")) if previous_alert is not None else None
    if previous_alert is None:
        transition_type = "initialize"
        transition_label = "启用正式 BYD v1.3 信号"
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
        "data_version": str(observation.get("data_version")),
        "target_weights": target_weights,
        "recovery_lifecycle_id": int(lifecycle.get("id", 0)),
        "recovery_active": bool(lifecycle.get("overlay_decision_active", False)),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]

    alert: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "experiment_id": MODEL_ID,
        "research_only": True,
        "trade_ready": False,
        "should_alert": bool(changed and data_freshness_ok),
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
        "base_target": float(champion.get("base_byd_weight", 0.75)),
        "expansion_active": bool(champion.get("trend_expansion_active", False)),
        "momentum_scale": float(champion.get("momentum_scale", 0.0)),
        "financed_increment": float(champion.get("financed_increment", 0.0)),
        "current_weights": current_weights,
        "target_weights": target_weights,
        "orders": order_rows,
        "turnover_units": turnover_units,
        "transaction_cost_bps": 20.0,
        "estimated_transaction_cost": turnover_units * 20.0 / 10_000.0,
        "price_context": {
            "byd_open": float(_mapping(observation.get("prices"), "observation.prices").get("byd_open", 0.0)),
            "etf_open": float(_mapping(observation.get("prices"), "observation.prices").get("etf_open", 0.0)),
        },
        "factor_context": {
            "market_state": str(factors.get("market_state", "")),
            "vol_state": str(factors.get("vol_state", "")),
            "drawdown_252": float(factors.get("drawdown_252", 0.0)),
            "mom_20": float(factors.get("mom_20", 0.0)),
            "mom_60": float(factors.get("mom_60", 0.0)),
            "momentum_scale": float(champion.get("momentum_scale", 0.0)),
            "financed_increment": float(champion.get("financed_increment", 0.0)),
        },
        "recovery_context": {
            "detector_active": bool(detector.get("active", False)),
            "event_edge": bool(detector.get("event_edge", False)),
            "recovery_factor": float(detector.get("drawdown252_x_rebound60", 0.0)),
            "threshold": float(detector.get("threshold", 0.026937)),
            "required_vol_state": str(confirmation.get("required_vol_state", "low")),
            "observed_vol_state": str(confirmation.get("observed_vol_state", "")),
            "entry_confirmed": bool(confirmation.get("passed_on_edge", False)),
            "catch_up_allowed": bool(confirmation.get("catch_up_allowed", False)),
            "lifecycle_active": bool(lifecycle.get("overlay_decision_active", False)),
            "lifecycle_started": bool(lifecycle.get("started", False)),
            "lifecycle_id": int(lifecycle.get("id", 0)),
            "remaining_eligible_sessions": int(lifecycle.get("remaining_eligible_sessions", 0)),
        },
        "source_identity": {
            "data_version": str(observation.get("data_version", "")),
            "source": dict(_mapping(observation.get("source"), "observation.source")),
            "prospective_evidence_eligible": bool(observation.get("prospective_eligible", False)),
            "prelaunch_seed": bool(observation.get("prelaunch_seed", False)),
        },
    }
    alert["title"] = (
        f"[BYD v1.3 信号] {signal_date} {_mode_label(mode, target_weights)}"
        if alert["should_alert"]
        else f"[BYD v1.3 评估] {signal_date} {_mode_label(mode, target_weights)}"
    )
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
    return rows or (["- 当前仓位与目标一致"] if markdown else ["• 当前仓位与目标一致"])


def _render_markdown(alert: Mapping[str, Any]) -> str:
    factors = _mapping(alert["factor_context"], "alert.factor_context")
    recovery = _mapping(alert["recovery_context"], "alert.recovery_context")
    target = _mapping(alert["target_weights"], "alert.target_weights")
    freshness = "通过" if alert["data_freshness_ok"] else "失败：禁止发布"
    eligibility = "已确认" if alert["open_research_eligible"] else "等待下一有效开盘"
    lines = [
        f"## {alert['title']}",
        "",
        "> 正式 research baseline 信号，非自动订单。`research_only=true`，`trade_ready=false`。",
        "",
        "### 决策",
        "",
        f"- 信号时间：**{alert['signal_date']} A股收盘后**",
        "- 计划执行：**下一共同确认有效开盘**",
        f"- 决策证据：**{freshness}**",
        f"- 最近开盘资格：**{eligibility}**",
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
        "### V1.2 核心与恢复确认",
        "",
        f"- 原核心状态：**{'趋势扩张' if alert['expansion_active'] else '常规核心'}**",
        f"- 20日动量：**{_fmt_pct(factors['mom_20'])}**",
        f"- 60日动量：**{_fmt_pct(factors['mom_60'])}**",
        f"- 融资增量：**{_fmt_pct(alert['financed_increment'])}**",
        f"- 252日回撤：**{_fmt_pct(factors['drawdown_252'])}**",
        f"- 市场/波动状态：**{factors['market_state']} / {factors['vol_state']}**",
        f"- Recovery factor：**{float(recovery['recovery_factor']):.4f}** / 阈值 **{float(recovery['threshold']):.4f}**",
        f"- Recovery edge：**{'是' if recovery['event_edge'] else '否'}**；低波动确认：**{'通过' if recovery['entry_confirmed'] else '未通过'}**",
        f"- Recovery lifecycle：**{'激活' if recovery['lifecycle_active'] else '未激活'}**",
        "",
        "### 执行纪律",
        "",
        "- 只按下一共同确认有效开盘执行；无效开盘保留待执行目标。",
        "- 高波动 recovery edge 不允许在之后波动回落时补入；必须等待新的 edge。",
        "- 实际成交价格、滑点和融资成本可能与回测假设不同。",
        "",
        f"<!-- signal-fingerprint:{alert['fingerprint']} -->",
    ]
    return "\n".join(lines) + "\n"


def _render_telegram(alert: Mapping[str, Any]) -> str:
    target = _mapping(alert["target_weights"], "alert.target_weights")
    recovery = _mapping(alert["recovery_context"], "alert.recovery_context")
    lines = [
        f"🔔 Alpha Engine BYD v1.3｜{alert['transition_label']}",
        "",
        f"信号：{alert['signal_date']} 收盘",
        "执行：下一共同确认有效开盘",
        f"状态：{alert['target_mode_label']}",
        f"目标：BYD {float(target['BYD']):.2%}｜515180 {float(target['515180']):.2%}｜现金 {float(target['CASH']):.2%}",
        f"Recovery：edge {'是' if recovery['event_edge'] else '否'}｜低波动确认 {'通过' if recovery['entry_confirmed'] else '未通过'}",
        "",
        *_order_lines(alert, markdown=False),
        "",
        "正式研究信号，不是自动订单。",
    ]
    return "\n".join(lines)[:TELEGRAM_MESSAGE_LIMIT]
