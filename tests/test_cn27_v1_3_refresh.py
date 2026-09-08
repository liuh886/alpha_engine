from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.refresh_cn_27_v1_3_formal import (
    Cn27V13RefreshError,
    _check_recipe_identity,
    extend_bars,
    refresh_cn_27_v1_3,
)
from src.artifacts.formal_bundle_reader import load_formal_run
from src.research.cn27_v1_3_replay import replay_cn_27_v1_3

ROOT = Path(__file__).resolve().parents[1]
FROZEN_PRICES = (
    ROOT / "artifacts/evidence/cn_all_weather_alpha_rotation_v1/source_ohlcv.csv"
)
FIELDS = ("open", "high", "low", "close", "volume")
FULL_CUTOFF = "2026-09-04"
TRUNCATED_CUTOFF = "2026-06-30"


def _write_day_bin(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = np.asarray([0.0, *values], dtype="<f4")
    path.write_bytes(payload.tobytes())


def _write_provider_panel(
    provider_dir: Path, bars: pd.DataFrame, *, cutoff: str
) -> None:
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.loc[frame["date"] <= pd.Timestamp(cutoff)]
    dates = sorted(frame["date"].dt.strftime("%Y-%m-%d").unique().tolist())
    (provider_dir / "calendars").mkdir(parents=True, exist_ok=True)
    (provider_dir / "calendars" / "day.txt").write_text(
        "\n".join(dates) + "\n", encoding="utf-8"
    )
    (provider_dir / "instruments").mkdir(parents=True, exist_ok=True)
    symbols = sorted(frame["symbol"].astype(str).unique().tolist())
    (provider_dir / "instruments" / "cn.txt").write_text(
        "".join(
            f"{symbol.zfill(6)}\t{dates[0]}\t{dates[-1]}\n" for symbol in symbols
        ),
        encoding="utf-8",
    )
    by_symbol = frame["symbol"].astype(str)
    for symbol in symbols:
        key = symbol.zfill(6)
        sub = frame.loc[by_symbol.eq(symbol)].copy()
        sub = sub.set_index(sub["date"].dt.strftime("%Y-%m-%d"))
        for field in FIELDS:
            values = [
                float(sub.loc[day, field]) if day in sub.index else float("nan")
                for day in dates
            ]
            _write_day_bin(provider_dir / "features" / key / f"{field}.day.bin", values)


def _write_manifest(path: Path, cutoff: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cutoff": cutoff,
                "quarantined_symbols": [],
                "legacy_copied_symbols": [],
                "unresolved_stale_symbols": [],
            }
        ),
        encoding="utf-8",
    )


def _frozen_bars() -> pd.DataFrame:
    return pd.read_csv(FROZEN_PRICES, dtype={"symbol": str}, parse_dates=["date"])


def test_replay_exact_incumbent() -> None:
    receipt = replay_cn_27_v1_3(root=ROOT)
    assert receipt["decision"] == "exact_replay"
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False


def test_replay_missing_root_is_invalid_evidence(tmp_path: Path) -> None:
    receipt = replay_cn_27_v1_3(root=tmp_path / "absent")
    assert receipt["decision"] == "invalid_evidence"


def test_replay_revised_prices_are_data_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.research.cn27_v1_3_replay as replay_module

    monkeypatch.setattr(replay_module, "_sha256_file", lambda path: "0" * 64)
    receipt = replay_cn_27_v1_3(root=ROOT)
    assert receipt["decision"] == "data_blocked"


def test_recipe_identity_drift_fails_closed() -> None:
    from scripts.refresh_cn_27_v1_3_formal import RECIPE_ID as _RECIPE_ID

    current = {
        "portfolio_contract": {
            "maximum_single_equity_sleeve_share": 0.22,
            "maximum_sector_equity_sleeve_share": 0.45,
            "minimum_effective_names": 8.0,
        }
    }
    recipe = {
        "id": _RECIPE_ID,
        "maximum_single_equity_sleeve_share": 0.99,
        "maximum_sector_equity_sleeve_share": 0.45,
        "minimum_effective_names": 8.0,
    }
    with pytest.raises(Cn27V13RefreshError, match="param drifted"):
        _check_recipe_identity(recipe, current)


def test_refresh_cutoff_must_extend(tmp_path: Path) -> None:
    current_path = tmp_path / "current.json"
    current_path.write_text(
        json.dumps({"model_id": "cn_27_v1_3", "evidence_cutoff": "2026-09-04"}),
        encoding="utf-8",
    )
    with pytest.raises(Cn27V13RefreshError, match="extend beyond"):
        refresh_cn_27_v1_3(
            current_package=current_path,
            provider_dir=tmp_path / "provider",
            provider_manifest=tmp_path / "manifest.json",
            cutoff="2020-01-01",
            generated_at="2026-09-08T00:00:00Z",
            output=tmp_path / "candidate.json",
        )


def test_refresh_manifest_cutoff_mismatch_fails_closed(tmp_path: Path) -> None:
    run = load_formal_run(ROOT, "cn_27_v1_3")
    state = run.refresh_state()
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps(state), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, "2020-01-01")
    with pytest.raises(Cn27V13RefreshError, match="cutoff"):
        refresh_cn_27_v1_3(
            current_package=current_path,
            provider_dir=tmp_path / "provider",
            provider_manifest=manifest_path,
            cutoff="2026-09-05",
            generated_at="2026-09-08T00:00:00Z",
            output=tmp_path / "candidate.json",
        )


def test_extend_bars_restatement_fails_closed(tmp_path: Path) -> None:
    bars = _frozen_bars()
    restated = bars.copy()
    mask = restated["symbol"].astype(str).eq("600900")
    restated.loc[mask, "close"] = restated.loc[mask, "close"] * 1.01
    extra = restated.loc[restated["date"] == restated["date"].max()].copy()
    extra["date"] = extra["date"] + pd.Timedelta(days=7)
    provider_input = pd.concat([restated, extra], ignore_index=True)
    provider_dir = tmp_path / "provider"
    _write_provider_panel(provider_dir, provider_input, cutoff="2026-09-11")
    with pytest.raises(Cn27V13RefreshError, match="restated"):
        extend_bars(
            frozen_bars=bars, provider_dir=provider_dir, cutoff="2026-09-11"
        )


def test_refresh_truncated_extension_rebuilds_exact_prefix(tmp_path: Path) -> None:
    bars = _frozen_bars()
    truncated = bars.loc[bars["date"] <= pd.Timestamp(TRUNCATED_CUTOFF)].copy()
    assert not truncated.empty
    frozen_path = tmp_path / "source_ohlcv_trunc.csv"
    truncated.to_csv(frozen_path, index=False)
    provider_dir = tmp_path / "provider"
    _write_provider_panel(provider_dir, bars, cutoff=FULL_CUTOFF)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, FULL_CUTOFF)

    run = load_formal_run(ROOT, "cn_27_v1_3")
    state = run.refresh_state()
    current = copy.deepcopy(state)
    current["evidence_cutoff"] = TRUNCATED_CUTOFF
    for field in ("report", "positions", "trades"):
        current[field] = [
            row for row in state[field] if str(row["date"]) <= TRUNCATED_CUTOFF
        ]
    assert current["report"] and len(current["report"]) < len(state["report"])
    current["evidence"] = {
        **state["evidence"],
        "source_prices": frozen_path.relative_to(ROOT).as_posix()
        if frozen_path.is_relative_to(ROOT)
        else str(frozen_path),
        "source_prices_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
    }
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    output = tmp_path / "candidate.json"
    summary = refresh_cn_27_v1_3(
        current_package=current_path,
        provider_dir=provider_dir,
        provider_manifest=manifest_path,
        cutoff=FULL_CUTOFF,
        generated_at="2026-09-08T00:00:00Z",
        output=output,
    )
    candidate = json.loads(output.read_text(encoding="utf-8"))
    assert candidate["evidence_cutoff"] == FULL_CUTOFF
    assert candidate["backtest_id"] == "cn_27_v1_3-through-2026_09_04"
    from src.research.cn27_v1_3_replay import rows_close_enough

    for field in ("report", "positions", "trades"):
        assert rows_close_enough(
            candidate[field][: len(current[field])], current[field]
        )
    assert len(candidate["report"]) > len(current["report"])
    assert summary["model_selection_reopened"] is False
    published_report = state["report"]
    assert len(candidate["report"]) == len(published_report)
    for fresh_row, published_row in zip(candidate["report"], published_report):
        assert fresh_row["date"] == published_row["date"]
        for key, value in published_row.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                assert fresh_row[key] == value
            else:
                assert abs(float(fresh_row[key]) - float(value)) <= 1e-6 * max(
                    1.0, abs(float(value))
                )


def test_execute_strategy_resolves_cn_27_adapter(tmp_path: Path) -> None:
    from scripts.run_formal_strategy_refresh import PLAN_SCHEMA, execute_strategy

    task = {
        "strategy_id": "cn_27",
        "model_family_id": "cn_27_rotation",
        "model_version_id": "cn_27_v1_3",
        "model_kind": "rules_based_allocation",
        "market": "cn",
        "publication_input": "native_bundle_v2",
        "formal_refresh_capability_status": "available",
        "formal_refresh_adapter_id": "cn_27_v1_3_formal_refresh_v1",
        "formal_refresh_block_reason": None,
        "planned_provider_cutoff": FULL_CUTOFF,
        "formal_refresh_required": False,
        "mtm_refresh_required": False,
    }
    plan = {"schema_version": PLAN_SCHEMA, "tasks": [task]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    from scripts.run_formal_strategy_refresh import _task

    resolved = _task(plan_path, "cn_27")
    assert resolved["formal_refresh_adapter_id"] == "cn_27_v1_3_formal_refresh_v1"
    receipt = execute_strategy(
        root=ROOT,
        task=resolved,
        provider_root=tmp_path / "provider",
        formal_v2_root=ROOT / "data/research/formal_model_runs",
        current_preview_root=ROOT / "data/research/model_runs",
        result_root=tmp_path / "result",
        generated_at="2026-09-08T00:00:00Z",
    )
    assert receipt["execution_status"] == "current_no_change"


def test_execute_strategy_cn_27_missing_provider_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    import scripts.run_formal_strategy_refresh as refresh_runner

    monkeypatch.setattr(
        refresh_runner,
        "replay_cn_27_v1_3",
        lambda *, root: {"decision": "exact_replay"},
    )
    task = {
        "strategy_id": "cn_27",
        "model_family_id": "cn_27_rotation",
        "model_version_id": "cn_27_v1_3",
        "model_kind": "rules_based_allocation",
        "market": "cn",
        "publication_input": "native_bundle_v2",
        "formal_refresh_capability_status": "available",
        "formal_refresh_adapter_id": "cn_27_v1_3_formal_refresh_v1",
        "formal_refresh_block_reason": None,
        "planned_provider_cutoff": "2026-09-05",
        "formal_refresh_required": True,
        "mtm_refresh_required": False,
    }
    # The missing provider surfaces as a subprocess failure, which main()
    # converts to an execution_failed receipt. Here we assert dispatch
    # resolved the adapter (no unknown-adapter block) and the failure is
    # the absent provider, not a wiring error.
    with pytest.raises(subprocess.CalledProcessError):
        refresh_runner.execute_strategy(
            root=ROOT,
            task=task,
            provider_root=tmp_path / "provider",
            formal_v2_root=ROOT / "data/research/formal_model_runs",
            current_preview_root=ROOT / "data/research/model_runs",
            result_root=tmp_path / "result",
            generated_at="2026-09-08T00:00:00Z",
        )
