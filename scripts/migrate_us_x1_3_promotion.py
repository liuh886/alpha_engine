#!/usr/bin/env python3
"""One-shot migration for the user-authorized US x1.3 research-baseline promotion.

The migration intentionally reuses the governed US x1.2 execution/publication
machinery rather than creating a parallel permanent workflow.  It promotes the
Stage-B winner ``mvv_plus_pressure`` while preserving ``research_only=true`` and
``trade_ready=false``.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_required(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"required migration anchor missing in {label}: {old!r}")
    return text.replace(old, new)


def clone_text(source: str, target: str, replacements: list[tuple[str, str]]) -> str:
    text = read(source)
    for old, new in replacements:
        text = replace_required(text, old, new, label=source)
    write(target, text)
    return text


US_X1_3_CONFIG = """schema_version: '1.3'
model_id: us_x1_3
display_name: US x1.3
release_date: '2026-08-12'
status: baseline_research_active
research_only: true
trade_ready: false
market: us
benchmark: QQQ
objective: Rank the governed US87 equity pool for 10-session forward return with the Stage-B supported momentum/volatility/volume plus price-volume-pressure factor contract and the governed max-four-names-per-sector portfolio constraint.
lineage:
  parent: us_x1_2
  supersedes: us_x1_2
  selected_candidate: mvv_plus_pressure
  source_research_pr: 868
  stage_b_pr: 869
  stage_b_receipt: data/research/experiment_receipts/us_x1_3_stage_b_v1.json
  stage_b_validation_workflow_run_id: 31567853785
  stage_b_artifact_id: 9130182216
  stage_b_artifact_digest: sha256:6733fde47212088c902df88c436af553f2bd83e37a19c14d47e066ce5f8c199d
  adoption_decision: explicit_user_directed_research_baseline_promotion
  promotion_authority: explicit_user_direction_2026_08_12
  promotion_note: User-directed promotion after canonical Stage-B exact replay supported mvv_plus_pressure. This remains research-only and does not authorize brokerage execution or trade readiness.
universe:
  universe_id: us_selected_equities_v2
  source: configs/research_universes/us_selected_equities_v2.yaml
  declared_candidate_count: 87
  membership_mode: static_curated
  survivorship_bias: true
  listing_policy: no_prelisting_fill_coverage_qualified_static_members
provider_binding:
  policy: canonical_repository_source_rebuild
  stage_b_provider_identity_sha256: c2b8cc29ad70afde1b4590a03da6f82d4a9fd1e242426bc936333b7f7c3bd39d
  stage_b_cutoff: '2026-08-10'
features:
  library: configs/factor_libraries/ohlcv.yaml
  factor_ids:
  - ohlcv.momentum.ret_3d
  - ohlcv.momentum.ret_5d
  - ohlcv.momentum.ret_10d
  - ohlcv.momentum.ret_20d
  - ohlcv.volatility.std_ret_10d
  - ohlcv.volatility.std_ret_20d
  - ohlcv.volume.momentum_10d
  - ohlcv.liquidity.volume_vs_ma_5d
  - ohlcv.liquidity.volume_vs_ma_10d
  - ohlcv.liquidity.volume_vs_ma_20d
  - ohlcv.pressure.ret1_x_volume_shock_5d
  - ohlcv.pressure.ret5_x_volume_shock_10d
  - ohlcv.pressure.high_low_ratio
label:
  type: processed_daily_cross_sectional_percentile_gain
  economic_return_expression: Ref($close, -10) / $close - 1
  horizon_sessions: 10
  gain_bins: 7
model:
  family: xgb
  objective: rank:ndcg
  tree_method: hist
  grow_policy: lossguide
  max_leaves: 31
  max_depth: 0
  min_child_weight: 1.0
  learning_rate: 0.05
  num_boost_round: 200
  subsample: 0.8
  colsample_bytree: 0.8
  reg_alpha: 0.0
  reg_lambda: 1.0
  seed: 42
  score_orientation: original
strategy:
  holding_sessions: 10
  rebalance_sessions: 10
  top_n: 15
  bottom_n_diagnostic: 15
  weighting: equal_weight
  maximum_names_per_sector: 4
  effective_maximum_sector_weight: 0.26666666666666666
  sector_classification: configs/research_classifications/us87_sector_industry_v1.yaml
  fill_contract: scan_complete_eligible_cross_section_until_exactly_15
  fail_closed_if_unfillable: true
  cost_bps: 20
  benchmark_mode: reference_only
stage_b_evidence:
  experiment_id: us_x1_3_stage_b_v1
  runner: exact_us_ranker_portfolio_v1
  development_period: 2024H1-2025H2
  positive_windows: 4
  gate_pass_count: 6
  compounded_relative_excess_20bps: 1.8032463075003768
  compounded_relative_excess_60bps: 1.5919189436396328
  incumbent_compounded_relative_excess_20bps: 1.6706892505243864
  incumbent_compounded_relative_excess_60bps: 1.4534527938905026
  improvement_vs_incumbent_20bps: 0.1325570569759904
  improvement_vs_incumbent_60bps: 0.13846614974913019
  mean_rank_ic: 0.051617500000000004
  mean_rank_ic_improvement: 0.0019187500000000038
  worst_drawdown: -0.26532173378029633
  incumbent_worst_drawdown: -0.26218061541141957
  exact_score_reproduction: true
selection_decision:
  stage_b_supported: true
  selected_over: us_x1_2
  selected_by: canonical_stage_b_exact_replay_plus_explicit_user_direction
  formal_acceptance: false
  research_baseline_promotion: true
  promotion_authority: explicit_user_direction_2026_08_12
  reason: mvv_plus_pressure_passed_all_stage_b_support_gates_and_user_explicitly_directed_formal_research_baseline_promotion
acceptance_gate:
  untouched_future_six_month_window_required: true
  prospective_acceptance_pending: true
  clock_resets_for_exact_us_x1_3_identity: true
  no_automatic_trade_readiness: true
known_limitations:
- Static curated membership carries survivorship bias.
- Stage-B selection uses the declared development windows; no reporting window is reclassified as untouched evidence.
- The exact US x1.3 prospective acceptance clock starts from this model identity and may not inherit US x1.2 observations.
- This is an accepted research baseline after formal publication, not a trade-ready model.
"""


def build_x13_sources() -> None:
    write("configs/models/us_x1_3.yaml", US_X1_3_CONFIG)

    common = [
        ("us_x1_2", "us_x1_3"),
        ("USX12", "USX13"),
        ("US x1.2", "US x1.3"),
    ]
    preview = clone_text(
        "src/artifacts/us_x1_2_preview.py",
        "src/artifacts/us_x1_3_preview.py",
        common
        + [
            ("expected_count=7", "expected_count=13"),
            ('"selected_candidate": "r11_sampled"', '"selected_candidate": "mvv_plus_pressure"'),
            ('"formal_baseline_superseded_for_research": "us_x1_1"', '"formal_baseline_superseded_for_research": "us_x1_2"'),
        ],
    )
    preview = replace_required(
        preview,
        "panel = _price_panel(runtime, symbols, first_signal, cutoff)",
        'panel = _price_panel(runtime, [*symbols, "QQQ"], first_signal, cutoff)',
        label="src/artifacts/us_x1_3_preview.py",
    )
    mtm_anchor = """    latest_signal = signals[-1]\n    completeness = {\n"""
    mtm_block = """    latest_signal = signals[-1]\n\n    # Keep the settled 10-session trace immutable, but project the currently\n    # open governed holding to the provider/evidence cutoff.  This is a\n    # provisional MTM point, not a settled period, and exists so charts never\n    # stop at an old holding-end date while fresher governed prices exist.\n    if latest_signal.get(\"signal_state\") == \"prospective_unrealized\":\n        signal_date = str(latest_signal[\"signal_date\"])\n        target_weights = {\n            str(key): float(value)\n            for key, value in dict(latest_signal[\"target_weights\"]).items()\n        }\n        gross_mtm = 0.0\n        for instrument, weight in target_weights.items():\n            entry = _market_value(panel, signal_date, instrument, \"price\")\n            current = _market_value(panel, cutoff, instrument, \"price\")\n            if entry is None or current is None or entry <= 0:\n                raise USX13PreviewError(\n                    f\"missing provisional MTM price for {instrument}: {signal_date}/{cutoff}\"\n                )\n            gross_mtm += weight * (current / entry - 1.0)\n        qqq_entry = _market_value(panel, signal_date, \"QQQ\", \"price\")\n        qqq_current = _market_value(panel, cutoff, \"QQQ\", \"price\")\n        if qqq_entry is None or qqq_current is None or qqq_entry <= 0:\n            raise USX13PreviewError(\"missing QQQ provisional MTM price\")\n        mtm_cost = float(latest_signal.get(\"turnover\") or 0.0) * 20 / 10_000\n        net_mtm = gross_mtm - mtm_cost\n        benchmark_mtm = qqq_current / qqq_entry - 1.0\n        mtm_account = account * (1.0 + net_mtm)\n        mtm_benchmark = benchmark_account * (1.0 + benchmark_mtm)\n        settled_peak = max([1.0, *[float(row[\"account\"]) for row in report]])\n        report.append(\n            {\n                \"date\": signal_date,\n                \"holding_end_date\": cutoff,\n                \"window\": \"current_target\",\n                \"window_role\": \"prospective_unrealized\",\n                \"period_index\": global_period,\n                \"period_return\": net_mtm,\n                \"benchmark_return\": benchmark_mtm,\n                \"excess_return\": net_mtm - benchmark_mtm,\n                \"turnover\": float(latest_signal.get(\"turnover\") or 0.0),\n                \"transaction_cost\": mtm_cost,\n                \"account\": mtm_account,\n                \"bench_qqq\": mtm_benchmark,\n                \"drawdown\": mtm_account / max(settled_peak, mtm_account) - 1.0,\n                \"trace_frequency\": \"provisional_mtm_to_evidence_cutoff\",\n                \"partial_window\": True,\n                \"provisional_mtm\": True,\n                \"settlement_status\": \"provisional_mtm\",\n                \"mtm_as_of\": cutoff,\n                \"research_only\": True,\n                \"trade_ready\": False,\n            }\n        )\n\n    completeness = {\n"""
    preview = replace_required(preview, mtm_anchor, mtm_block, label="src/artifacts/us_x1_3_preview.py")
    write("src/artifacts/us_x1_3_preview.py", preview)

    clone_text(
        "scripts/build_us_x1_2_preview.py",
        "scripts/build_us_x1_3_preview.py",
        common,
    )

    current = clone_text(
        "src/research/us_x1_2_current_target.py",
        "src/research/us_x1_3_current_target.py",
        common
        + [
            ("expected_count=7", "expected_count=13"),
            ('lineage.get("selected_candidate") != "r11_sampled"', 'lineage.get("selected_candidate") != "mvv_plus_pressure"'),
            ('"selected_candidate": "r11_sampled"', '"selected_candidate": "mvv_plus_pressure"'),
            ('reason_code="formal_us_x1_2_10_session_rebalance"', 'reason_code="formal_us_x1_3_10_session_rebalance"'),
        ],
    )
    write("src/research/us_x1_3_current_target.py", current)

    runner = clone_text(
        "scripts/run_us_x1_2_current_target.py",
        "scripts/run_us_x1_3_current_target.py",
        common,
    )
    runner = replace_required(
        runner,
        "    due = next_due_session(anchor=anchor, sessions=sessions)\n",
        """    # A newly promoted model must publish its own first governed target;\n    # it must not inherit or relabel the predecessor ledger.  Bootstrap once at\n    # the latest completed provider session, then return to the 10-session clock.\n    if not (args.ledger_dir / \"latest.json\").is_file():\n        due = (\n            pd.Timestamp(sessions.max()).strftime(\"%Y-%m-%d\")\n            if len(sessions)\n            else None\n        )\n    else:\n        due = next_due_session(anchor=anchor, sessions=sessions)\n""",
        label="scripts/run_us_x1_3_current_target.py",
    )
    write("scripts/run_us_x1_3_current_target.py", runner)

    formal = clone_text(
        "src/artifacts/us_x1_2_formal.py",
        "src/artifacts/us_x1_3_formal.py",
        common
        + [
            ('SUPERSEDED_FORMAL_MODEL = "us_x1_1"', 'SUPERSEDED_FORMAL_MODEL = "us_x1_2"'),
        ],
    )
    write("src/artifacts/us_x1_3_formal.py", formal)


def patch_active_catalog() -> None:
    path = "configs/strategies/registry.json"
    payload = json.loads(read(path))
    rows = payload["strategies"]
    us = next(row for row in rows if row["strategy_id"] == "us_x")
    if us["model_version_id"] != "us_x1_2":
        raise RuntimeError(f"unexpected active US model: {us['model_version_id']}")
    us["display_name"] = "US x1.3"
    us["model_version_id"] = "us_x1_3"
    us["signal_ledger"] = "data/research/strategy_signal_ledgers/us_x1_3"
    write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def patch_refresh_runtime() -> None:
    path = "scripts/run_formal_strategy_refresh.py"
    text = read(path)
    text = replace_required(text, 'US_MODEL_ID = "us_x1_2"', 'US_MODEL_ID = "us_x1_3"', label=path)
    text = replace_required(text, '"scripts/build_us_x1_2_preview.py"', '"scripts/build_us_x1_3_preview.py"', label=path)
    text = text.replace("US x1.2", "US x1.3")
    write(path, text)

    path = "scripts/sync_formal_bundle_v2.py"
    text = read(path)
    text = replace_required(
        text,
        "from src.artifacts.us_x1_2_formal import promote_preview_bundle as promote_us_x1_2",
        "from src.artifacts.us_x1_3_formal import promote_preview_bundle as promote_us_x1_3",
        label=path,
    )
    text = replace_required(
        text,
        '    "us_x1_2": promote_us_x1_2,',
        '    "us_x1_3": promote_us_x1_3,',
        label=path,
    )
    write(path, text)

    # During an intentional version cutover, the checked-in formal catalog is
    # necessarily one revision behind the active catalog until the reviewed
    # refresh publishes the successor.  Allow only a declared supersedes edge,
    # never an arbitrary catalog mismatch.
    path = "scripts/run_formal_refresh_transaction.py"
    text = read(path)
    text = replace_required(text, "import shutil\n", "import shutil\n\nimport yaml\n", label=path)
    anchor = """def _cutoffs(us_manifest: Path, cn_manifest: Path) -> dict[str, str]:\n"""
    helper = """def _assert_formal_catalog_or_declared_transition(\n    formal_v2: Mapping[str, object],\n    active,\n) -> None:\n    try:\n        assert_formal_catalog_matches_active_strategies(formal_v2, active)\n        return\n    except ActiveStrategyCatalogError as original:\n        rows = formal_v2.get(\"records\")\n        if not isinstance(rows, list):\n            raise FormalRefreshError(str(original)) from original\n        observed = {\n            str(row.get(\"model_version_id\") or \"\")\n            for row in rows\n            if isinstance(row, Mapping)\n        }\n        expected = set(active.active_model_version_ids)\n        missing = expected - observed\n        extra = observed - expected\n        if not missing or len(missing) != len(extra):\n            raise FormalRefreshError(str(original)) from original\n        by_model = active.by_model_version_id\n        unmatched_extra = set(extra)\n        for successor in sorted(missing):\n            strategy = by_model.get(successor)\n            config_path = Path(\"configs/models\") / f\"{successor}.yaml\"\n            if strategy is None or not config_path.is_file():\n                raise FormalRefreshError(str(original)) from original\n            config = yaml.safe_load(config_path.read_text(encoding=\"utf-8\"))\n            lineage = config.get(\"lineage\") if isinstance(config, Mapping) else None\n            predecessor = (\n                str(lineage.get(\"supersedes\") or \"\")\n                if isinstance(lineage, Mapping)\n                else \"\"\n            )\n            predecessor_row = next(\n                (\n                    row\n                    for row in rows\n                    if isinstance(row, Mapping)\n                    and row.get(\"model_version_id\") == predecessor\n                ),\n                None,\n            )\n            if (\n                predecessor not in unmatched_extra\n                or not isinstance(predecessor_row, Mapping)\n                or predecessor_row.get(\"model_family_id\") != strategy.model_family_id\n                or predecessor_row.get(\"model_kind\") != strategy.model_kind\n                or predecessor_row.get(\"publication_status\") != strategy.formal_status\n            ):\n                raise FormalRefreshError(str(original)) from original\n            unmatched_extra.remove(predecessor)\n        if unmatched_extra:\n            raise FormalRefreshError(str(original)) from original\n\n\n"""
    text = replace_required(text, anchor, helper + anchor, label=path)
    old = """    try:\n        assert_formal_catalog_matches_active_strategies(formal_v2, active)\n    except ActiveStrategyCatalogError as exc:\n        raise FormalRefreshError(str(exc)) from exc\n"""
    text = replace_required(
        text,
        old,
        "    _assert_formal_catalog_or_declared_transition(formal_v2, active)\n",
        label=path,
    )
    write(path, text)


def patch_workflows() -> None:
    # Formal refresh: switch active US implementation and stop output/UI changes
    # from recursively launching the expensive provider + four-strategy refresh.
    path = ".github/workflows/formal-backtest-refresh.yml"
    text = read(path)
    for old, new in [
        ("configs/models/us_x1_2.yaml", "configs/models/us_x1_3.yaml"),
        ("src/artifacts/us_x1_2_preview.py", "src/artifacts/us_x1_3_preview.py"),
        ("scripts/build_us_x1_2_preview.py", "scripts/build_us_x1_3_preview.py"),
        ("tests/test_us_x1_2_preview_publication.py", "tests/test_us_x1_3_preview_publication.py"),
    ]:
        text = text.replace(old, new)
    for trigger in [
        '      - "data/research/formal_backtests/**"\n',
        '      - "data/research/formal_model_runs/**"\n',
        '      - "data/research/model_runs/**"\n',
        '      - "data/research/market_evidence/**"\n',
        '      - "data/research/model_data_bundle_v1/**"\n',
        '      - "data/research/strategy_signal_ledgers/**"\n',
        '      - "qlib-dashboard/scripts/**"\n',
        '      - "qlib-dashboard/src/**"\n',
        '      - "qlib-dashboard/package.json"\n',
        '      - "qlib-dashboard/package-lock.json"\n',
        '      - "qlib-dashboard/vite.config.*"\n',
        '      - "qlib-dashboard/tsconfig*.json"\n',
    ]:
        text = text.replace(trigger, "")
    write(path, text)

    path = ".github/workflows/formal-backtest-refresh-ci.yml"
    text = read(path)
    for old, new in [
        ("configs/models/us_x1_2.yaml", "configs/models/us_x1_3.yaml"),
        ("src/artifacts/us_x1_2_preview.py", "src/artifacts/us_x1_3_preview.py"),
        ("scripts/build_us_x1_2_preview.py", "scripts/build_us_x1_3_preview.py"),
        ("tests/test_us_x1_2_preview_publication.py", "tests/test_us_x1_3_preview_publication.py"),
    ]:
        text = text.replace(old, new)
    write(path, text)

    path = ".github/workflows/ranker-10d-current-target.yml"
    text = read(path)
    replacements = [
        ("scripts/run_us_x1_2_current_target.py", "scripts/run_us_x1_3_current_target.py"),
        ("src/research/us_x1_2_current_target.py", "src/research/us_x1_3_current_target.py"),
        ("configs/models/us_x1_2.yaml", "configs/models/us_x1_3.yaml"),
        ("strategy_signal_ledgers/us_x1_2", "strategy_signal_ledgers/us_x1_3"),
        ("Build due US x1.2 provider and current target", "Build due US x1.3 provider and current target"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    path_anchor = '      - "configs/factor_libraries/ohlcv.yaml"\n'
    text = replace_required(
        text,
        path_anchor,
        path_anchor + '      - "data/research/formal_model_runs/**"\n',
        label=path,
    )
    # Do not fail a promotion commit merely because the reviewed formal refresh
    # has not published x1.3 yet.  The formal-catalog output push retriggers this
    # workflow, at which point the first x1.3 target is bootstrapped immediately.
    due_anchor = """          as_of=\"$(date -u +%F)\"\n          mkdir -p artifacts/ranker-current-target\n          uv run python scripts/run_us_x1_3_current_target.py due \\\n"""
    due_replacement = """          as_of=\"$(date -u +%F)\"\n          mkdir -p artifacts/ranker-current-target\n          us_formal_ready=\"$(uv run python - <<'PY'\nimport json\nfrom pathlib import Path\np = Path('data/research/formal_model_runs/catalog.json')\ntry:\n    rows = json.loads(p.read_text()).get('records', [])\n    print('true' if any(r.get('model_version_id') == 'us_x1_3' for r in rows) else 'false')\nexcept Exception:\n    print('false')\nPY\n)\"\n          if [ \"$us_formal_ready\" = \"true\" ]; then\n            uv run python scripts/run_us_x1_3_current_target.py due \\\n"""
    text = replace_required(text, due_anchor, due_replacement, label=path)
    close_anchor = """            --as-of \"$as_of\" \\\n            --output artifacts/ranker-current-target/us_due.json\n          uv run python scripts/run_ranker_current_target.py due \\\n"""
    close_replacement = """            --as-of \"$as_of\" \\\n            --output artifacts/ranker-current-target/us_due.json\n          else\n            printf '%s\\n' '{\"market\":\"us\",\"model_version_id\":\"us_x1_3\",\"due\":false,\"signal_date\":null,\"reason\":\"awaiting_formal_promotion\",\"research_only\":true,\"trade_ready\":false}' > artifacts/ranker-current-target/us_due.json\n          fi\n          uv run python scripts/run_ranker_current_target.py due \\\n"""
    text = replace_required(text, close_anchor, close_replacement, label=path)
    # Every due 10-session evaluation is operationally material, even when the
    # target is unchanged.  Telegram/Issue delivery therefore follows the due
    # event rather than only allocation deltas.
    text = replace_required(
        text,
        """            changed=\"$(uv run python - \"$signal\" <<'PY'\n          import json, sys\n          print('true' if json.load(open(sys.argv[1]))['should_alert'] else 'false')\n          PY\n          )\"\n""",
        """            changed=\"true\"\n""",
        label=path,
    )
    write(path, text)


def patch_tests() -> None:
    common = [
        ("us_x1_2", "us_x1_3"),
        ("US x1.2", "US x1.3"),
    ]
    preview = clone_text(
        "tests/test_us_x1_2_preview_publication.py",
        "tests/test_us_x1_3_preview_publication.py",
        common,
    )
    insertion = """    performance = _object(\"performance.json\")\n"""
    # Add a direct regression for the original stale-chart failure.
    stale_test = """\n\ndef test_us_x1_3_chart_reaches_evidence_cutoff_with_provisional_mtm() -> None:\n    manifest = _object(\"manifest.json\")\n    performance = _object(\"performance.json\")\n    assert performance[\"report\"][-1][\"holding_end_date\"] == manifest[\"evidence_cutoff\"]\n    assert performance[\"date_range\"][\"end\"] == manifest[\"evidence_cutoff\"]\n    if performance[\"report\"][-1].get(\"provisional_mtm\"):\n        assert performance[\"report\"][-1][\"settlement_status\"] == \"provisional_mtm\"\n        assert performance[\"report\"][-1][\"trade_ready\"] is False\n"""
    preview += stale_test
    write("tests/test_us_x1_3_preview_publication.py", preview)

    current = clone_text(
        "tests/test_us_x1_2_current_target.py",
        "tests/test_us_x1_3_current_target.py",
        common
        + [
            ("r11_sampled", "mvv_plus_pressure"),
        ],
    )
    # Replace the frozen 7-factor assertion with the promoted 13-factor contract.
    start = current.index("    assert factor_ids == [")
    end = current.index("    assert list(factor_columns) == factor_ids", start)
    contract = """    assert factor_ids == [\n        \"ohlcv.momentum.ret_3d\",\n        \"ohlcv.momentum.ret_5d\",\n        \"ohlcv.momentum.ret_10d\",\n        \"ohlcv.momentum.ret_20d\",\n        \"ohlcv.volatility.std_ret_10d\",\n        \"ohlcv.volatility.std_ret_20d\",\n        \"ohlcv.volume.momentum_10d\",\n        \"ohlcv.liquidity.volume_vs_ma_5d\",\n        \"ohlcv.liquidity.volume_vs_ma_10d\",\n        \"ohlcv.liquidity.volume_vs_ma_20d\",\n        \"ohlcv.pressure.ret1_x_volume_shock_5d\",\n        \"ohlcv.pressure.ret5_x_volume_shock_10d\",\n        \"ohlcv.pressure.high_low_ratio\",\n    ]\n    assert len(expressions) == 13\n"""
    current = current[:start] + contract + current[end:]
    current = current.replace(
        "assert \"scripts/run_us_x1_3_current_target.py due\" in workflow",
        "assert \"scripts/run_us_x1_3_current_target.py due\" in workflow",
    )
    current = current.replace(
        'assert "strategy_signal_ledgers/us_x1_1" not in workflow',
        'assert "strategy_signal_ledgers/us_x1_2" not in workflow',
    )
    write("tests/test_us_x1_3_current_target.py", current)

    # Active-catalog and release tests should track the current active version;
    # historical x1.2-specific unit tests remain untouched as historical evidence.
    for path in [
        "tests/test_active_strategy_catalog.py",
        "tests/test_formal_refresh.py",
        "tests/test_formal_strategy_refresh.py",
        "tests/test_sync_formal_bundle_v2.py",
        "tests/test_strategy_operations.py",
        "scripts/validate_model_x1_baselines.py",
        "tests/test_model_x1_baselines.py",
    ]:
        p = ROOT / path
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        text = text.replace('"us_x1_2"', '"us_x1_3"')
        text = text.replace("'us_x1_2'", "'us_x1_3'")
        text = text.replace("US x1.2", "US x1.3")
        p.write_text(text, encoding="utf-8")


def main() -> None:
    build_x13_sources()
    patch_active_catalog()
    patch_refresh_runtime()
    patch_workflows()
    patch_tests()
    print("US x1.3 promotion migration staged successfully")


if __name__ == "__main__":
    main()
