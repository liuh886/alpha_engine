"""Research-only signal cards for formal QQQ Rotation v4.3."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping

ASSETS = ("QQQI", "QQQ", "TQQQ", "SGOV")
COST_BPS_PER_TURNOVER_UNIT = 10.0
MACHINE_MARKER = "qqq-v4-3-signal"


def _weights(value: Mapping[str, Any]) -> dict[str, float]:
    output = {asset: float(value.get(asset, 0.0)) for asset in ASSETS}
    if any(weight < 0.0 for weight in output.values()):
        raise ValueError("v4.3 weights cannot be negative")
    if abs(sum(output.values()) - 1.0) > 1e-9:
        raise ValueError("v4.3 weights must sum to one")
    return output


def _orders(current: Mapping[str, float], target: Mapping[str, float]) -> list[dict[str, Any]]:
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


def _weight_text(weights: Mapping[str, float]) -> str:
    active = [f"{asset} {weight:.0%}" for asset, weight in weights.items() if weight > 1e-12]
    return " / ".join(active) if active else "空仓"


def _machine_record(alert: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "model_id": "qqqi_qqq_tqqq_v4_3",
        "research_only": True,
        "trade_ready": False,
        "signal_date": alert["signal_date"],
        "latest_data_date": alert["latest_data_date"],
        "data_freshness_ok": alert["data_freshness_ok"],
        "execution_time": alert["execution_time"],
        "fingerprint": alert["fingerprint"],
        "current_formal_state": alert["current_formal_state"],
        "target_formal_state": alert["target_formal_state"],
        "current_overlay": alert["current_overlay"],
        "target_overlay": alert["target_overlay"],
        "current_weights": alert["current_weights"],
        "target_weights": alert["target_weights"],
        "orders": alert["orders"],
        "turnover_units": alert["turnover_units"],
        "estimated_transaction_cost": alert["estimated_transaction_cost"],
        "panic_repair_active": alert["panic_repair_active"],
        "strong_defense": alert["strong_defense"],
        "ma200_falling": alert["ma200_falling"],
        "fast_price_vol_repair": alert["fast_price_vol_repair"],
        "rsi_14": alert["rsi_14"],
        "fear_greed_score": alert["fear_greed_score"],
        "context": alert["context"],
        "data_context": alert["data_context"],
    }


def _machine_marker(alert: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _machine_record(alert), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"<!-- {MACHINE_MARKER}:{encoded} -->"


def build_v4_3_signal_alert(summary: Mapping[str, Any]) -> dict[str, Any]:
    current = summary.get("current_open_target")
    target = summary.get("next_open_target")
    if not isinstance(current, Mapping) or not isinstance(target, Mapping):
        raise ValueError("v4.3 monitor summary is incomplete")
    current_weights = _weights(current["target_weights"])
    target_weights = _weights(target["target_weights"])
    orders = _orders(current_weights, target_weights)
    signal_date = str(target["signal_date"])
    latest_data_date = str(summary.get("latest_data_date") or signal_date)
    freshness_ok = signal_date == latest_data_date
    should_alert = bool(orders) and freshness_ok
    turnover = float(sum(row["weight_change"] for row in orders))
    estimated_cost = turnover * COST_BPS_PER_TURNOVER_UNIT / 10_000.0
    fingerprint_payload = {
        "model_id": "qqqi_qqq_tqqq_v4_3",
        "signal_date": signal_date,
        "target_weights": target_weights,
        "formal_state": int(target["formal_state"]),
        "overlay": str(target["overlay"]),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    alert = {
        "schema_version": "1.0.0",
        "model_id": "qqqi_qqq_tqqq_v4_3",
        "display_name": "QQQ Rotation v4.3",
        "research_only": True,
        "trade_ready": False,
        "signal_date": signal_date,
        "latest_data_date": latest_data_date,
        "data_freshness_ok": freshness_ok,
        "should_alert": should_alert,
        "fingerprint": fingerprint,
        "execution_time": "next_session_open",
        "current_formal_state": int(current["formal_state"]),
        "target_formal_state": int(target["formal_state"]),
        "current_overlay": str(current["overlay"]),
        "target_overlay": str(target["overlay"]),
        "current_weights": current_weights,
        "target_weights": target_weights,
        "orders": orders,
        "turnover_units": turnover,
        "estimated_transaction_cost": estimated_cost,
        "transaction_cost_bps_per_turnover_unit": COST_BPS_PER_TURNOVER_UNIT,
        "panic_repair_active": bool(target["panic_repair_active"]),
        "strong_defense": bool(target["strong_defense"]),
        "ma200_falling": bool(target["ma200_falling"]),
        "fast_price_vol_repair": bool(target["fast_price_vol_repair"]),
        "rsi_14": float(target["rsi_14"]),
        "fear_greed_score": target.get("fear_greed_score"),
        "context": dict(target.get("context", {})),
        "data_context": dict(summary.get("data_identity", {})),
    }
    context = alert["context"]
    qqq_close = float(context["qqq_close"])
    ma20 = float(context["ma20"])
    ma50 = float(context["ma50"])
    ma200 = float(context["ma200"])
    alert["current_state"] = alert["current_formal_state"]
    alert["target_state"] = alert["target_formal_state"]
    alert["transition_type"] = "risk_budget_change" if orders else "hold"
    alert["decision_reason_label"] = (
        f"{alert['current_overlay']} → {alert['target_overlay']}"
    )
    alert["price_context"] = {
        "qqq_close": qqq_close,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "qqq_vs_ma20": qqq_close / ma20 - 1.0,
        "qqq_vs_ma50": qqq_close / ma50 - 1.0,
        "qqq_vs_ma200": qqq_close / ma200 - 1.0,
        "stress_price_failure": bool(context.get("stress_price_failure", False)),
        "long_break": qqq_close < ma200,
    }
    alert["data_context"] = {
        **dict(alert["data_context"]),
        "latest_data_date": latest_data_date,
    }
    alert["title"] = f"[策略信号] QQQ v4.3 {signal_date} {_weight_text(target_weights)}"
    alert["markdown"] = render_markdown(alert)
    alert["telegram_text"] = render_telegram(alert)
    return alert


def _order_lines(alert: Mapping[str, Any], prefix: str) -> list[str]:
    labels = {"buy": "买入", "sell": "卖出"}
    if not alert["orders"]:
        return [f"{prefix}当前权重已与下一开盘目标一致"]
    return [
        f"{prefix}{labels[row['side']]} {row['weight_change']:.0%} {row['asset']} "
        f"({row['from_weight']:.0%} → {row['to_weight']:.0%})"
        for row in alert["orders"]
    ]


def render_markdown(alert: Mapping[str, Any]) -> str:
    context = alert["context"]
    lines = [
        f"## {alert['title']}",
        "",
        "> 研究用途；不是自动订单。v4.3 保持 `trade_ready=false`。",
        "",
        f"- 信号日期：**{alert['signal_date']}**",
        "- 执行口径：**下一美股交易日开盘**",
        f"- 当前目标：**{_weight_text(alert['current_weights'])}**",
        f"- 下一开盘目标：**{_weight_text(alert['target_weights'])}**",
        f"- Formal state：**{alert['current_formal_state']} → {alert['target_formal_state']}**",
        f"- 风险层：**{alert['current_overlay']} → {alert['target_overlay']}**",
        f"- Panic Repair：**{alert['panic_repair_active']}**",
        f"- Slow-bear strong defense：**{alert['strong_defense']}**",
        f"- MA200 falling：**{alert['ma200_falling']}**",
        f"- MA20+VIX repair release：**{alert['fast_price_vol_repair']}**",
        f"- RSI(14)：**{alert['rsi_14']:.2f}**",
        f"- Fear & Greed：**{alert['fear_greed_score'] if alert['fear_greed_score'] is not None else '不可用'}**",
        f"- QQQ / MA20 / MA200：**{context.get('qqq_close')} / {context.get('ma20')} / {context.get('ma200')}**",
        f"- VIX / VXN：**{context.get('vix_close')} / {context.get('vxn_close')}**",
        "",
        "### 调整",
        "",
        *_order_lines(alert, "- "),
        f"- 换手单位：**{alert['turnover_units']:.2f}**",
        f"- 模型交易成本：**{alert['estimated_transaction_cost']:.2%}**",
        "",
        _machine_marker(alert),
        f"<!-- signal-fingerprint:{alert['fingerprint']} -->",
        "",
    ]
    return "\n".join(lines)


def render_telegram(alert: Mapping[str, Any]) -> str:
    lines = [
        f"QQQ Rotation v4.3｜{alert['signal_date']}",
        f"当前：{_weight_text(alert['current_weights'])}",
        f"下一开盘：{_weight_text(alert['target_weights'])}",
        f"风险层：{alert['target_overlay']}",
        f"State：{alert['target_formal_state']}｜Panic={alert['panic_repair_active']}｜强防守={alert['strong_defense']}",
        f"RSI14={alert['rsi_14']:.2f}｜Fear&Greed={alert['fear_greed_score'] if alert['fear_greed_score'] is not None else 'NA'}",
        *_order_lines(alert, "• "),
        "研究信号，不是自动订单。",
    ]
    return "\n".join(lines)
