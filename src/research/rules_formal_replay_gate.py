from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from numbers import Real
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.promote_cn_x1_1_formal import build_package as build_cn_frozen_package
from src.artifacts.formal_refresh import load_object, sha256
from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    run_regime_portfolio,
)
from src.research.replay_comparison import compare_package_sections

CN_MODEL_ID = "cn_x1_1"
CN_FROZEN_EVIDENCE = Path("data/research/cn_x1_1_regime_gated_candidate_v1")
CN_FROZEN_SCORE_MANIFEST = (
    CN_FROZEN_EVIDENCE / "frozen_score_cross_sections_2026H2_manifest.json"
)
CN_WINDOW = "2026H2_PARTIAL"
CN_REPLAY_LEDGER_NAME = (
    "2026H2_PARTIAL__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz"
)


class RulesFormalReplayError(ValueError):
    """Raised when an accepted rules-based economic path cannot be reproduced."""


def _raise_mismatch(label: str, comparison: Mapping[str, Any]) -> None:
    raise RulesFormalReplayError(
        f"{label} exact replay mismatch: "
        + json.dumps(comparison, ensure_ascii=False, sort_keys=True, default=str)
    )


def _prefix_package(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    prefix: dict[str, Any] = {
        "portfolio_contract": observed.get("portfolio_contract"),
    }
    for section in ("report", "positions", "trades"):
        expected_rows = expected.get(section)
        observed_rows = observed.get(section)
        if not isinstance(expected_rows, list) or not isinstance(observed_rows, list):
            prefix[section] = observed_rows
            continue
        prefix[section] = observed_rows[: len(expected_rows)]
    return prefix


def assert_exact_formal_prefix(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    comparison = compare_package_sections(expected, _prefix_package(expected, observed))
    if not comparison["exact"]:
        _raise_mismatch(label, comparison)
    return comparison


def verify_cn_frozen_prefix(
    repository_root: str | Path,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    if package.get("model_id") != CN_MODEL_ID:
        raise RulesFormalReplayError("CN replay requires the accepted cn_x1_1 package")
    evidence_root = (root / CN_FROZEN_EVIDENCE).resolve()
    frozen = build_cn_frozen_package(
        evidence_root,
        generated_at=str(package.get("generated_at") or "frozen-replay"),
    )
    comparison = assert_exact_formal_prefix(
        frozen,
        package,
        label="CN x1.1 frozen incumbent prefix",
    )
    report = frozen.get("report")
    if not isinstance(report, list) or not report:
        raise RulesFormalReplayError("CN frozen formal report is empty")
    boundary = max(str(row["date"]) for row in report if isinstance(row, Mapping))
    return {
        "decision": "exact_replay",
        "boundary": boundary,
        "evidence_root": str(CN_FROZEN_EVIDENCE),
        "evidence_manifest_sha256": sha256(evidence_root / "evidence_manifest.json"),
        "trace_reproduction": comparison,
    }


def _weights_before(package: Mapping[str, Any], boundary: str) -> dict[str, float]:
    positions = package.get("positions")
    if not isinstance(positions, list):
        raise RulesFormalReplayError("CN formal positions are missing")
    eligible = [
        row
        for row in positions
        if isinstance(row, Mapping)
        and row.get("date")
        and str(row["date"]) < boundary
    ]
    if not eligible:
        return {}
    latest = max(str(row["date"]) for row in eligible)
    weights = {
        str(row["instrument"]): float(row["weight"])
        for row in positions
        if isinstance(row, Mapping) and str(row.get("date")) == latest
    }
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise RulesFormalReplayError(
            f"CN formal pre-window weights do not sum to one on {latest}"
        )
    return weights


def _cn_report_rows(periods: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in periods.sort_values("datetime").to_dict("records"):
        risk_on = bool(row["risk_on"])
        rows.append(
            {
                "date": pd.Timestamp(row["datetime"]).date().isoformat(),
                "period_return": float(row["net_return"]),
                "gross_return": float(row["gross_return"]),
                "benchmark_return": float(row["benchmark_return"]),
                "relative_log_return": float(row["relative_log_return"]),
                "turnover": float(row["turnover"]),
                "transaction_cost": float(row["cost"]),
                "risk_on": risk_on,
                "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                "votes": int(row["votes"]),
                "long_trend": bool(row["long_trend"]),
                "medium_momentum": bool(row["medium_momentum"]),
                "cross_sectional_breadth": bool(row["cross_sectional_breadth"]),
                "breadth_value": float(row["breadth_value"]),
                "benchmark_hit": bool(row["benchmark_hit"]),
            }
        )
    return rows


def _cn_position_rows(
    periods: pd.DataFrame,
    holdings: pd.DataFrame,
) -> list[dict[str, Any]]:
    risk_by_date = {
        pd.Timestamp(row["datetime"]).date().isoformat(): bool(row["risk_on"])
        for row in periods.to_dict("records")
    }
    rows: list[dict[str, Any]] = []
    for row in holdings.to_dict("records"):
        date = pd.Timestamp(row["datetime"]).date().isoformat()
        score = row.get("score")
        rows.append(
            {
                "date": date,
                "instrument": str(row["instrument"]),
                "name": str(row["entity"]),
                "sector": str(row["sector"]),
                "weight": float(row["weight"]),
                "score": None if pd.isna(score) else float(score),
                "raw_return": float(row["raw_return"]),
                "benchmark_return": float(row["benchmark_return"]),
                "net_contribution": float(row["net_contribution"]),
                "precision_hit": bool(row["precision_hit"]),
                "risk_state": (
                    "risk_on" if risk_by_date[date] else "risk_off_csi300_fallback"
                ),
            }
        )
    return sorted(rows, key=lambda row: (row["date"], row["instrument"]))


def _project_fields(
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    return [{field: row.get(field) for field in fields} for row in rows]


def _accepted_decimal_match(expected: object, observed: object) -> bool:
    """Replay numbers through the serializer that produced accepted frozen CSVs.

    CN x1.1 candidate CSVs were written with pandas ``float_format="%.10g"``.
    If the accepted JSON value is itself exactly representable by that serializer,
    the current replay must serialize back to the same ten-significant-digit text.
    Values with more retained precision are not frozen-CSV values and remain strict.
    """

    if isinstance(expected, bool) or isinstance(observed, bool):
        return expected == observed
    if not isinstance(expected, Real) or not isinstance(observed, Real):
        return expected == observed
    left = float(expected)
    right = float(observed)
    if math.isnan(left) and math.isnan(right):
        return True
    if not math.isfinite(left) or not math.isfinite(right):
        return left == right
    accepted_text = str(expected)
    if format(left, ".10g") == accepted_text:
        return format(right, ".10g") == accepted_text
    return left == right


def _compare_rows_at_accepted_precision(
    expected: object,
    observed: object,
) -> dict[str, Any]:
    if not isinstance(expected, list) or not isinstance(observed, list):
        return {
            "exact": False,
            "expected_rows": len(expected) if isinstance(expected, list) else None,
            "observed_rows": len(observed) if isinstance(observed, list) else None,
            "first_mismatch": {"reason": "section_is_not_a_row_list"},
            "comparison_semantics": "accepted_frozen_csv_serializer_or_full_precision",
        }
    first_mismatch: dict[str, Any] | None = None
    if len(expected) != len(observed):
        first_mismatch = {
            "reason": "row_count_mismatch",
            "expected": len(expected),
            "observed": len(observed),
        }
    for index, (left, right) in enumerate(zip(expected, observed, strict=False)):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            if first_mismatch is None:
                first_mismatch = {"reason": "row_is_not_mapping", "index": index}
            continue
        if set(left) != set(right):
            if first_mismatch is None:
                first_mismatch = {
                    "reason": "field_set_mismatch",
                    "index": index,
                    "expected_only": sorted(set(left) - set(right)),
                    "observed_only": sorted(set(right) - set(left)),
                }
            continue
        for field, expected_value in left.items():
            observed_value = right[field]
            if _accepted_decimal_match(expected_value, observed_value):
                continue
            if first_mismatch is None:
                first_mismatch = {
                    "reason": "value_mismatch",
                    "index": index,
                    "field": field,
                    "expected": expected_value,
                    "observed": observed_value,
                }
    return {
        "exact": first_mismatch is None,
        "expected_rows": len(expected),
        "observed_rows": len(observed),
        "first_mismatch": first_mismatch,
        "comparison_semantics": "accepted_frozen_csv_serializer_or_full_precision",
    }


def _load_cn_frozen_score_cross_sections(
    root: Path,
    *,
    symbols: Sequence[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    evidence_root = (root / CN_FROZEN_EVIDENCE).resolve()
    manifest_path = (root / CN_FROZEN_SCORE_MANIFEST).resolve()
    manifest = load_object(manifest_path)
    if manifest.get("schema_version") != "cn_x1_1_frozen_score_cross_sections_v1":
        raise RulesFormalReplayError("CN frozen score manifest schema is invalid")
    if manifest.get("model_id") != CN_MODEL_ID or manifest.get("window") != CN_WINDOW:
        raise RulesFormalReplayError("CN frozen score manifest identity is invalid")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise RulesFormalReplayError("CN frozen score manifest violates research boundary")

    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise RulesFormalReplayError("CN frozen score source provenance is missing")
    certification = load_object(evidence_root / "manifest.json")
    if source.get("provider_identity_sha256") != certification.get(
        "provider_identity_sha256"
    ):
        raise RulesFormalReplayError("CN frozen score provider identity is not certified")
    ledger_rows = certification.get("ledger_files")
    if not isinstance(ledger_rows, list):
        raise RulesFormalReplayError("CN certified ledger inventory is missing")
    source_sha = str(source.get("source_sha256") or "")
    source_name = Path(str(source.get("source_path") or "")).name
    matches = [
        row
        for row in ledger_rows
        if isinstance(row, Mapping)
        and Path(str(row.get("path") or "")).name == source_name
        and str(row.get("sha256") or "") == source_sha
    ]
    if len(matches) != 1:
        raise RulesFormalReplayError("CN frozen score source SHA is not certified")

    expected_symbols = {str(symbol).zfill(6) for symbol in symbols}
    declared_dates = [str(value) for value in manifest.get("accepted_signal_dates", [])]
    cross_sections = manifest.get("cross_sections")
    if not declared_dates or not isinstance(cross_sections, list):
        raise RulesFormalReplayError("CN frozen score cross-section inventory is empty")

    frames: list[pd.DataFrame] = []
    seen_dates: list[str] = []
    required_columns = [
        "window",
        "datetime",
        "instrument",
        "score",
        "execution_forward_return",
        "entity",
        "sector",
    ]
    for record in cross_sections:
        if not isinstance(record, Mapping):
            raise RulesFormalReplayError("CN frozen score cross-section row is invalid")
        date = str(record.get("date") or "")
        relative = Path(str(record.get("path") or ""))
        path = (evidence_root / relative).resolve()
        path.relative_to(evidence_root)
        if not path.is_file() or sha256(path) != str(record.get("sha256") or ""):
            raise RulesFormalReplayError(
                f"CN frozen score cross-section hash mismatch: {date}"
            )
        frame = pd.read_csv(path, dtype={"instrument": str})
        if list(frame.columns) != required_columns:
            raise RulesFormalReplayError(
                f"CN frozen score cross-section columns changed: {date}"
            )
        frame["instrument"] = frame["instrument"].astype(str).str.zfill(6)
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise")
        if len(frame) != int(record.get("rows", -1)) or len(frame) != 130:
            raise RulesFormalReplayError(
                f"CN frozen score cross-section row count changed: {date}"
            )
        if set(frame["instrument"]) != expected_symbols or frame["instrument"].duplicated().any():
            raise RulesFormalReplayError(
                f"CN frozen score cross-section universe changed: {date}"
            )
        frame_dates = set(frame["datetime"].dt.date.astype(str))
        if frame_dates != {date} or set(frame["window"].astype(str)) != {CN_WINDOW}:
            raise RulesFormalReplayError(
                f"CN frozen score cross-section date/window changed: {date}"
            )
        if not pd.to_numeric(frame["score"], errors="coerce").notna().all():
            raise RulesFormalReplayError(f"CN frozen score values are invalid: {date}")
        if not pd.to_numeric(
            frame["execution_forward_return"], errors="coerce"
        ).notna().all():
            raise RulesFormalReplayError(
                f"CN frozen execution returns are invalid: {date}"
            )
        frames.append(frame)
        seen_dates.append(date)

    if seen_dates != declared_dates or len(set(seen_dates)) != len(seen_dates):
        raise RulesFormalReplayError("CN frozen score accepted dates changed")
    combined = pd.concat(frames, ignore_index=True)
    return combined, {
        "manifest_path": str(manifest_path.relative_to(root)),
        "manifest_sha256": sha256(manifest_path),
        "accepted_signal_dates": declared_dates,
        "cross_section_sha256": {
            str(row["date"]): str(row["sha256"])
            for row in cross_sections
            if isinstance(row, Mapping)
        },
        "source": dict(source),
    }


def _replay_cn_frozen_score_dates(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    state: pd.DataFrame,
    *,
    package: Mapping[str, Any],
    spec: RegimeGateSpec,
    dates: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    previous = _weights_before(package, dates[0])
    period_frames: list[pd.DataFrame] = []
    holding_frames: list[pd.DataFrame] = []
    for date in dates:
        timestamp = pd.Timestamp(date)
        day = ledger.loc[ledger["datetime"].eq(timestamp)].copy()
        if len(day) != 130:
            raise RulesFormalReplayError(
                f"CN frozen score cross-section unavailable for replay: {date}"
            )
        _, periods, holdings, _ = run_regime_portfolio(
            day,
            benchmark_returns,
            state,
            windows=(CN_WINDOW,),
            variant=spec.variant(),
            rule="two_of_three",
            rebalance_sessions=1,
            cost_bps=spec.cost_bps,
            initial_weights=previous,
        )
        if len(periods) != 1:
            raise RulesFormalReplayError(f"CN frozen replay did not emit one period: {date}")
        current = {
            str(row["instrument"]): float(row["weight"])
            for row in holdings.to_dict("records")
        }
        if not current or not math.isclose(
            sum(current.values()), 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise RulesFormalReplayError(f"CN frozen replay weights are invalid: {date}")
        previous = current
        period_frames.append(periods)
        holding_frames.append(holdings)
    return (
        pd.concat(period_frames, ignore_index=True),
        pd.concat(holding_frames, ignore_index=True),
    )


def verify_cn_current_allocation_replay(
    repository_root: str | Path,
    *,
    package_path: str | Path,
    provider_dir: str | Path,
    ledger_path: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    package = load_object(Path(package_path).resolve())
    frozen_prefix = verify_cn_frozen_prefix(root, package)

    universe = yaml.safe_load(
        (root / "configs/research_universes/cn_selected_equities_v3.yaml").read_text(
            encoding="utf-8"
        )
    )
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise RulesFormalReplayError("CN130 universe identity is not exact")

    frozen_scores, score_identity = _load_cn_frozen_score_cross_sections(
        root,
        symbols=symbols,
    )
    replay_dates = list(score_identity["accepted_signal_dates"])
    spec = RegimeGateSpec()
    panel = load_provider_panel(
        Path(provider_dir).resolve(),
        [*symbols, spec.benchmark],
        fields=("close",),
    )
    close = panel.fields["close"]
    state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=spec.benchmark,
        long_ma_sessions=spec.long_ma_sessions,
        momentum_sessions=spec.momentum_sessions,
        breadth_ma_sessions=spec.breadth_ma_sessions,
        breadth_threshold=spec.breadth_threshold,
    )
    benchmark_returns = forward_returns(
        close[[spec.benchmark]],
        horizon=spec.horizon_sessions,
        delay=spec.execution_delay_sessions,
    )[spec.benchmark]
    periods, holdings = _replay_cn_frozen_score_dates(
        frozen_scores,
        benchmark_returns,
        state,
        package=package,
        spec=spec,
        dates=replay_dates,
    )

    computed_report = _cn_report_rows(periods)
    accepted_report = [
        row
        for row in package.get("report", [])
        if isinstance(row, Mapping) and str(row.get("date") or "") in replay_dates
    ]
    report_fields = (
        "date",
        "period_return",
        "gross_return",
        "benchmark_return",
        "relative_log_return",
        "turnover",
        "transaction_cost",
        "risk_on",
        "risk_state",
        "votes",
        "long_trend",
        "medium_momentum",
        "cross_sectional_breadth",
        "breadth_value",
        "benchmark_hit",
    )
    report_expected = _project_fields(accepted_report, report_fields)
    report_observed = _project_fields(computed_report, report_fields)
    report_comparison = _compare_rows_at_accepted_precision(
        report_expected, report_observed
    )
    if not report_comparison["exact"]:
        _raise_mismatch("CN x1.1 frozen-score allocation report", report_comparison)

    computed_positions = _cn_position_rows(periods, holdings)
    accepted_positions = sorted(
        [
            row
            for row in package.get("positions", [])
            if isinstance(row, Mapping) and str(row.get("date") or "") in replay_dates
        ],
        key=lambda row: (str(row.get("date")), str(row.get("instrument"))),
    )
    position_fields = (
        "date",
        "instrument",
        "name",
        "sector",
        "weight",
        "score",
        "raw_return",
        "benchmark_return",
        "net_contribution",
        "precision_hit",
        "risk_state",
    )
    position_expected = _project_fields(accepted_positions, position_fields)
    position_observed = _project_fields(computed_positions, position_fields)
    position_comparison = _compare_rows_at_accepted_precision(
        position_expected, position_observed
    )
    if not position_comparison["exact"]:
        _raise_mismatch("CN x1.1 frozen-score allocation positions", position_comparison)
    if len(report_expected) != len(replay_dates):
        raise RulesFormalReplayError(
            "CN frozen score dates do not match accepted settled formal trace"
        )

    future_ledger = Path(ledger_path).resolve()
    if not future_ledger.is_file():
        raise RulesFormalReplayError("CN current score ledger is missing")

    return {
        "schema_version": "1.2",
        "model_id": CN_MODEL_ID,
        "decision": "exact_replay",
        "frozen_prefix": frozen_prefix,
        "current_allocation": {
            "accepted_overlap_periods": len(report_expected),
            "report": report_comparison,
            "positions": position_comparison,
            "historical_score_authority": "committed_frozen_score_cross_sections",
            "frozen_score_identity": score_identity,
            "future_score_ledger_sha256": sha256(future_ledger),
            "provider_calendar_start": pd.Timestamp(close.index.min()).date().isoformat(),
            "provider_calendar_end": pd.Timestamp(close.index.max()).date().isoformat(),
            "continuation_state_source": (
                f"accepted_formal_positions_before_{replay_dates[0]}"
            ),
            "numeric_comparison": (
                "accepted_frozen_csv_serializer_or_full_precision"
            ),
        },
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
