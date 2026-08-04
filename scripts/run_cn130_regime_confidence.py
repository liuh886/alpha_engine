"""Run CN130 regime-conditioned factors and confidence-gated sector portfolios."""
from __future__ import annotations
import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import numpy as np
import pandas as pd
import yaml
import src.research.cn130_ranking_pipeline as rank_core
from src.research.cn130_cross_sectional_ranking import attach_classification, build_feature_matrices, compound, forward_returns, load_provider_panel, make_label, max_drawdown, stack_return_frame
from src.research.cn130_tail_factor_discovery import FACTOR_REGISTRY, build_discovery_factors, factor_window_metrics, sector_relative_factor, stack_wide
CALIBRATION_WINDOWS = {'2022H2': ('2022-07-01', '2022-12-31'), '2023H1': ('2023-01-01', '2023-06-30'), '2023H2': ('2023-07-01', '2023-12-31')}
VALIDATION_WINDOWS = {'2024H1': ('2024-01-01', '2024-06-30'), '2024H2': ('2024-07-01', '2024-12-31'), '2025H1': ('2025-01-01', '2025-06-30'), '2025H2': ('2025-07-01', '2025-12-31')}
REPORTING_WINDOWS = {'2026H1': ('2026-01-01', '2026-06-30'), '2026H2_PARTIAL': ('2026-07-01', '2026-12-31')}


@dataclass(frozen=True)
class ConfidenceVariant:
    variant_id: str
    fourth_threshold: bool = False
    gap_veto: bool = False
    risk_off_exposure: float = 1.0


REGIME_FACTOR_NAMES = ('trend_efficiency_20', 'momentum_10', 'momentum_20', 'reversal_3', 'distance_low_20', 'volume_price_confirmation_20', 'downside_volatility_20', 'intraday_range_20', 'drawdown_63', 'recovery_from_low_20', 'amihud_20', 'residual_momentum_20')
VARIANTS = (ConfidenceVariant('always_invested'), ConfidenceVariant('fourth_sector_score_fixed_0_80', fourth_threshold=True), ConfidenceVariant('sector_gap_fixed_0_10', gap_veto=True), ConfidenceVariant('combined_fixed_thresholds', fourth_threshold=True, gap_veto=True), ConfidenceVariant('risk_off_half_cash', risk_off_exposure=0.5), ConfidenceVariant('risk_off_full_cash', risk_off_exposure=0.0))


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime('%Y-%m-%d')
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format='%.10g', lineterminator='\n')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_validation_ledger(ledger_dir: Path, windows: Sequence[str]) -> pd.DataFrame:
    frames = []
    for window in windows:
        path = ledger_dir / 'score_ledgers' / f'{window}__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz'
        frame = pd.read_csv(path, compression='gzip', dtype={'instrument': str}, parse_dates=['datetime'])
        frame['instrument'] = frame['instrument'].str.zfill(6)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def market_states(benchmark_close: pd.Series) -> pd.Series:
    ma120 = benchmark_close.rolling(120, min_periods=100).mean()
    ret20 = benchmark_close.pct_change(20)
    drawdown120 = benchmark_close / benchmark_close.rolling(120, min_periods=100).max() - 1.0
    state = pd.Series('neutral', index=benchmark_close.index, dtype='object')
    risk_on = (benchmark_close > ma120) & (ret20 > 0.0) & (drawdown120 > -0.08)
    repair = (drawdown120 <= -0.08) & (ret20 > 0.0)
    risk_off = (benchmark_close < ma120) & (ret20 <= 0.0)
    state.loc[risk_on] = 'risk_on'
    state.loc[repair] = 'repair'
    state.loc[risk_off] = 'risk_off'
    return state.rename('market_state')


def sector_snapshot(day: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    ranked = day.dropna(subset=['score', 'execution_forward_return']).copy()
    ranked['score_pct'] = ranked['score'].rank(method='average', pct=True)
    ranked = ranked.sort_values(['score', 'instrument'], ascending=[False, True], kind='mergesort')
    sector_scores = ranked.groupby('sector', sort=True)['score_pct'].apply(lambda s: float(s.nlargest(min(3, len(s))).mean())).sort_values(ascending=False, kind='mergesort')
    selected = sector_scores.head(4)
    fourth = float(selected.iloc[-1]) if len(selected) == 4 else 0.0
    gap = float(selected.mean() - sector_scores.median())
    return (ranked, fourth, gap)


def choose_sector_4x1(day: pd.DataFrame, thresholds: dict[str, float], variant: ConfidenceVariant, state: str, excluded_name: str | None=None, excluded_sector: str | None=None) -> tuple[pd.DataFrame, float, dict[str, float]]:
    eligible = day.copy()
    if excluded_name:
        eligible = eligible.loc[eligible['instrument'] != excluded_name]
    if excluded_sector:
        eligible = eligible.loc[eligible['sector'] != excluded_sector]
    ranked, fourth, gap = sector_snapshot(eligible)
    ranked['score_pct'] = ranked['score'].rank(method='average', pct=True)
    ranked = ranked.sort_values(['score', 'instrument'], ascending=[False, True], kind='mergesort')
    sector_scores = ranked.groupby('sector', sort=True)['score_pct'].apply(lambda s: float(s.nlargest(min(3, len(s))).mean())).sort_values(ascending=False, kind='mergesort')
    if variant.gap_veto and gap < thresholds['sector_gap_threshold']:
        return (ranked.head(0), 0.0, {'fourth': fourth, 'gap': gap})
    selected_sectors = list(sector_scores.head(4).index)
    if variant.fourth_threshold:
        selected_sectors = [s for s in selected_sectors if sector_scores.loc[s] >= thresholds['fourth_sector_score_threshold']]
    pieces = [ranked.loc[ranked['sector'] == sector].head(1) for sector in selected_sectors]
    chosen = pd.concat(pieces) if pieces else ranked.head(0)
    base_exposure = len(chosen) / 4.0
    if state == 'risk_off':
        base_exposure *= variant.risk_off_exposure
    return (chosen, base_exposure, {'fourth': fourth, 'gap': gap})


def run_confidence_portfolio(ledger: pd.DataFrame, benchmark_execution: pd.Series, states: pd.Series, thresholds: dict[str, float], variant: ConfidenceVariant, cost_bps: int, windows: Sequence[str], excluded_name: str | None=None, excluded_sector: str | None=None) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    previous: dict[str, float] = {}
    period_rows = []
    holding_rows = []
    for window in windows:
        part = ledger.loc[ledger['window'] == window].copy()
        dates = sorted(pd.to_datetime(part['datetime'].unique()))[::10]
        for date in dates:
            day = part.loc[pd.to_datetime(part['datetime']) == date]
            state = str(states.get(date, 'neutral'))
            chosen, exposure, confidence = choose_sector_4x1(day, thresholds, variant, state, excluded_name, excluded_sector)
            if date not in benchmark_execution.index:
                continue
            if chosen.empty or exposure <= 0.0:
                weights: dict[str, float] = {}
                gross = 0.0
            else:
                weight = exposure / len(chosen)
                weights = {str(x): weight for x in chosen['instrument']}
                gross = float((chosen['execution_forward_return'] * weight).sum())
            turn = rank_core.turnover(previous, weights)
            cost = turn * cost_bps / 10000.0
            net = gross - cost
            benchmark = float(benchmark_execution.loc[date])
            period_rows.append({'window': window, 'datetime': date, 'state': state, 'gross_return': gross, 'net_return': net, 'benchmark_return': benchmark, 'turnover': turn, 'cost': cost, 'exposure': exposure, 'cash': 1.0 - exposure, 'n_holdings': len(chosen), 'fourth_sector_score': confidence['fourth'], 'sector_gap': confidence['gap']})
            if not chosen.empty and exposure > 0:
                weight = exposure / len(chosen)
                for row in chosen.itertuples(index=False):
                    holding_rows.append({'window': window, 'datetime': date, 'instrument': str(row.instrument), 'sector': row.sector, 'weight': weight, 'net_contribution': weight * row.execution_forward_return - cost / len(chosen)})
            previous = weights
    periods = pd.DataFrame(period_rows)
    holdings = pd.DataFrame(holding_rows)
    window_results = []
    for window, group in periods.groupby('window', sort=False):
        total = compound(group['net_return'])
        bench = compound(group['benchmark_return'])
        window_results.append({'window': window, 'relative_excess': (1 + total) / (1 + bench) - 1, 'total_return': total, 'benchmark_return': bench, 'max_drawdown': max_drawdown(group['net_return']), 'mean_exposure': float(group['exposure'].mean())})
    total = compound(periods['net_return'])
    bench = compound(periods['benchmark_return'])
    if holdings.empty:
        name_share = sector_share = 1.0
        top_name = top_sector = 'none'
    else:
        name = holdings.groupby('instrument')['net_contribution'].sum()
        sector = holdings.groupby('sector')['net_contribution'].sum()
        name_share = float(name.abs().max() / name.abs().sum()) if name.abs().sum() else 1.0
        sector_share = float(sector.abs().max() / sector.abs().sum()) if sector.abs().sum() else 1.0
        top_name = str(name.abs().idxmax())
        top_sector = str(sector.abs().idxmax())
    return ({'variant_id': variant.variant_id, 'cost_bps': cost_bps, 'total_return': total, 'benchmark_return': bench, 'relative_excess': (1 + total) / (1 + bench) - 1, 'max_drawdown': max_drawdown(periods['net_return']), 'turnover': float(periods['turnover'].sum()), 'positive_excess_windows': int(sum((x['relative_excess'] > 0 for x in window_results))), 'mean_exposure': float(periods['exposure'].mean()), 'cash_period_ratio': float((periods['cash'] > 1e-12).mean()), 'maximum_name_absolute_contribution_share': name_share, 'maximum_sector_absolute_contribution_share': sector_share, 'top_name': top_name, 'top_sector': top_sector, 'window_results': window_results}, periods, holdings)


def daily_state_factor_ic(factor: pd.Series, forward: pd.Series, states: pd.Series, start: str, end: str) -> pd.DataFrame:
    dates = factor.index.get_level_values('datetime')
    mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    joined = pd.DataFrame({'factor': factor.loc[mask], 'return': forward.reindex(factor.index[mask])}).dropna()
    rows = []
    for date, group in joined.groupby(level='datetime', sort=True):
        if len(group) < 30:
            continue
        ic = group['factor'].rank(pct=True).corr(group['return'].rank(pct=True))
        if pd.notna(ic):
            rows.append({'datetime': date, 'state': str(states.get(date, 'neutral')), 'rank_ic': float(ic)})
    return pd.DataFrame(rows)


def select_state_factors(factor_series: dict[str, pd.Series], factor_meta: dict[str, dict[str, Any]], forward: pd.Series, states: pd.Series) -> tuple[pd.DataFrame, dict[str, list[dict[str, Any]]]]:
    rows = []
    for factor_id, series in factor_series.items():
        daily = daily_state_factor_ic(series, forward, states, '2022-01-01', '2023-12-31')
        for state, group in daily.groupby('state', sort=True):
            values = group['rank_ic'].to_numpy(float)
            rows.append({'factor_id': factor_id, 'factor': factor_meta[factor_id]['factor'], 'family': factor_meta[factor_id]['family'], 'mode': factor_meta[factor_id]['mode'], 'state': state, 'n_dates': len(values), 'mean_rank_ic': float(values.mean()), 'rank_icir': float(values.mean() / values.std(ddof=1)) if len(values) > 1 and values.std(ddof=1) > 0 else 0.0, 'positive_ratio': float((values > 0).mean()), 'eligible': bool(len(values) >= 40 and abs(values.mean()) >= 0.01)})
    calibration = pd.DataFrame(rows)
    selected: dict[str, list[dict[str, Any]]] = {}
    corr_source = pd.concat({k: v for k, v in factor_series.items()}, axis=1)
    corr_rank = corr_source.loc[(corr_source.index.get_level_values('datetime') >= '2022-01-01') & (corr_source.index.get_level_values('datetime') <= '2023-12-31')].groupby(level='datetime').rank(pct=True).corr()
    for state in ['risk_on', 'repair', 'risk_off', 'neutral']:
        candidates = calibration.loc[(calibration['state'] == state) & calibration['eligible']].copy()
        candidates['abs_ic'] = candidates['mean_rank_ic'].abs()
        candidates = candidates.sort_values(['abs_ic', 'factor_id'], ascending=[False, True], kind='mergesort')
        chosen = []
        families = set()
        for row in candidates.itertuples(index=False):
            if row.family in families:
                continue
            if any((abs(float(corr_rank.loc[row.factor_id, x['factor_id']])) > 0.8 for x in chosen)):
                continue
            chosen.append({'factor_id': row.factor_id, 'factor': row.factor, 'family': row.family, 'mode': row.mode, 'calibration_mean_rank_ic': row.mean_rank_ic, 'sign': 1 if row.mean_rank_ic > 0 else -1, 'n_dates': row.n_dates})
            families.add(row.family)
            if len(chosen) >= 5:
                break
        selected[state] = chosen
    return (calibration, selected)


def build_regime_composite(factor_series: dict[str, pd.Series], states: pd.Series, selected: dict[str, list[dict[str, Any]]]) -> pd.Series:
    all_index = next(iter(factor_series.values())).index
    out = pd.Series(np.nan, index=all_index, name='regime_composite')
    for date in sorted(all_index.get_level_values('datetime').unique()):
        state = str(states.get(date, 'neutral'))
        rules = selected.get(state, [])
        idx = (date, slice(None))
        if not rules:
            continue
        parts = []
        for rule in rules:
            values = factor_series[rule['factor_id']].loc[idx]
            ranked = values.rank(method='average', pct=True) - 0.5
            parts.append(ranked * rule['sign'])
        composite = pd.concat(parts, axis=1).mean(axis=1)
        out.loc[idx] = composite.to_numpy()
    return out


def validate_composite(composite: pd.Series, forward: pd.Series, baseline: pd.Series) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for window, (start, end) in VALIDATION_WINDOWS.items():
        rows.append({'window': window, **factor_window_metrics(composite, forward, baseline, start, end)})
    frame = pd.DataFrame(rows)
    ics = frame['mean_rank_ic'].tolist()
    inc = frame['mean_incremental_rank_ic'].tolist()
    spreads = frame['mean_top_bottom_spread'].tolist()
    loo = [float(np.mean([ics[j] for j in range(4) if j != i])) for i in range(4)]
    summary = {'mean_window_rank_ic': float(np.mean(ics)), 'mean_window_rank_icir': float(frame['rank_icir'].mean()), 'positive_windows': int(sum((x > 0 for x in ics))), 'worst_window_rank_ic': float(min(ics)), 'mean_incremental_rank_ic': float(np.mean(inc)), 'mean_top_bottom_spread': float(np.mean(spreads)), 'minimum_leave_one_window_mean_rank_ic': float(min(loo))}
    summary['support_gate_pass'] = bool(summary['mean_window_rank_ic'] >= 0.015 and summary['positive_windows'] >= 3 and (summary['worst_window_rank_ic'] >= -0.01) and (summary['mean_incremental_rank_ic'] >= 0.005) and (summary['mean_top_bottom_spread'] >= 0.0025) and (summary['minimum_leave_one_window_mean_rank_ic'] >= 0.005))
    return (frame, summary)


def run(root: Path, provider_dir: Path, ledger_dir: Path, output_dir: Path) -> None:
    universe_path = root / 'configs/research_universes/cn_selected_equities_v3.yaml'
    class_path = root / 'configs/research_classifications/cn130_sector_industry_v1.yaml'
    symbols = [str(x).zfill(6) for x in yaml.safe_load(universe_path.read_text())['symbols']]
    classification_raw = yaml.safe_load(class_path.read_text())['symbols']
    classification = {str(k).zfill(6): v for k, v in classification_raw.items()}
    panel = load_provider_panel(provider_dir, [*symbols, '000300'])
    states = market_states(panel.fields['close']['000300'])
    thresholds = {'fourth_sector_score_threshold': 0.8, 'sector_gap_threshold': 0.1, 'source': 'fixed_economic_definition'}
    validation_ledger = load_validation_ledger(ledger_dir, VALIDATION_WINDOWS)
    reporting_ledger = load_validation_ledger(ledger_dir, REPORTING_WINDOWS)
    benchmark_execution = forward_returns(panel.fields['close'][['000300']], horizon=10, delay=1)['000300']
    portfolio_rows = []
    portfolio_details = []
    reporting_rows = []
    baseline = None
    for variant in VARIANTS:
        by_cost = {}
        for cost in (10, 20, 40):
            summary, periods, holdings = run_confidence_portfolio(validation_ledger, benchmark_execution, states, thresholds, variant, cost, VALIDATION_WINDOWS)
            by_cost[cost] = summary
            if cost == 20:
                leave_name, _, _ = run_confidence_portfolio(validation_ledger, benchmark_execution, states, thresholds, variant, cost, VALIDATION_WINDOWS, excluded_name=summary['top_name'])
                leave_sector, _, _ = run_confidence_portfolio(validation_ledger, benchmark_execution, states, thresholds, variant, cost, VALIDATION_WINDOWS, excluded_sector=summary['top_sector'])
                flat = {k: v for k, v in summary.items() if k != 'window_results'}
                flat['leave_one_name_relative_excess'] = leave_name['relative_excess']
                flat['leave_one_sector_relative_excess'] = leave_sector['relative_excess']
                portfolio_rows.append(flat)
                portfolio_details.append({'variant_id': variant.variant_id, 'window_results': summary['window_results'], 'periods': periods.to_dict('records'), 'holdings': holdings.to_dict('records')})
                if variant.variant_id == 'always_invested':
                    baseline = flat
        portfolio_rows[-1]['relative_excess_40bps'] = by_cost[40]['relative_excess']
        for window in REPORTING_WINDOWS:
            rep, _, _ = run_confidence_portfolio(reporting_ledger, benchmark_execution, states, thresholds, variant, 20, (window,))
            reporting_rows.append({'window': window, **{k: v for k, v in rep.items() if k != 'window_results'}})
    portfolios = pd.DataFrame(portfolio_rows)
    assert baseline is not None
    portfolios['support_gate_pass'] = (portfolios['positive_excess_windows'] >= 3) & (portfolios['relative_excess_40bps'] > 0) & (portfolios['leave_one_name_relative_excess'] > 0) & (portfolios['leave_one_sector_relative_excess'] > 0) & (portfolios['mean_exposure'] >= 0.45) & ((portfolios['max_drawdown'] >= baseline['max_drawdown'] + 0.02) | (portfolios['relative_excess'] >= baseline['relative_excess'] + 0.05)) & (portfolios['relative_excess'] >= baseline['relative_excess'] - 0.05)
    portfolios.loc[portfolios['variant_id'] == 'always_invested', 'support_gate_pass'] = False
    factors = build_discovery_factors(panel.fields, symbols, '000300')
    close = panel.fields['close'].loc[:, symbols]
    forward = stack_return_frame(forward_returns(close, horizon=10), 'forward_return')['forward_return']
    sector_map = {str(k): v['sector'] for k, v in classification.items()}
    sectors = pd.Series(index=forward.index, data=forward.index.get_level_values('instrument').map(sector_map))
    registry = {x['factor']: x for x in FACTOR_REGISTRY}
    factor_series = {}
    factor_meta = {}
    for name, wide in factors.items():
        if name not in REGIME_FACTOR_NAMES:
            continue
        raw = stack_wide(wide, name)
        for mode, series in (('global', raw), ('sector_relative', sector_relative_factor(raw, sectors))):
            fid = f'{name}__{mode}'
            factor_series[fid] = series
            factor_meta[fid] = {'factor': name, 'family': registry[name]['family'], 'mode': mode}
    calibration_factors, selected = select_state_factors(factor_series, factor_meta, forward, states)
    composite = build_regime_composite(factor_series, states, selected)
    baseline_score = pd.concat([validation_ledger, reporting_ledger], ignore_index=True).set_index(['datetime', 'instrument'])['score'].sort_index()
    factor_windows, factor_summary = validate_composite(composite, forward, baseline_score)
    state_validation = []
    daily = daily_state_factor_ic(composite, forward, states, '2024-01-01', '2025-12-31')
    for state, group in daily.groupby('state'):
        vals = group['rank_ic'].to_numpy(float)
        state_validation.append({'state': state, 'n_dates': len(vals), 'mean_rank_ic': float(vals.mean()), 'rank_icir': float(vals.mean() / vals.std(ddof=1)) if len(vals) > 1 and vals.std(ddof=1) > 0 else 0.0, 'positive_ratio': float((vals > 0).mean())})
    reporting_factor = []
    for window, (start, end) in REPORTING_WINDOWS.items():
        reporting_factor.append({'window': window, **factor_window_metrics(composite, forward, baseline_score, start, end)})
    confidence_supported = bool(portfolios['support_gate_pass'].any())
    regime_supported = bool(factor_summary['support_gate_pass'])
    decision = f"confidence_gate_{('supported' if confidence_supported else 'not_supported')}_regime_model_{('supported' if regime_supported else 'not_supported')}"
    identity = {'provider_identity_sha256': json.loads((provider_dir / 'provider_manifest.json').read_text())['provider_identity_sha256'], 'universe_sha256': sha(universe_path), 'classification_sha256': sha(class_path), 'calibration_thresholds': thresholds, 'research_only': True, 'trade_ready': False}
    decision_payload = {'decision': decision, 'confidence_gate_supported': confidence_supported, 'supported_confidence_variants': portfolios.loc[portfolios['support_gate_pass'], 'variant_id'].tolist(), 'regime_model_supported': regime_supported, 'regime_factor_summary': factor_summary, 'selected_state_factors': selected, 'research_only': True, 'trade_ready': False, 'creates_cn_x1_1_candidate': False}
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / 'execution_identity.json', identity)
    write_json(output_dir / 'decision.json', decision_payload)
    write_json(output_dir / 'selected_state_factors.json', selected)
    write_json(output_dir / 'portfolio_details.json', portfolio_details)
    write_csv(output_dir / 'confidence_portfolio_summary.csv', portfolios.sort_values(['support_gate_pass', 'relative_excess'], ascending=[False, False]))
    write_csv(output_dir / 'confidence_portfolio_reporting.csv', pd.DataFrame(reporting_rows))
    write_csv(output_dir / 'factor_state_calibration.csv', calibration_factors)
    write_csv(output_dir / 'regime_factor_window_summary.csv', factor_windows)
    write_csv(output_dir / 'regime_factor_state_validation.csv', pd.DataFrame(state_validation))
    write_csv(output_dir / 'regime_factor_reporting.csv', pd.DataFrame(reporting_factor))
    lines = ['# CN130 市场状态条件化与置信度现金机制实验报告', '', '> 2022–2023仅用于校准；2024–2025用于冻结验证；2026仅报告。', '', '## 最终裁决', '', f'- Decision: `{decision}`', f'- Confidence gate supported: {confidence_supported}', f'- Regime factor model supported: {regime_supported}', '- 不创建CN x1.1；`research_only=true`。', '', '## 校准阈值', '', f"- 第四行业固定得分阈值：{thresholds['fourth_sector_score_threshold']:.4f}", f"- Top4行业均值与行业中位数固定差值阈值：{thresholds['sector_gap_threshold']:.4f}", '', '## 置信度组合（20bps）', '', '| 方案 | 相对超额 | 最大回撤 | 正窗口 | 平均暴露 | 现金期占比 | 留一名称 | 留一行业 | 40bps超额 | Gate |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in portfolios.sort_values(['support_gate_pass', 'relative_excess'], ascending=[False, False]).itertuples(index=False):
        lines.append(f"| {r.variant_id} | {r.relative_excess:.2%} | {r.max_drawdown:.2%} | {r.positive_excess_windows}/4 | {r.mean_exposure:.1%} | {r.cash_period_ratio:.1%} | {r.leave_one_name_relative_excess:.2%} | {r.leave_one_sector_relative_excess:.2%} | {r.relative_excess_40bps:.2%} | {('PASS' if r.support_gate_pass else 'FAIL')} |")
    lines += ['', '## 市场状态条件化因子', '', f"- Mean Rank IC: {factor_summary['mean_window_rank_ic']:.4f}", f"- 正窗口：{factor_summary['positive_windows']}/4", f"- 最差窗口：{factor_summary['worst_window_rank_ic']:.4f}", f"- 增量Rank IC：{factor_summary['mean_incremental_rank_ic']:.4f}", f"- Mean Spread：{factor_summary['mean_top_bottom_spread']:.2%}", f"- Gate: {('PASS' if regime_supported else 'FAIL')}", '', '### 每个状态冻结因子']
    for state, rules in selected.items():
        lines.append(f'- {state}: ' + (', '.join((f"{x['factor_id']}({x['sign']:+d})" for x in rules)) or 'none'))
    lines += ['', '## 解释边界', '', '- 置信度阈值采用预注册固定定义，不使用验证期收益。', '- 因子方向、选择和权重仅来自2022–2023。', '- 当前静态池仍存在生存者偏差；PIT基本面与市值未覆盖。']
    (output_dir / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    files = [p for p in output_dir.rglob('*') if p.is_file() and p.name != 'evidence_manifest.json']
    write_json(output_dir / 'evidence_manifest.json', {'experiment_id': 'cn130_regime_confidence_v1', 'decision': decision_payload, 'files': [{'path': str(p.relative_to(output_dir)), 'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(files)]})
    print(json.dumps(clean(decision_payload), ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--provider-dir', type=Path, required=True)
    p.add_argument('--ledger-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    run(a.root.resolve(), a.provider_dir.resolve(), a.ledger_dir.resolve(), a.output_dir.resolve())


if __name__ == '__main__':
    main()
