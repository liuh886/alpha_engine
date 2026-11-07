"""Real-time rules-only paper cycle: source → sealed forecast → delayed paper ledger.

No model fit, broker, historical prediction backfill, or automatic episode reset.
Canonical immutable receipts are private; health/report projections are disposable.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import uuid

import numpy as np
import pandas as pd
from exchange_calendars import get_calendar

from src.research import e7_source
from src.research.e5_score_reconstruction import sha
from src.research.execution_selection import make_selection
from src.research.portfolio_ledger import replay_ledger, summarize_ledger
from src.research.study_workspace import save_receipt_exclusive


class MissedPrediction(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def single_writer(root: Path):
    # Native advisory locking releases on process exit; an old lock file is harmless.
    with (root / ".cycle.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def code_identity() -> dict:
    root = Path(__file__).resolve().parents[2]
    paths = (
        "src/research/e7_paper_daily.py",
        "src/research/e7_source.py",
        "src/research/execution_selection.py",
        "src/research/portfolio_ledger.py",
        "src/research/walkforward/pipeline.py",
        "src/data/adapters/yfinance_adapter.py",
        "src/research/study_workspace.py",
        "uv.lock",
    )
    return {p: sha(root / p) for p in paths}


def environment() -> dict:
    return {
        "python": platform.python_version(),
        **{
            p: importlib.metadata.version(p)
            for p in ("numpy", "pandas", "yfinance", "pyarrow", "exchange_calendars")
        },
    }


def initialize(root: Path, contract_path: Path, now: datetime) -> dict:
    cfg = json.loads(contract_path.read_bytes())
    first = cfg["first_signal_session"]
    if (
        set(cfg["strategies"]) != {"rule_momentum60", "rule_momentum120"}
        or cfg["strategies"] != {"rule_momentum60": 60, "rule_momentum120": 120}
        or len(set(cfg["symbols"])) != 73
        or cfg["benchmark"] in cfg["symbols"]
        or cfg["tree_models_enabled"] is not False
        or cfg["trade_ready"] is not False
    ):
        raise ValueError("E7 requires the explicit two-rule US73 contract")
    if now >= get_calendar("XNYS").session_open(first).to_pydatetime():
        raise MissedPrediction("freeze a NEW future episode before its first session opens")
    root.mkdir(parents=True, exist_ok=False)
    with (root / "contract.json").open("xb") as out:
        out.write(contract_path.read_bytes())
    record = {
        "episode_id": cfg["episode_id"],
        "contract_sha256": sha(root / "contract.json"),
        "registered_at_utc": now.isoformat(),
        "code_sha256": code_identity(),
        "environment": environment(),
        "first_signal_session": first,
        "strategies": cfg["strategies"],
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
        "independent_timestamp_attested": False,
        "status": "REGISTERED_RULES_ONLY_NOT_E6_FOUR_MODEL_RESUME",
    }
    save_receipt_exclusive(root / "registration.json", record)
    return record


def load(root: Path) -> tuple[dict, dict]:
    reg = json.loads((root / "registration.json").read_bytes())
    if (
        sha(root / "contract.json") != reg["contract_sha256"]
        or code_identity() != reg["code_sha256"]
        or environment() != reg["environment"]
    ):
        raise ValueError("frozen E7 source/contract/dependency identity changed")
    return json.loads((root / "contract.json").read_bytes()), reg


def latest_closed(now: datetime) -> str:
    cal = get_calendar("XNYS")
    dates = cal.sessions_in_range(
        (now - timedelta(days=14)).date().isoformat(), now.date().isoformat()
    )
    for d in reversed(dates):
        if cal.session_close(d).to_pydatetime() <= now:
            return d.strftime("%Y-%m-%d")
    raise ValueError("no completed exchange session")


def deadline(day: str) -> datetime:
    cal = get_calendar("XNYS")
    return cal.session_open(cal.next_session(day)).to_pydatetime()


def read_prediction(root: Path, day: str, cfg: dict) -> dict:
    p = root / "predictions" / f"{day}.json"
    row = json.loads(p.read_bytes())
    if row["session"] != day or row["contract_sha256"] != sha(root / "contract.json"):
        raise ValueError("retained prediction identity mismatch")
    if pd.Timestamp(row["received_at_utc"]).to_pydatetime() >= deadline(day):
        raise MissedPrediction("late prediction cannot enter paper replay")
    if row["market_receipt_sha256"] != sha(root / "market" / f"{day}.json"):
        raise ValueError("forecast source receipt changed")
    for s in cfg["strategies"]:
        if set(row["scores"][s]) != set(cfg["symbols"]) or not all(
            np.isfinite(v) for v in row["scores"][s].values()
        ):
            raise ValueError("retained forecast cross-section is incomplete")
    return row


def seal_prediction(root: Path, cfg: dict, day: str, now: datetime) -> dict:
    path = root / "predictions" / f"{day}.json"
    if path.exists():
        return read_prediction(root, day, cfg)
    market, frame = e7_source.read(root, day, cfg)
    available = pd.Timestamp(market["available_at_utc"]).to_pydatetime()
    if (
        not get_calendar("XNYS").session_close(day).to_pydatetime()
        <= available
        <= now
        < deadline(day)
    ):
        raise MissedPrediction(
            f"{day} has missed its actual next-open prediction deadline; no backfill"
        )
    close = frame.pivot(index="date", columns="symbol", values="close").loc[:, cfg["symbols"]]
    scores = {
        strategy: {
            s: float(close[s].iloc[-1] / close[s].iloc[-lookback - 1] - 1) for s in cfg["symbols"]
        }
        for strategy, lookback in cfg["strategies"].items()
    }
    record = {
        "schema_version": "e7_joint_rules_prediction_v1",
        "session": day,
        "received_at_utc": now.isoformat(),
        "source_available_at_utc": market["available_at_utc"],
        "deadline_utc": deadline(day).isoformat(),
        "contract_sha256": sha(root / "contract.json"),
        "market_receipt_sha256": sha(root / "market" / f"{day}.json"),
        "scores": scores,
        "status": "TWO_RULE_PREDICTIONS_SEALED_BEFORE_NEXT_OPEN",
        "model_fits": 0,
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }
    save_receipt_exclusive(path, record)
    return record


def parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    out = io.BytesIO()
    frame.to_parquet(out, index=False)
    raw = out.getvalue()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("refusing to rewrite retained paper table")
    else:
        with path.open("xb") as handle:
            handle.write(raw)


def paper(root: Path, cfg: dict, day: str, now: datetime) -> dict:
    existing = root / "paper" / day / "receipt.json"
    if existing.exists():
        row = json.loads(existing.read_bytes())
        for name, h in row["files"].items():
            if sha(existing.parent / name) != h:
                raise ValueError("paper evidence hash mismatch")
        return row
    cal = get_calendar("XNYS")
    first = cfg["first_signal_session"]
    dates = cal.sessions_in_range(first, day).strftime("%Y-%m-%d").tolist()
    if len(dates) < 2:
        return {"status": "WAITING_NEXT_SESSION_PAPER_FILL", "observed_return_intervals": 0}
    indexes = {dates[0]: {s: 1.0 for s in [*cfg["symbols"], cfg["benchmark"]]}}
    bridge = []
    panels = {}
    market_refs = {}
    for d in dates:
        meta, frame = e7_source.read(root, d, cfg)
        panels[d] = frame.pivot(index="date", columns="symbol", values="close")
        market_refs[d] = sha(root / "market" / f"{d}.json")
        if d == dates[0]:
            continue
        previous = dates[dates.index(d) - 1]
        # Both prices in each return ratio are from the same actually-observed vintage.
        ratio = panels[d].loc[d] / panels[d].loc[previous]
        for s in ratio.index:
            indexes.setdefault(d, {})[s] = indexes[previous][s] * float(ratio[s])
            bridge.append(
                {
                    "session": d,
                    "previous_session": previous,
                    "symbol": s,
                    "observed_return_ratio": float(ratio[s]),
                    "previous_mark_revision_ratio": float(
                        panels[d].loc[previous, s] / panels[previous].loc[previous, s]
                    ),
                    "source_snapshot_sha256": meta["frame_sha256"],
                    "action_bridge_certified": False,
                }
            )
    prices = pd.DataFrame.from_dict(indexes, orient="index").sort_index()
    fill_days = dates[1:]
    summaries = {}
    fill_records = {}
    all_files = {}
    folder = root / "paper" / day
    folder.mkdir(parents=True, exist_ok=True)
    parquet_exclusive(folder / "source-adjustment-bridge.parquet", pd.DataFrame(bridge))
    for strategy in cfg["strategies"]:
        mappings = {fill: signal for fill, signal in zip(fill_days, dates[:-1])}
        predictions = {d: read_prediction(root, d, cfg) for d in dates[:-1]}
        scores = pd.DataFrame(
            [
                [predictions[mappings[d]]["scores"][strategy][s] for s in cfg["symbols"]]
                for d in fill_days
            ],
            index=fill_days,
            columns=cfg["symbols"],
        )
        state = {}
        daily, assets = replay_ledger(
            scores=scores,
            prices=prices[cfg["symbols"]],
            qqq=prices[cfg["benchmark"]],
            sessions=fill_days,
            friction=cfg["execution"]["friction_per_turnover"],
            signal_sessions=mappings,
            mode="delayed_close_1session",
            liquidate_at_end=False,
            end_state=state,
            selection=make_selection(
                cfg["execution"], symbols=cfg["symbols"], calendar=dates, salt=cfg["episode_id"]
            ),
        )
        parquet_exclusive(folder / f"{strategy}-daily.parquet", daily)
        parquet_exclusive(folder / f"{strategy}-assets.parquet", assets)
        summaries[strategy] = (
            summarize_ledger(daily, assets)
            if len(daily)
            else {
                "net_return": 0.0,
                "net_excess": 0.0,
                "qqq_return": 0.0,
                "max_drawdown": 0.0,
                "turnover": 0.0,
                "sessions": 0,
            }
        )
        current = e7_source.read(root, day, cfg)[1].query("date == @day").set_index("symbol")
        fills = []
        for i, s in enumerate(cfg["symbols"]):
            delta = float(state["target_weight"][i] - state["weight_before_fill"][i])
            if abs(delta) > 1e-14:
                fills.append(
                    {
                        "symbol": s,
                        "trade_weight": delta,
                        "target_weight": float(state["target_weight"][i]),
                        "observed_raw_close_reference": float(current.loc[s, "raw_close"]),
                        "normalized_reference_units_per_nav": delta
                        / float(current.loc[s, "raw_close"]),
                        "reported_volume": float(current.loc[s, "volume"]),
                        "actual_fill_observed": False,
                    }
                )
        fill_records[strategy] = {
            "signal_session": mappings[day],
            "fill_session": day,
            "prediction_sha256": sha(root / "predictions" / f"{mappings[day]}.json"),
            "paper_orders": fills,
            "turnover_at_close": float(state["turnover"]),
            "pending_fee_return": float(state["pending_fee_return"]),
            "cost_timing": state["cost_timing"],
            "capacity_certified": False,
            "execution": "PAPER_CLOSE_PROXY_NOT_ACTUAL_FILL",
            "actual_fill_observed": False,
            "cash_fee_funding_modelled": False,
        }
    fill_receipt = {
        "session": day,
        "generated_at_utc": now.isoformat(),
        "strategies": fill_records,
        "market_receipt_sha256": market_refs[day],
        "research_only": True,
        "trade_ready": False,
    }
    save_receipt_exclusive(root / "fills" / f"{day}.json", fill_receipt)
    for p in folder.glob("*.parquet"):
        all_files[p.name] = sha(p)
    result = {
        "status": "CONTINUOUS_PAPER_REFERENCE_NAV_UPDATED",
        "cutoff": day,
        "generated_at_utc": now.isoformat(),
        "summaries": summaries,
        "files": all_files,
        "fill_receipt_sha256": sha(root / "fills" / f"{day}.json"),
        "market_receipts": market_refs,
        "observed_return_intervals": len(dates) - 2,
        "terminal_liquidation": False,
        "accounting": "E4_interval_fee_deduction; current_close_fee_pending_until_next_observed_return",
        "price_basis": "daily_chained_same_snapshot_total_return_index_not_executable_quote",
        "actual_capacity_gate": "BLOCKED_AS_TRADED_VOLUME_ACTION_AVAILABILITY_AND_FILL_EVIDENCE",
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }
    save_receipt_exclusive(existing, result)
    return result


def health(root: Path, payload: dict) -> None:
    # Derived projection only; immutable cycles/failures remain the authority.
    folder = root / "health"
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, folder / "latest.json")


def report(root: Path, cycle: dict) -> None:
    folder = root / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "# E7 连续纸面研究",
        "",
        f"行情截止：{cycle['session']}；状态：{cycle['status']}",
        "",
        "60/120日动量；已封存预测才允许下一交易日纸面成交。研究净值不代表实盘账户，成交为收盘价代理，容量和公司行为可用时间尚未认证。",
        "",
    ]
    for s, row in cycle.get("paper", {}).get("summaries", {}).items():
        lines.append(
            f"- {s}：参考净值 {1 + row['net_return']:.6f}，超QQQ {100 * row['net_excess']:.3f}pp，回撤 {100 * row['max_drawdown']:.3f}%，已观察持有区间 {row['sessions']}。"
        )
    if cycle["status"] == "WARMUP_ONLY_NO_FORWARD_PREDICTION":
        lines.append("当前仅为真实行情预热，没有前瞻预测、纸面成交或未来收益。")
    lines += [
        "",
        "当日纸面成交费用按冻结口径计入下一个已观察持有区间；待计费用在fill回执单列。没有手续费筹资/真实成交或独立PIT认证。",
        "",
    ]
    path = folder / f"{cycle['session']}.md"
    if not path.exists():
        path.write_text("\n".join(lines), encoding="utf-8")


def run(root: Path, clock=now_utc, collector=e7_source.collect) -> dict:
    with single_writer(root):
        return _run(root, clock, collector)


def _run(root: Path, clock=now_utc, collector=e7_source.collect) -> dict:
    now = clock()
    day = latest_closed(now)
    try:
        cfg, reg = load(root)
        if (root / "HALTED.json").exists():
            raise MissedPrediction(
                "episode halted; freeze a new FUTURE start, never rewrite missing signals"
            )
        cycle_path = root / "cycles" / f"{day}.json"
        if cycle_path.exists():
            old = json.loads(cycle_path.read_bytes())
            e7_source.read(root, day, cfg)
            if old.get("prediction_sha256"):
                read_prediction(root, day, cfg)
                if sha(root / "predictions" / f"{day}.json") != old["prediction_sha256"]:
                    raise ValueError("sealed cycle prediction hash mismatch")
            if (root / "paper" / day / "receipt.json").exists():
                paper(root, cfg, day, now)
            health(
                root,
                {
                    "status": "UNCHANGED_VERIFIED_CUTOFF",
                    "session": day,
                    "checked_at_utc": now.isoformat(),
                    "cycle_sha256": sha(cycle_path),
                },
            )
            return old
        first = cfg["first_signal_session"]
        if day >= first:
            prior = (
                get_calendar("XNYS")
                .sessions_in_range(first, day)
                .strftime("%Y-%m-%d")
                .tolist()[:-1]
            )
            if any(not (root / "predictions" / f"{d}.json").exists() for d in prior):
                raise MissedPrediction(
                    "missing already-due prior prediction; a new future episode is required"
                )
            if now >= deadline(day) and not (root / "predictions" / f"{day}.json").exists():
                raise MissedPrediction(
                    "first/current signal deadline missed; no retrospective prediction allowed"
                )
        if not (root / "market" / f"{day}.json").exists():
            collector(root, cfg, day)
        market, _ = e7_source.read(root, day, cfg)
        state = {
            "status": "WARMUP_ONLY_NO_FORWARD_PREDICTION",
            "session": day,
            "generated_at_utc": clock().isoformat(),
            "source_rows": market["rows"],
            "source_symbols": market["source_symbols"],
            "market_sha256": sha(root / "market" / f"{day}.json"),
            "contract_sha256": reg["contract_sha256"],
            "model_fits": 0,
            "research_only": True,
            "trade_ready": False,
        }
        if day >= first:
            state["paper"] = paper(root, cfg, day, clock())
            seal_prediction(root, cfg, day, clock())
            state["status"] = "PREDICTIONS_SEALED_PAPER_EVIDENCE_ADVANCED"
            state["prediction_sha256"] = sha(root / "predictions" / f"{day}.json")
        save_receipt_exclusive(cycle_path, state)
        report(root, state)
        health(root, state)
        return state
    except Exception as exc:
        failure = {
            "session": day,
            "received_at_utc": clock().isoformat(),
            "type": type(exc).__name__,
            "reason": str(exc),
            "status": "FAILED_NO_FABRICATED_PREDICTION",
            "trade_ready": False,
        }
        save_receipt_exclusive(root / "failures" / (uuid.uuid4().hex + ".json"), failure)
        if isinstance(exc, MissedPrediction) and not (root / "HALTED.json").exists():
            save_receipt_exclusive(root / "HALTED.json", failure)
        health(root, failure)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("init", "run", "status"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--contract", type=Path)
    args = p.parse_args(argv)
    if args.root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("private E7 data must stay outside checkout")
    try:
        if args.action == "init":
            result = initialize(args.root, args.contract, now_utc())
        elif args.action == "run":
            result = run(args.root)
        else:
            cfg, reg = load(args.root)
            result = {
                "episode_id": reg["episode_id"],
                "first_signal_session": cfg["first_signal_session"],
                "predictions": len(list((args.root / "predictions").glob("*.json"))),
                "paper_fills": len(list((args.root / "fills").glob("*.json"))),
                "halted": (args.root / "HALTED.json").exists(),
                "model_fits": 0,
                "trade_ready": False,
            }
        print(json.dumps(result, allow_nan=False))
        return 0
    except Exception as exc:
        print("BLOCKED_E7", type(exc).__name__, str(exc))
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
