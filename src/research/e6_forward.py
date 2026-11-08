"""Owner-operated append-only forward paper evidence; no feeds, fits or orders.

First-seen is the actual local receipt clock, not an independent timestamp
authority. Historical PIT/real-fill/capacity claims remain separate blockers.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from exchange_calendars import get_calendar
from scipy.stats import spearmanr

from src.research.e5_score_reconstruction import sha
from src.research.e6_execution import CONTRACT_SHA, E5Inputs, contract
from src.research.execution_selection import make_selection
from src.research.portfolio_ledger import replay_ledger, summarize_ledger
from src.research.study_workspace import save_receipt_exclusive

PRICE_BASIS = "e6_fixed_20261103_adjustment_basis_v1_requires_source_action_bridge"


def is_sha(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def utc(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("naive timestamps cannot establish availability")
    return stamp.astimezone(timezone.utc)


def load(root: Path) -> tuple[dict, dict]:
    cfg = contract(root / "contract.json")
    record = json.loads((root / "registration.json").read_bytes())
    if (
        record["forward_code_sha256"] != sha(Path(__file__))
        or record["contract_sha256"] != CONTRACT_SHA
    ):
        raise ValueError("forward code/contract changed after registration")
    return cfg, record


def register(root: Path, contract_path: Path, inputs: E5Inputs, now: datetime) -> dict:
    cfg = contract(contract_path)
    calendar = get_calendar("XNYS")
    first = cfg["forward"]["first_signal_session"]
    if now >= calendar.session_open(first).to_pydatetime():
        raise ValueError("late registration needs a new truly future contract")
    models = {s: inputs.doc(f"scores/{s}/f2026h2/score-receipt.json") for s in cfg["strategies"]}
    record = {
        "schema_version": "e6_forward_registration_v1",
        "contract_sha256": CONTRACT_SHA,
        "first_signal_session": first,
        "registered_at_utc": now.isoformat(),
        "forward_code_sha256": sha(Path(__file__)),
        "price_basis_id": PRICE_BASIS,
        "symbols": list(inputs.close.columns),
        "models": models,
        "primary_policy": cfg["primary_forward_policy"],
        "status": "WAITING_FUTURE_INPUTS_AND_FROZEN_TREE_MODEL_ARTIFACTS",
        "no_prior_consumption_certified": False,
        "independent_timestamp_attested": False,
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }
    root.mkdir(parents=True, exist_ok=False)
    with (root / "contract.json").open("xb") as out:
        out.write(contract_path.read_bytes())
    save_receipt_exclusive(root / "registration.json", record)
    return record


def bind_model(root: Path, strategy: str, model: Path, receipt: dict, now: datetime) -> dict:
    cfg, registered = load(root)
    if now >= get_calendar("XNYS").session_open(registered["first_signal_session"]).to_pydatetime():
        raise ValueError("model must be fixed before the first forward market session")
    if strategy not in ("xgb_p03", "lgb_p05"):
        raise ValueError("only missing frozen tree artifacts may be bound")
    expected = registered["models"][strategy]
    keys = (
        "configuration",
        "train_end",
        "X_train_sha256",
        "y_train_sha256",
        "native_git_sha",
        "source_history_sha256",
    )
    for key in keys:
        if receipt.get(key) != expected[key]:
            raise ValueError("model receipt differs from the locked E5 recipe/training inputs")
    raw = model.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if receipt.get("model_sha256") != digest:
        raise ValueError("model artifact hash mismatch")
    record = {
        "strategy": strategy,
        "model_sha256": digest,
        "producer_receipt": {key: receipt[key] for key in keys},
        "bound_at_utc": now.isoformat(),
        "contract_sha256": CONTRACT_SHA,
        "proof_limit": "producer_receipt_bound_not_independently_refitted_or_trade_certified",
    }
    # Preserve the actual binary in this private evidence namespace, not a moving path.
    target = root / "models" / f"{strategy}.model"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(target) != digest:
            raise ValueError("refusing to replace a retained forward model")
    else:
        with target.open("xb") as out:
            out.write(raw)
    save_receipt_exclusive(root / "models" / f"{strategy}.json", record)
    return record


def prediction(root: Path, source: Path, now: datetime) -> dict:
    cfg, registered = load(root)
    doc = json.loads(source.read_bytes())
    signal = doc["signal_session"]
    strategy = doc["strategy"]
    calendar = get_calendar("XNYS")
    if strategy not in cfg["strategies"] or signal < registered["first_signal_session"]:
        raise ValueError("historical or unfrozen prediction")
    close = calendar.session_close(signal).to_pydatetime()
    deadline = calendar.session_open(calendar.next_session(signal)).to_pydatetime()
    generated = utc(doc["generated_at_utc"])
    available = utc(doc["source_available_at_utc"])
    if not close <= available <= generated <= now < deadline:
        raise ValueError(
            "prediction was not captured after source availability and before next open"
        )
    if doc.get("contract_sha256") != CONTRACT_SHA or set(doc["scores"]) != set(
        registered["symbols"]
    ):
        raise ValueError("prediction contract or pool differs")
    if not all(np.isfinite(v) for v in doc["scores"].values()):
        raise ValueError("missing or nonfinite future scores")
    if strategy in ("xgb_p03", "lgb_p05"):
        model = json.loads((root / "models" / f"{strategy}.json").read_bytes())
        if (
            doc.get("model_sha256") != model["model_sha256"]
            or sha(root / "models" / f"{strategy}.model") != model["model_sha256"]
        ):
            raise ValueError("prediction is not from the frozen forward model identity")
    if not is_sha(doc.get("source_snapshot_sha256")):
        raise ValueError("prediction needs a source snapshot fingerprint")
    record = {
        "prediction": doc,
        "received_at_utc": now.isoformat(),
        "deadline_utc": deadline.isoformat(),
        "input_file_sha256": sha(source),
        "status": "COMMITTED_BEFORE_FORWARD_FILL_DAY_OPEN",
        "research_only": True,
        "trade_ready": False,
    }
    save_receipt_exclusive(root / "predictions" / strategy / f"{signal}.json", record)
    return record


def market(root: Path, source: Path, now: datetime) -> dict:
    _, registered = load(root)
    doc = json.loads(source.read_bytes())
    day = doc["session"]
    if (
        day < registered["first_signal_session"]
        or now < get_calendar("XNYS").session_close(day).to_pydatetime()
    ):
        raise ValueError("historical backfill or future market outcome is not admissible")
    if not set(doc["close_by_symbol"]) == set(registered["symbols"]) | {"QQQ"}:
        raise ValueError("forward market pool is incomplete")
    if not all(np.isfinite(v) and v > 0 for v in doc["close_by_symbol"].values()):
        raise ValueError("invalid forward closing price")
    if (
        not get_calendar("XNYS").session_close(day).to_pydatetime()
        <= utc(doc["source_available_at_utc"])
        <= now
        or not is_sha(doc.get("source_snapshot_sha256"))
        or doc.get("price_basis_id") != registered["price_basis_id"]
        or not is_sha(doc.get("adjustment_evidence_sha256"))
    ):
        raise ValueError("market source evidence is not yet available")
    record = {
        "market": doc,
        "first_seen_at_utc": now.isoformat(),
        "input_file_sha256": sha(source),
        "source_vintage_limit": "local_snapshot_receipt_not_vendor_first_available_certification",
    }
    save_receipt_exclusive(root / "market" / f"{day}.json", record)
    return record


def outcome(root: Path, strategy: str, signal: str, now: datetime) -> dict:
    cfg, registered = load(root)
    if strategy not in cfg["strategies"] or signal < registered["first_signal_session"]:
        raise ValueError("outcome identity outside the frozen forward contract")
    calendar = get_calendar("XNYS")
    end = calendar.session_offset(signal, cfg["forward"]["outcome_horizon_sessions"]).strftime(
        "%Y-%m-%d"
    )
    if now < calendar.session_close(end).to_pydatetime():
        raise ValueError("five-session target is not mature")
    prediction_path = root / "predictions" / strategy / f"{signal}.json"
    forecast = json.loads(prediction_path.read_bytes())
    start_path = root / "market" / f"{signal}.json"
    end_path = root / "market" / f"{end}.json"
    start = json.loads(start_path.read_bytes())["market"]["close_by_symbol"]
    finish = json.loads(end_path.read_bytes())["market"]["close_by_symbol"]
    symbols = registered["symbols"]
    target = [finish[s] / start[s] - 1 for s in symbols]
    scores = [forecast["prediction"]["scores"][s] for s in symbols]
    ic = float(spearmanr(scores, target).statistic)
    record = {
        "strategy": strategy,
        "signal_session": signal,
        "label_end": end,
        "rank_ic_5d": ic if np.isfinite(ic) else None,
        "evaluated_at_utc": now.isoformat(),
        "prediction_sha256": sha(prediction_path),
        "start_price_sha256": sha(start_path),
        "end_price_sha256": sha(end_path),
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }
    save_receipt_exclusive(root / "outcomes" / strategy / f"{signal}.json", record)
    return record


def evaluate(root: Path, output: Path) -> dict:
    cfg, registered = load(root)
    paths = sorted((root / "market").glob("*.json"))
    if len(paths) < 3:
        raise ValueError("forward price intervals are not yet available")
    data = {
        json.loads(p.read_bytes())["market"]["session"]: json.loads(p.read_bytes())["market"][
            "close_by_symbol"
        ]
        for p in paths
    }
    calendar = get_calendar("XNYS")
    expected = (
        calendar.sessions_in_range(registered["first_signal_session"], max(data))
        .strftime("%Y-%m-%d")
        .tolist()
    )
    if sorted(data) != expected:
        raise ValueError("forward calendar gap: no dropping or price filling allowed")
    prices = pd.DataFrame.from_dict(data, orient="index").sort_index()
    symbols = registered["symbols"]
    sessions = expected[1:]
    arm = next(a for a in cfg["arms"] if a["id"] == registered["primary_policy"])
    output.mkdir(parents=True, exist_ok=False)
    summaries = {}
    for strategy in cfg["strategies"]:
        rows = []
        mapping = {}
        for fill, signal in zip(sessions, expected[:-1]):
            p = root / "predictions" / strategy / f"{signal}.json"
            receipt = json.loads(p.read_bytes())
            if utc(receipt["received_at_utc"]) >= utc(receipt["deadline_utc"]):
                raise ValueError("late prediction cannot enter forward replay")
            rows.append([receipt["prediction"]["scores"][s] for s in symbols])
            mapping[fill] = signal
        scores = pd.DataFrame(rows, index=sessions, columns=symbols)
        daily, assets = replay_ledger(
            scores=scores,
            prices=prices[symbols],
            qqq=prices["QQQ"],
            sessions=sessions,
            signal_sessions=mapping,
            mode="delayed_close_1session",
            liquidate_at_end=False,
            selection=make_selection(
                arm, symbols=symbols, calendar=expected, salt=cfg["contract_id"]
            ),
        )
        daily.to_parquet(output / f"{strategy}-daily.parquet", index=False)
        assets.to_parquet(output / f"{strategy}-assets.parquet", index=False)
        summaries[strategy] = summarize_ledger(daily, assets)
    report = {
        "contract_sha256": CONTRACT_SHA,
        "policy": registered["primary_policy"],
        "summaries": summaries,
        "model_fits": 0,
        "terminal_liquidation": False,
        "actual_fill_observed": False,
        "fixed_price_basis": registered["price_basis_id"],
        "corporate_action_bridge": "source_receipt_bound_not_independently_certified",
        "capacity_actual_gate": "BLOCKED_UNTIL_SOURCE_EVIDENCE_PASSES",
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }
    save_receipt_exclusive(output / "forward-paper-summary.json", report)
    return report


def status(root: Path, now: datetime) -> dict:
    cfg, registered = load(root)
    return {
        "contract_sha256": CONTRACT_SHA,
        "policy": registered["primary_policy"],
        "first_signal_session": registered["first_signal_session"],
        "future_has_started": now
        >= get_calendar("XNYS").session_close(registered["first_signal_session"]).to_pydatetime(),
        "missing_model_artifacts": [
            s for s in ("xgb_p03", "lgb_p05") if not (root / "models" / f"{s}.json").exists()
        ],
        "predictions_captured": len(list((root / "predictions").rglob("*.json"))),
        "market_packets": len(list((root / "market").glob("*.json"))),
        "actual_execution_gate": "BLOCKED_SOURCE_UNITS_ACTION_BRIDGE_AND_FILL_EVIDENCE",
        "model_fits": 0,
        "trade_ready": False,
        "pit_certified": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=("register", "bind-model", "prediction", "market", "outcome", "evaluate", "status"),
    )
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--contract", type=Path)
    p.add_argument("--e5-package", type=Path)
    p.add_argument("--input", type=Path)
    p.add_argument("--model", type=Path)
    p.add_argument("--strategy")
    p.add_argument("--signal")
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    now = datetime.now(timezone.utc)
    for target in (args.root, args.output):
        if target is not None and target.resolve().is_relative_to(
            Path(__file__).resolve().parents[2]
        ):
            raise ValueError("private forward evidence must stay outside checkout")
    if args.action == "register":
        cfg = contract(args.contract)
        inputs = E5Inputs(args.e5_package, cfg)
        try:
            result = register(args.root, args.contract, inputs, now)
        finally:
            inputs.close_file()
        print(result["status"])
        return 0
    if args.action == "status":
        result = status(args.root, now)
    elif args.action == "bind-model":
        result = bind_model(
            args.root, args.strategy, args.model, json.loads(args.input.read_bytes()), now
        )
    elif args.action == "prediction":
        result = prediction(args.root, args.input, now)
    elif args.action == "market":
        result = market(args.root, args.input, now)
    elif args.action == "outcome":
        result = outcome(args.root, args.strategy, args.signal, now)
    else:
        result = evaluate(args.root, args.output)
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
