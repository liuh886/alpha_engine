"""Physical, per-security audit for frozen P2 daily research inputs.

This is an inventory, not a readiness authority. Missing exchange sessions are
reported as unexplained unless a governed lifecycle rule accounts for them.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def inspect_security(payload: dict, sessions: list[str], requested_start: str,
                     cutoff: str, terminal_date: str | None = None) -> dict:
    bars = payload.get('bars', [])
    fields = ('open', 'high', 'low', 'close', 'volume')
    times = [str(row.get('time', row.get('date', ''))) for row in bars]
    valid = [row for row in bars if all(_finite(row.get(f)) for f in fields) and
             min(row[f] for f in fields[:4]) > 0 and row['volume'] >= 0]
    valid_dates = sorted({str(row.get('time', row.get('date', ''))) for row in valid})
    first, last = (valid_dates[0], valid_dates[-1]) if valid_dates else (None, None)
    expected_end = min(cutoff, terminal_date) if terminal_date else cutoff
    expected = [s for s in sessions if requested_start <= s <= expected_end]
    observed = set(valid_dates)
    interior = [s for s in expected if first and last and first <= s <= last and s not in observed]
    factors = {}
    for factor, rows in payload.get('factor_series', {}).items():
        finite_dates = [str(r.get('time', '')) for r in rows if _finite(r.get('value'))]
        factors[factor] = {'rows': len(rows), 'finite_rows': len(finite_dates),
                           'missing_or_nonfinite': len(rows) - len(finite_dates),
                           'first_valid': min(finite_dates, default=None),
                           'last_valid': max(finite_dates, default=None)}
    return {
        'symbol': str(payload['symbol']), 'roles': payload.get('roles', []),
        'row_count': len(bars), 'valid_ohlcv_rows': len(valid),
        'first_valid_session': first, 'last_valid_session': last,
        'null_or_nonfinite_by_field': {f: sum(not _finite(r.get(f)) for r in bars) for f in fields},
        'invalid_ohlcv_rows': len(bars) - len(valid),
        'ohlc_order_violations': sum(
            r['low'] > min(r['open'], r['close'], r['high']) + 1e-7 or
            r['high'] < max(r['open'], r['close'], r['low']) - 1e-7 for r in valid),
        'zero_volume_rows': sum(r.get('volume') == 0 for r in bars),
        'duplicate_dates': sorted(t for t, n in Counter(times).items() if n > 1),
        'dates_sorted': times == sorted(times),
        'non_session_dates': sorted(observed - set(sessions)),
        'beyond_cutoff_dates': [s for s in valid_dates if s > cutoff],
        'after_terminal_dates': [s for s in valid_dates if terminal_date and s > terminal_date],
        'missing_interior_sessions': interior,
        'missing_prefix_sessions': [s for s in expected if first and s < first],
        'missing_suffix_sessions': [s for s in expected if last and s > last],
        'prefix_classification': 'UNREVIEWED_LISTING_OR_SOURCE_EDITION_LIMIT',
        'terminal_date': terminal_date,
        'adjustment_factor_in_projection': any('factor' in r for r in bars),
        'factor_series': factors,
        'provider_manifest_sha256': payload.get('provider_manifest_sha256'),
        'source_csv_sha256': payload.get('source_csv_sha256'),
        'historical_completeness_certified': False,
    }


def audit_market(root: Path, catalog: dict) -> dict:
    import exchange_calendars as xc
    import yaml

    market = catalog['market']
    calendar_name = 'XNYS' if market == 'us' else 'XSHG'
    cal = xc.get_calendar(calendar_name, start=catalog['start'], end=catalog['cutoff'])
    sessions = [x.strftime('%Y-%m-%d') for x in cal.sessions]
    lifecycle_path = root / 'configs/data_quality/symbol_identity_and_lifecycle_v1.yaml'
    rules = yaml.safe_load(lifecycle_path.read_text(encoding='utf-8'))['rules'] if lifecycle_path.exists() else {}
    terminal = rules.get('terminal_listings', {})
    securities = []
    import json
    for record in catalog['symbols']:
        file = root / 'data/research/market_evidence' / market / record['path']
        payload = json.loads(file.read_text(encoding='utf-8'))
        symbol = str(record['symbol'])
        terminal_date = terminal.get(symbol, {}).get('terminal_date')
        detail = inspect_security(payload, sessions, catalog['start'], catalog['cutoff'], terminal_date)
        detail['projection_path'] = file.relative_to(root).as_posix()
        detail['projection_sha256'] = sha256(file)
        detail['projection_hash_verified'] = detail['projection_sha256'] == record.get('sha256')
        csv = root / 'data/csv_clean' / f'{symbol}.csv'
        detail['source_csv_local_status'] = 'NOT_SAVED_LOCALLY'
        if csv.is_file() and not csv.is_symlink():
            digest = sha256(csv)
            detail['local_csv_sha256'] = digest
            detail['source_csv_local_status'] = (
                'VERIFIED_SAME_EDITION' if digest == payload.get('source_csv_sha256')
                else 'DIFFERENT_LOCAL_EDITION')
        securities.append(detail)
    candidates = [s for s in securities if 'selected_pool_candidate' in s['roles']]
    return {
        'calendar': calendar_name, 'calendar_library_version': xc.__version__,
        'calendar_sessions': sessions, 'securities': securities,
        'candidate_ohlcv_symbols': sum(s['valid_ohlcv_rows'] > 0 for s in candidates),
        'earliest_observed_candidate': min(s['first_valid_session'] for s in candidates if s['first_valid_session']),
        'latest_observed_candidate': max(s['last_valid_session'] for s in candidates if s['last_valid_session']),
        'candidate_rows': sum(s['row_count'] for s in candidates),
        'symbols_with_interior_gaps': [s['symbol'] for s in candidates if s['missing_interior_sessions']],
        'symbols_with_prefix_limits': [s['symbol'] for s in candidates if s['missing_prefix_sessions']],
        'same_edition_source_csvs': sum(s['source_csv_local_status'] == 'VERIFIED_SAME_EDITION' for s in securities),
        'coverage_warning': 'Symbol presence does not certify complete history, tradability or PIT.',
    }
