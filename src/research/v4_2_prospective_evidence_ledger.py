"""Durable prospective evidence ledger for the frozen v4.2 strategy family.

The ledger never creates or changes a trading signal. It persists the signal-time
facts that were already produced by the frozen v4.2 monitor and appends outcome
observations only after the declared trading-session horizons exist.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

EVENT_MARKER_PREFIX = "prospective-evidence-record"
UPDATE_MARKER_PREFIX = "prospective-evidence-update"
MONTH_MARKER_PREFIX = "prospective-evidence-month"
ASSETS = ("QQQI", "QQQ", "TQQQ")


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _normalise_weights(raw: Mapping[str, Any] | None) -> dict[str, float]:
    if raw is None:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: float(raw.get(asset, 0.0)) for asset in ASSETS}


def _record_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def encode_marker(prefix: str, payload: Mapping[str, Any]) -> str:
    """Encode one machine record inside a safe HTML comment."""

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"<!-- {prefix}:{encoded} -->"


def decode_marker_payload(encoded: str) -> dict[str, Any]:
    """Decode the base64-url payload stored in a ledger marker."""

    padding = "=" * (-len(encoded) % 4)
    value = json.loads(base64.urlsafe_b64decode(encoded + padding))
    if not isinstance(value, dict):
        raise ValueError("ledger marker payload must be an object")
    return value


def _snapshot_parts(
    prospective_summary: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    snapshot = prospective_summary.get("bridge_latest_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("bridge_latest_snapshot is missing")
    executed = snapshot.get("latest_executed_position")
    signal = snapshot.get("latest_close_signal")
    if not isinstance(executed, Mapping) or not isinstance(signal, Mapping):
        raise ValueError("latest executed position or close signal is missing")
    return executed, signal


def recovery_precursor_boolean(prospective_summary: Mapping[str, Any]) -> bool:
    """Evaluate the already-frozen close-time precursor from monitor fields."""

    executed, signal = _snapshot_parts(prospective_summary)
    price = signal.get("price_context", {})
    volatility = signal.get("volatility_context", {})
    if not isinstance(price, Mapping) or not isinstance(volatility, Mapping):
        raise ValueError("signal context is missing")
    return bool(
        int(executed["position_state"]) == 1
        and int(signal["decision_state"]) == 1
        and bool(price.get("shock_memory", False))
        and bool(price.get("medium_repair", False))
        and bool(volatility.get("vix_normalized", False))
        and not bool(volatility.get("vxn_stress", False))
    )


def _decision_state_age(summary: Mapping[str, Any]) -> int | None:
    _, signal = _snapshot_parts(summary)
    value = signal.get("decision_state_age_sessions")
    if value is not None:
        return int(value)
    executed, _ = _snapshot_parts(summary)
    if int(executed.get("position_state", -1)) == int(signal["decision_state"]):
        age = executed.get("state_age_sessions")
        return int(age) if age is not None else None
    return 1


def _signal_features(summary: Mapping[str, Any]) -> dict[str, Any]:
    _, signal = _snapshot_parts(summary)
    price = signal.get("price_context", {})
    volatility = signal.get("volatility_context", {})
    return {
        "vix_return_5d": _optional_float(volatility.get("vix_return_5d")),
        "vxn_return_5d": _optional_float(volatility.get("vxn_return_5d")),
        "vxn_close": _optional_float(volatility.get("vxn_close")),
        "state_1_decision_age_sessions": _decision_state_age(summary),
        "vxn_return_1d": _optional_float(volatility.get("vxn_return_1d")),
        "qqq_distance_ma_short": _optional_float(price.get("qqq_vs_ma20")),
        "vix_close": _optional_float(volatility.get("vix_close")),
        "vxn_retreat_from_peak": _optional_float(volatility.get("vxn_retreat_from_peak")),
        "qqq_close": _optional_float(price.get("qqq_close")),
        "shock_memory": bool(price.get("shock_memory", False)),
        "medium_repair": bool(price.get("medium_repair", False)),
        "vix_normalized": bool(volatility.get("vix_normalized", False)),
        "vxn_stress": bool(volatility.get("vxn_stress", False)),
    }


def _active_precursor_exists(existing_events: Sequence[Mapping[str, Any]]) -> bool:
    for item in existing_events:
        record = item.get("record", item)
        if not isinstance(record, Mapping):
            continue
        status = str(item.get("latest_status") or record.get("status") or "")
        if record.get("event_type") == "recovery_precursor" and status == "active_precursor":
            return True
    return False


def _common_record(
    summary: Mapping[str, Any],
    alert: Mapping[str, Any],
    event_type: str,
) -> dict[str, Any]:
    executed, signal = _snapshot_parts(summary)
    signal_date = str(signal["signal_date"])
    latest_data_date = str(summary.get("latest_data_date") or signal_date)
    current_state = int(executed["position_state"])
    target_state = int(signal["decision_state"])
    current_weights = _normalise_weights(executed.get("weights"))
    target_weights = _normalise_weights(alert.get("target_weights"))
    identity = summary.get("data_identity", {})
    if not isinstance(identity, Mapping):
        identity = {}
    identity_payload = {
        "experiment_id": str(alert.get("experiment_id")),
        "event_type": event_type,
        "signal_date": signal_date,
        "current_state": current_state,
        "target_state": target_state,
        "fingerprint": str(alert.get("fingerprint", "")),
    }
    status = "active_precursor" if event_type == "recovery_precursor" else "awaiting_next_open"
    return {
        "schema_version": "1.0",
        "event_id": _record_id(identity_payload),
        "experiment_id": str(alert.get("experiment_id")),
        "ledger_experiment_id": "qqqi_qqq_tqqq_v4_2_prospective_evidence_ledger_v1",
        "event_type": event_type,
        "research_only": True,
        "trade_ready": False,
        "actionable": event_type == "state_change",
        "status": status,
        "signal_date": signal_date,
        "latest_data_date_at_creation": latest_data_date,
        "data_freshness_ok": bool(alert.get("data_freshness_ok", False)),
        "execution_time": "next_session_open",
        "fingerprint": str(alert.get("fingerprint", "")),
        "transition_type": str(alert.get("transition_type", "")),
        "decision_reason": str(signal.get("decision_reason", "")),
        "current_state": current_state,
        "target_state": target_state,
        "current_weights": current_weights,
        "target_weights": target_weights,
        "turnover_units": float(alert.get("turnover_units", 0.0)),
        "estimated_transaction_cost": float(alert.get("estimated_transaction_cost", 0.0)),
        "signal_close_features": _signal_features(summary),
        "recovery_precursor_boolean": recovery_precursor_boolean(summary),
        "data_identity": {
            "mode": identity.get("mode"),
            "bundle_id": identity.get("bundle_id"),
            "selected_providers": identity.get("selected_providers"),
        },
        "delivery": {
            "github_issue": "pending",
            "telegram": (
                "not_authorized_for_shadow_event"
                if event_type == "recovery_precursor"
                else "managed_by_signal_alert_workflow"
            ),
        },
        "outcome_horizons_sessions": [1, 2, 3, 5, 10, 20, 40],
    }


def build_candidate_event_records(
    prospective_summary: Mapping[str, Any],
    alert: Mapping[str, Any],
    existing_events: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build only genuinely new state-change or precursor episode records."""

    candidates: list[dict[str, Any]] = []
    if bool(alert.get("should_alert", False)):
        candidates.append(_common_record(prospective_summary, alert, "state_change"))

    if recovery_precursor_boolean(prospective_summary) and not _active_precursor_exists(
        existing_events
    ):
        precursor = _common_record(
            prospective_summary,
            alert,
            "recovery_precursor",
        )
        precursor["actionable"] = False
        precursor["transition_type"] = "recovery_precursor_shadow"
        precursor["target_weights"] = _normalise_weights({"QQQI": 0.25, "QQQ": 0.50, "TQQQ": 0.25})
        precursor["shadow_allocations"] = {
            "tqqq_25": {"QQQI": 0.25, "QQQ": 0.50, "TQQQ": 0.25},
            "tqqq_50": {"QQQI": 0.00, "QQQ": 0.50, "TQQQ": 0.50},
        }
        candidates.append(precursor)

    existing_ids = {
        str(item.get("record", item).get("event_id"))
        for item in existing_events
        if isinstance(item.get("record", item), Mapping)
    }
    return [item for item in candidates if item["event_id"] not in existing_ids]


def validate_event_record(record: Mapping[str, Any]) -> None:
    """Validate immutable signal-time fields before persistence."""

    required = {
        "schema_version",
        "event_id",
        "event_type",
        "research_only",
        "trade_ready",
        "signal_date",
        "latest_data_date_at_creation",
        "data_freshness_ok",
        "current_state",
        "target_state",
        "current_weights",
        "target_weights",
        "signal_close_features",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"event record missing fields: {missing}")
    if record["event_type"] not in {"state_change", "recovery_precursor"}:
        raise ValueError("unsupported event_type")
    if record["research_only"] is not True or record["trade_ready"] is not False:
        raise ValueError("ledger records must remain research-only and not trade-ready")
    if pd.Timestamp(record["signal_date"]) > pd.Timestamp(record["latest_data_date_at_creation"]):
        raise ValueError("signal date cannot be after latest data date")
    if not bool(record["data_freshness_ok"]):
        raise ValueError("new event requires fresh governed data")
    for label in ("current_weights", "target_weights"):
        weights = _normalise_weights(record[label])
        total = sum(weights.values())
        expected = 1.0 if label == "target_weights" or sum(weights.values()) > 0 else 0.0
        if abs(total - expected) > 1e-9:
            raise ValueError(f"{label} must sum to {expected:.0f}")


def _daily_frame(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
        frame = frame.set_index("date")
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame.sort_index()


def _cumulative_return(values: pd.Series, horizon: int) -> float | None:
    sample = values.iloc[:horizon].dropna().astype(float)
    if len(sample) != horizon:
        return None
    return float((1.0 + sample).prod() - 1.0)


def _sign_reversals(values: pd.Series) -> int:
    signs = np.sign(values.dropna().astype(float).to_numpy())
    signs = signs[signs != 0]
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


def _path_metrics(future: pd.DataFrame, horizon: int) -> dict[str, Any]:
    qqq = future["QQQ_next_open_return"].iloc[:horizon].dropna().astype(float)
    tqqq = future["TQQQ_next_open_return"].iloc[:horizon].dropna().astype(float)
    if len(qqq) != horizon or len(tqqq) != horizon:
        return {}
    qqq_return = float((1.0 + qqq).prod() - 1.0)
    tqqq_return = float((1.0 + tqqq).prod() - 1.0)
    daily_three_x = float((1.0 + 3.0 * qqq).prod() - 1.0)
    qqq_path = (1.0 + qqq).cumprod() - 1.0
    result: dict[str, Any] = {
        "qqq_return": qqq_return,
        "tqqq_return": tqqq_return,
        "raw_50_vs_25_component": 0.25 * (tqqq_return - qqq_return),
        "directional_leverage_component": 0.25 * (daily_three_x - qqq_return),
        "tracking_compounding_component": 0.25 * (tqqq_return - daily_three_x),
    }
    if horizon == 5:
        result.update(
            {
                "qqq_mfe": float(qqq_path.max()),
                "qqq_mae": float(qqq_path.min()),
                "qqq_realized_volatility_annualized": float(qqq.std(ddof=0) * np.sqrt(252.0)),
                "qqq_sign_reversals": _sign_reversals(qqq),
            }
        )
        if {"QQQ_open", "QQQ_close"}.issubset(future.columns):
            sample = future.iloc[:horizon]
            intraday = sample["QQQ_close"].astype(float) / sample["QQQ_open"].astype(float) - 1.0
            overnight = (1.0 + qqq.to_numpy()) / (1.0 + intraday.to_numpy()) - 1.0
            result["qqq_intraday_log_return"] = float(np.log1p(intraday).sum())
            result["qqq_overnight_log_return"] = float(np.log1p(overnight).sum())
    return result


def _first_transition(future: pd.DataFrame, state: int) -> int | None:
    if "position_state" not in future.columns:
        return None
    matches = np.flatnonzero(future["position_state"].astype(int).eq(state).to_numpy())
    return int(matches[0] + 1) if len(matches) else None


def compute_event_observation(
    record: Mapping[str, Any],
    daily: pd.DataFrame,
    *,
    current_precursor_boolean: bool,
    latest_data_date: str,
    posted_horizons: Sequence[int] = (),
    latest_status: str | None = None,
) -> dict[str, Any]:
    """Append deterministic next-open outcomes without mutating the event record."""

    validate_event_record(record)
    frame = _daily_frame(daily)
    signal_date = pd.Timestamp(record["signal_date"]).tz_localize(None)
    future = frame.loc[frame.index > signal_date].copy()
    required_returns = {"QQQ_next_open_return", "TQQQ_next_open_return"}
    if not required_returns.issubset(future.columns):
        future = future.iloc[0:0]
    else:
        future = future.loc[
            future["QQQ_next_open_return"].notna() & future["TQQQ_next_open_return"].notna()
        ]

    horizons = [int(value) for value in record["outcome_horizons_sessions"]]
    completed = [horizon for horizon in horizons if len(future) >= horizon]
    posted = {int(value) for value in posted_horizons}
    new_horizons = [value for value in completed if value not in posted]
    outcomes = {str(horizon): _path_metrics(future, horizon) for horizon in completed}

    execution: dict[str, Any] | None = None
    if not future.empty:
        first = future.iloc[0]
        execution = {
            "execution_date": future.index[0].date().isoformat(),
            "theoretical_next_open_prices": {
                asset: _optional_float(first.get(f"{asset}_open")) for asset in ASSETS
            },
        }
        qqq_signal_close = _optional_float(record.get("signal_close_features", {}).get("qqq_close"))
        qqq_open = execution["theoretical_next_open_prices"]["QQQ"]
        execution["qqq_opening_gap"] = (
            qqq_open / qqq_signal_close - 1.0
            if qqq_open is not None
            and qqq_signal_close is not None
            and abs(qqq_signal_close) > 1e-12
            else None
        )

    status = "awaiting_next_open"
    if future.shape[0] > 0:
        status = "observing_outcomes"
    if record["event_type"] == "recovery_precursor":
        status = "active_precursor" if current_precursor_boolean else status
    if 40 in completed:
        status = "mature_40_sessions"
    status_changed = latest_status is not None and status != latest_status

    observation = {
        "schema_version": "1.0",
        "event_id": str(record["event_id"]),
        "as_of_data_date": str(latest_data_date),
        "status": status,
        "previous_status": latest_status,
        "status_changed": status_changed,
        "available_sessions": int(len(future)),
        "completed_horizons": completed,
        "new_horizons": new_horizons,
        "execution": execution,
        "outcomes": outcomes,
        "time_to_formal_state_2_sessions": _first_transition(future, 2),
        "time_to_state_0_sessions": _first_transition(future, 0),
    }
    observation["has_material_update"] = bool(
        new_horizons
        or status_changed
        or (execution is not None and 1 not in posted and not completed)
    )
    return observation


def render_event_issue_body(
    record: Mapping[str, Any],
    *,
    alert_markdown: str | None = None,
) -> str:
    """Render the durable human-readable record and its machine marker."""

    validate_event_record(record)
    feature = record["signal_close_features"]
    title = (
        "v4.2 状态变化前瞻证据"
        if record["event_type"] == "state_change"
        else "v4.2 恢复前置信号研究台账"
    )
    lines = [f"## {title}", ""]
    if alert_markdown and record["event_type"] == "state_change":
        lines.extend([alert_markdown.rstrip(), "", "---", ""])
    lines.extend(
        [
            "> 这是研究证据记录，不是自动订单，也不授权修改 v4.2。",
            "",
            f"- 事件ID：`{record['event_id']}`",
            f"- 类型：`{record['event_type']}`",
            f"- 信号收盘日：**{record['signal_date']}**",
            "- 理论执行：**下一美股交易日开盘**",
            f"- 当前状态 → 收盘决策状态：**{record['current_state']} → {record['target_state']}**",
            f"- 数据新鲜度：**{'通过' if record['data_freshness_ok'] else '失败'}**",
            f"- 恢复前置信号：**{bool(record['recovery_precursor_boolean'])}**",
            "",
            "### 信号时可见特征",
            "",
            f"- VIX 5日变化：`{feature.get('vix_return_5d')}`",
            f"- VXN 5日变化：`{feature.get('vxn_return_5d')}`",
            f"- VXN水平：`{feature.get('vxn_close')}`",
            f"- state 1决策年龄：`{feature.get('state_1_decision_age_sessions')}`",
            f"- VXN单日变化：`{feature.get('vxn_return_1d')}`",
            f"- QQQ相对MA20：`{feature.get('qqq_distance_ma_short')}`",
            "",
            "### 后续自动补写",
            "",
            "系统将在1/2/3/5/10/20/40个交易日后追加QQQ、TQQQ、路径、波动率、盘中/隔夜和方向/跟踪归因。",
            "缺失数据、失败交付和未解决状态会显式保留，不会被静默覆盖。",
            "",
            encode_marker(EVENT_MARKER_PREFIX, record),
        ]
    )
    if record["event_type"] == "state_change" and record.get("fingerprint"):
        lines.append(f"<!-- signal-fingerprint:{record['fingerprint']} -->")
    return "\n".join(lines).rstrip() + "\n"


def render_observation_comment(observation: Mapping[str, Any]) -> str:
    """Render one idempotent outcome update comment."""

    lines = [
        f"## 前瞻证据更新 · {observation['as_of_data_date']}",
        "",
        f"- 状态：`{observation['status']}`",
        f"- 可用交易日：**{observation['available_sessions']}**",
        f"- 本次新增期限：`{observation['new_horizons']}`",
    ]
    execution = observation.get("execution")
    if isinstance(execution, Mapping):
        lines.extend(
            [
                f"- 理论执行日：**{execution.get('execution_date')}**",
                f"- 理论下一开盘价：`{execution.get('theoretical_next_open_prices')}`",
                f"- QQQ开盘跳空：`{execution.get('qqq_opening_gap')}`",
            ]
        )
    for horizon in observation.get("new_horizons", []):
        outcome = observation.get("outcomes", {}).get(str(horizon), {})
        lines.extend(
            [
                "",
                f"### {horizon}个交易日",
                "",
                f"- QQQ：`{outcome.get('qqq_return')}`",
                f"- TQQQ：`{outcome.get('tqqq_return')}`",
                f"- 50%相对25%原始分量：`{outcome.get('raw_50_vs_25_component')}`",
                f"- 方向杠杆分量：`{outcome.get('directional_leverage_component')}`",
                f"- 跟踪/复利分量：`{outcome.get('tracking_compounding_component')}`",
            ]
        )
        if int(horizon) == 5:
            lines.extend(
                [
                    f"- QQQ MFE / MAE：`{outcome.get('qqq_mfe')}` / `{outcome.get('qqq_mae')}`",
                    f"- QQQ年化实现波动率：`{outcome.get('qqq_realized_volatility_annualized')}`",
                    f"- QQQ方向反转次数：`{outcome.get('qqq_sign_reversals')}`",
                    f"- 盘中 / 隔夜对数收益：`{outcome.get('qqq_intraday_log_return')}` / `{outcome.get('qqq_overnight_log_return')}`",
                ]
            )
    lines.extend(["", encode_marker(UPDATE_MARKER_PREFIX, observation)])
    return "\n".join(lines).rstrip() + "\n"


def build_monthly_summary(
    event_items: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    month: str,
) -> dict[str, Any]:
    """Build a non-promotional monthly operating summary."""

    records = [
        item.get("record", item)
        for item in event_items
        if isinstance(item.get("record", item), Mapping)
    ]
    month_records = [item for item in records if str(item.get("signal_date", "")).startswith(month)]
    observation_by_id = {str(item["event_id"]): item for item in observations if "event_id" in item}
    completed_counts = {str(horizon): 0 for horizon in (1, 2, 3, 5, 10, 20, 40)}
    unresolved = 0
    for record in month_records:
        observation = observation_by_id.get(str(record.get("event_id")), {})
        completed = {int(value) for value in observation.get("completed_horizons", [])}
        for horizon in completed_counts:
            completed_counts[horizon] += int(int(horizon) in completed)
        unresolved += int(40 not in completed)
    return {
        "schema_version": "1.0",
        "month": month,
        "research_only": True,
        "trade_ready": False,
        "event_count": len(month_records),
        "state_change_event_count": sum(
            item.get("event_type") == "state_change" for item in month_records
        ),
        "recovery_precursor_event_count": sum(
            item.get("event_type") == "recovery_precursor" for item in month_records
        ),
        "completed_horizon_counts": completed_counts,
        "unresolved_40_session_count": unresolved,
        "model_change_authorized": False,
        "interpretation": (
            "Operating evidence accumulation only; this monthly summary cannot "
            "promote, retune or modify v4.2."
        ),
    }


def render_monthly_summary(summary: Mapping[str, Any]) -> str:
    lines = [
        f"## v4.2 前瞻证据月报 · {summary['month']}",
        "",
        "> 仅汇总证据积累，不构成策略晋级、参数调整或交易建议。",
        "",
        f"- 新事件：**{summary['event_count']}**",
        f"- 状态变化：**{summary['state_change_event_count']}**",
        f"- 恢复前置信号：**{summary['recovery_precursor_event_count']}**",
        f"- 40日尚未完成：**{summary['unresolved_40_session_count']}**",
        f"- 各期限完成数：`{summary['completed_horizon_counts']}`",
        "- 模型变更授权：**否**",
        "",
        encode_marker(MONTH_MARKER_PREFIX, summary),
    ]
    return "\n".join(lines).rstrip() + "\n"
