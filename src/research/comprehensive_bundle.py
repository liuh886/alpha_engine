"""Build and verify local-only, source-bound P2 multi-domain research bundles.

Raw archives are retained once. Parquet is a disposable analytical projection;
original manifests, source editions, missingness and availability are preserved.
This module never grants cloud-copy rights, uploads, or certifies PIT.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from src.research.cloud_exchange import ExchangeError, _git_head, _safe_name
from src.research.comprehensive_dataset import plan
from src.research.dataset_inventory import sha256
from src.research.source_archive_recovery import ALLOWED, RECEIPT, _source_plan, verify_archive

VERSION = 'p2_local_research_bundle_v1'
HISTORY_VERSION = 'p2_local_market_history_v1'
DATA_ONLY_SECURITY_KEYS = frozenset((
    'schema_version', 'evidence_type', 'market', 'symbol', 'instrument_id', 'provider_symbol',
    'roles', 'start', 'cutoff', 'provider_manifest_sha256', 'source_csv_sha256',
    'bars', 'factor_series', 'factor_series_scope', 'research_only', 'trade_ready',
))


def _data_only_security(payload: dict) -> dict:
    """A market source may also serve UI model markers; those never enter P2."""
    return {key: value for key, value in payload.items() if key in DATA_ONLY_SECURITY_KEYS}


def repair_cn_gaps(root: Path, destination: Path) -> dict:
    """Acquire only declared missing symbols into a separate, non-promoted edition."""
    import yaml
    from src.data.cn_selected_pool_event_sources import populate_cn_selected_pool_event_sources

    root, destination = root.resolve(), destination.resolve()
    if destination.is_relative_to(root):
        raise ExchangeError('supplemental source data must remain outside the public repository')
    component = json.loads((root / 'data/research/model_data_bundle_v1/sources/cn_events/fundamentals/component_manifest.json').read_text())
    symbols = component['missing_symbols']
    if any((destination / str(symbol) / 'receipt.json').exists() for symbol in symbols):
        raise ExchangeError('supplement edition exists; refuse to overwrite acquisition evidence')
    contract = yaml.safe_load((root / 'configs/data/selected_pool_event_population_v1.yaml').read_text(encoding='utf-8'))
    result = populate_cn_selected_pool_event_sources(
        symbols, contract['fundamental_fields']['cn'], datetime.now(timezone.utc).isoformat(),
        start_date='2021-01-01', end_date=component['evidence_cutoff'],
        source_cache_root=destination / 'source_cache', progress=lambda _: None,
    )
    records = []
    for symbol in symbols:
        population = result.fundamentals[symbol]
        rows = [asdict(event) for event in population.events
                if str(event.available_at)[:10] <= component['evidence_cutoff']]
        target = destination / symbol
        target.mkdir(parents=True, exist_ok=True)
        with (target / 'events.jsonl').open('x', encoding='utf-8', newline='\n') as out:
            for row in rows:
                out.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n')
        receipt = {'symbol': symbol, 'status': population.status, 'error': population.error,
                   'event_count': len(rows), 'source_reuse': result.source_reuse,
                   'source_cutoff': component['evidence_cutoff'],
                   'original_archive_modified': False, 'pit_certified': False,
                   'research_only': True, 'trade_ready': False}
        _write_json(target / 'receipt.json', receipt)
        records.append({k: receipt[k] for k in ('symbol', 'status', 'event_count', 'error')})
    return {'supplements': records, 'canonical_registry_modified': False}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or '\\' in value or ':' in value or path.is_absolute() or
            any(p in ('', '.', '..') for p in value.split('/'))):
        raise ExchangeError('unsafe bundle member path')
    return value


def _file(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
        raise ExchangeError(f'missing or unsafe bundle file: {relative}')
    return path


def _entry(root: Path, path: Path, role: str) -> dict:
    return {'path': path.relative_to(root).as_posix(), 'size_bytes': path.stat().st_size,
            'sha256': sha256(path), 'role': role}


def local_history_pack(root: Path, market: str, target: Path) -> dict:
    """Preserve all retained history without implying permission for a cloud copy."""
    root, target = root.resolve(), target.resolve()
    if target.is_relative_to(root):
        raise ExchangeError('local market archive must be outside the public repository')
    report = plan(root, market)
    item = report['markets'][0]
    if item['market_history_status'] != 'READY_FOR_RIGHTS_REVIEW':
        raise ExchangeError('market history hash/roster verification failed')
    entries = [dict(entry) for entry in item['files']]
    catalog_path = f'data/research/market_evidence/{market}/catalog.json'
    catalog = json.loads((root / catalog_path).read_text(encoding='utf-8'))
    transformed = {}
    upstream_hashes = {}
    for record in catalog['symbols']:
        name = f'data/research/market_evidence/{market}/' + record['path']
        payload = json.loads((root / name).read_text(encoding='utf-8'))
        data = json.dumps(_data_only_security(payload), sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode() + b'\n'
        transformed[name] = data
        record['upstream_projection_sha256'] = record.get('upstream_projection_sha256', record['sha256'])
        upstream_hashes[name] = record['upstream_projection_sha256']
        record['sha256'] = hashlib.sha256(data).hexdigest()
    catalog['p2_data_only_projection'] = True
    catalog['upstream_catalog_sha256'] = catalog.get('upstream_catalog_sha256', sha256(root / catalog_path))
    upstream_hashes[catalog_path] = catalog['upstream_catalog_sha256']
    transformed[catalog_path] = json.dumps(catalog, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode() + b'\n'
    for entry in entries:
        if entry['path'] in transformed:
            entry['upstream_sha256'] = upstream_hashes[entry['path']]
            entry['sha256'] = hashlib.sha256(transformed[entry['path']]).hexdigest()
            entry['size'] = len(transformed[entry['path']])
    manifest = {
        'schema_version': HISTORY_VERSION, 'market': market, 'pool_id': item['pool_id'],
        'repo_revision': report['source_repository_revision'], 'data_cutoff': item['source_cutoff'],
        'candidate_count': item['candidate_symbol_count'], 'reference_symbols': item['reference_symbols'],
        'research_only': True, 'trade_ready': False, 'pit_certified': False,
        'transfer_scope': 'local_only', 'owner_approved_private_cloud_copy': False,
        'rights_class': 'UNREVIEWED_FOR_CLOUD_COPY',
        'history_scope': 'all_retained_projection_rows_not_certified_listing_history',
        'data_only': True, 'model_events_and_weights_included': False,
        'upstream_catalog_sha256': catalog['upstream_catalog_sha256'],
        'files': entries,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            created = True
            payload = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\n'
            info = zipfile.ZipInfo('manifest.json', (1980, 1, 1, 0, 0, 0))
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED)
            for entry in entries:
                name = _safe_name(entry['path'])
                info = zipfile.ZipInfo('files/' + name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                if name in transformed:
                    archive.writestr(info, transformed[name])
                    continue
                with (root / name).open('rb') as src, archive.open(info, 'w') as dst:
                    shutil.copyfileobj(src, dst)
        verify_local_history(target)
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise
    return {'path': str(target), 'sha256': sha256(target), 'size_bytes': target.stat().st_size,
            'transfer_scope': 'local_only', 'cloud_copy_approved': False}


def verify_local_history(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 300:
            raise ExchangeError('invalid local history archive members')
        manifest = json.loads(archive.read('manifest.json'))
        if (manifest.get('schema_version') != HISTORY_VERSION or
                manifest.get('transfer_scope') != 'local_only' or
                manifest.get('owner_approved_private_cloud_copy') is not False or
                manifest.get('research_only') is not True or
                manifest.get('data_only') is not True or
                manifest.get('model_events_and_weights_included') is not False or
                manifest.get('trade_ready') is not False or manifest.get('pit_certified') is not False):
            raise ExchangeError('invalid local-only history boundary')
        expected = {'manifest.json'}
        for entry in manifest['files']:
            name = 'files/' + _safe_name(entry['path'])
            expected.add(name)
            info = archive.getinfo(name)
            if info.file_size != entry['size']:
                raise ExchangeError('local history member size mismatch')
            with archive.open(name) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != entry['sha256']:
                raise ExchangeError('local history member SHA mismatch')
        if set(names) != expected:
            raise ExchangeError('unexpected local history member')
        import yaml
        pool_files = [f for f in manifest['files'] if f['role'] == 'pool_spec']
        catalogs = [f for f in manifest['files'] if f['role'] == 'source_manifest']
        if len(pool_files) != 1 or len(catalogs) != 1:
            raise ExchangeError('local history pool/catalog authority missing')
        pool = yaml.safe_load(archive.read('files/' + pool_files[0]['path']))
        catalog = json.loads(archive.read('files/' + catalogs[0]['path']))
        candidates = {str(r['symbol']) for r in catalog['symbols']
                      if 'selected_pool_candidate' in r['roles']}
        expected_count = 87 if manifest['market'] == 'us' else 130
        if (manifest['market'] not in ('us', 'cn') or len(candidates) != expected_count or
                candidates != set(map(str, pool['symbols'])) or
                manifest['pool_id'] != pool['pool_id'] or catalog['pool_id'] != pool['pool_id'] or
                manifest['candidate_count'] != expected_count or
                catalog['cutoff'] != manifest['data_cutoff']):
            raise ExchangeError('local history frozen roster/identity mismatch')
        symbol_files = {'files/data/research/market_evidence/' + manifest['market'] + '/' + r['path']
                        for r in catalog['symbols']}
        if not symbol_files.issubset(expected):
            raise ExchangeError('catalog security payload missing')
        for name in symbol_files:
            payload = json.loads(archive.read(name))
            if set(payload) - DATA_ONLY_SECURITY_KEYS:
                raise ExchangeError('unexpected non-data fields in P2 security payload')
            _privacy_bytes(archive.read(name))
    return manifest


def inventory_archive(path: Path, record: dict, authority: dict) -> dict:
    verified = verify_archive(path, record)
    verified.pop('path')
    members = []
    bindings = []
    with zipfile.ZipFile(path) as archive:
        member_hashes = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = _relative(info.filename)
            with archive.open(info) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            member_hashes[name] = digest
            members.append({'path': name, 'size_bytes': info.file_size, 'sha256': digest})
        for binding in authority.get('component_manifests', []):
            if member_hashes.get(binding['path']) != binding['sha256']:
                raise ExchangeError(f"anchored component SHA mismatch: {binding['path']}")
            bindings.append(binding)
            component = json.loads(archive.read(binding['path']))
            base = PurePosixPath(binding['path']).parent
            files = component.get('files', {})
            pairs = (files.items() if isinstance(files, dict) else
                     ((entry['path'], entry['sha256']) for entry in files))
            for name, digest in pairs:
                candidate = str(base / name) if str(base) != '.' else name
                if member_hashes.get(candidate) != digest:
                    raise ExchangeError(f'inner component file SHA mismatch: {candidate}')
            if component.get('catalog_sha256'):
                candidate = str(base / 'factor_catalog.json')
                if member_hashes.get(candidate) != component['catalog_sha256']:
                    raise ExchangeError('factor catalog SHA mismatch')
            for kind in ('events', 'coverage'):
                details = component.get('details', {})
                expected = details.get(f'{kind}_sha256')
                if expected and member_hashes.get(details[f'{kind}_path']) != expected:
                    raise ExchangeError(f'event/coverage payload SHA mismatch: {kind}')
    return {**verified, 'cutoff': record['cutoff'], 'members': members,
            'component_bindings': bindings, 'original_payload_bytes_verified': True}


def _parquet(path: Path, rows: list[dict]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not rows:
        raise ExchangeError('refusing to create an empty data component')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ExchangeError('immutable Parquet already exists')
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression='zstd', version='2.6')


def _event_component(archive_path: Path, family: str, output: Path, market: str) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(f'{family}/events.jsonl') as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
        coverage = json.loads(archive.read(f'{family}/coverage.json'))
        manifest = json.loads(archive.read(f'{family}/component_manifest.json'))
    if any(r.get('market') != market for r in rows):
        raise ExchangeError('cross-market event payload')
    counts = Counter(str(r['symbol']) for r in rows)
    for item in coverage:
        if counts[str(item['symbol'])] != item['event_count']:
            raise ExchangeError('event count does not match authoritative symbol coverage')
    _parquet(output, rows)
    time_fields = ('reported_at', 'available_at', 'retrieved_at') if family == 'fundamentals' else (
        'announced_at', 'ex_date', 'effective_date', 'pay_date', 'retrieved_at')
    return {
        'market': market, 'family': family, 'event_count': len(rows),
        'payload_symbols': len(counts), 'coverage': coverage,
        'original_status': manifest['status'], 'original_ready_symbols': manifest['ready_symbol_count'],
        'time_fields': {f: {'nonempty': sum(bool(r.get(f)) for r in rows),
                             'first': min((str(r[f]) for r in rows if r.get(f)), default=None),
                             'last': max((str(r[f]) for r in rows if r.get(f)), default=None)}
                        for f in time_fields},
        'fields_or_event_types': dict(Counter(str(r.get('field', r.get('event_type'))) for r in rows)),
        'availability_note': 'retrieved_at is retrospective; availability fields do not certify source vintage',
        'pit_certified': False,
    }


def _normalize_alpha(archive_path: Path, output: Path) -> dict:
    import pandas as pd
    import pyarrow.parquet as pq

    symbols = []
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('alpha158/factor_panel_manifest.json'))
        quality = pd.read_csv(io.BytesIO(archive.read('alpha158/factor_quality.csv.gz')),
                              compression='gzip', dtype={'symbol': str})
        for name in sorted(archive.namelist()):
            if not name.startswith('alpha158/panels/') or not name.endswith('.csv.gz'):
                continue
            symbol = PurePosixPath(name).name.removesuffix('.csv.gz')
            frame = pd.read_csv(io.BytesIO(archive.read(name)), compression='gzip')
            features = [c for c in frame if c != 'date']
            if len(features) != 158:
                raise ExchangeError('Alpha158 feature count mismatch')
            frame = frame.copy()
            frame.insert(0, 'symbol', symbol)
            frame.insert(0, 'market', 'cn')
            target = output / f'{symbol}.parquet'
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, engine='pyarrow', compression='zstd', index=False)
            q = quality[quality.symbol == symbol]
            symbols.append({'symbol': symbol, 'rows': len(frame),
                            'ready_factors': int((q.status == 'ready').sum()),
                            'blocked_factors': q[q.status != 'ready'][
                                ['factor_id', 'status', 'reasons', 'source_available_rows',
                                 'eligible_rows', 'finite_rows']].fillna('').to_dict('records'),
                            'null_values': int(frame[features].isna().sum().sum()),
                            'readback_rows': pq.read_metadata(target).num_rows})
    return {'family': 'qlib_alpha158', 'market': 'cn', 'factor_count': 158,
            'symbols_with_payload': len(symbols), 'original_ready_symbols': manifest['ready_symbol_count'],
            'original_status': manifest['status'], 'cutoff': manifest['evidence_cutoff'],
            'not_yet_applicable_symbols': manifest.get('not_yet_applicable_symbols', []),
            'source_field_semantics': manifest.get('source_role', {}).get('field_semantics', {}),
            'quality_policy': manifest['quality_policy'], 'symbols': symbols}


def _normalize_reference(archive_path: Path, output: Path) -> dict:
    import pandas as pd

    records = []
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('bundle_manifest.json'))
        for symbol in manifest['symbols']:
            frame = pd.read_csv(io.BytesIO(archive.read(f'canonical/{symbol}.csv')))
            frame.insert(0, 'symbol', symbol)
            target = output / f'{symbol}.parquet'
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, engine='pyarrow', compression='zstd', index=False)
            records.append({'symbol': symbol, 'rows': len(frame), 'columns': frame.columns.tolist(),
                            'first_date': str(frame.iloc[0]['date']),
                            'last_date': str(frame.iloc[-1]['date'])})
        action_headers_only = all(len(archive.read(f'corporate_actions/{s}.csv').splitlines()) <= 1
                                  for s in manifest['symbols'])
    return {'family': 'qqq_reference', 'market': 'us', 'symbols': records,
            'source_policy': manifest['source_policy'], 'limitations': manifest['limitations'],
            'corporate_actions_headers_only': action_headers_only,
            'professional_source_ready': manifest['professional_source_ready'],
            'source_edition_kept_separate_from_market_history': True}


def _reference_comparison(output: Path) -> list[dict]:
    import pandas as pd

    prices = pd.read_parquet(output / 'normalized/us_prices.parquet')
    records = []
    for symbol in ('QQQ', 'QQQI', 'TQQQ'):
        reference = pd.read_parquet(output / f'normalized/reference_20261014/{symbol}.parquet')
        current = prices[prices.symbol == symbol].set_index('date')
        previous = reference.set_index('date')
        common = sorted(set(current.index) & set(previous.index))
        a = current.loc[common, 'close']
        b = previous.loc[common, 'close']
        ratio = a / b
        differences = (a.pct_change(fill_method=None) - b.pct_change(fill_method=None)).abs().dropna()
        records.append({'symbol': symbol, 'common_sessions': len(common),
                        'first_common': min(common, default=None), 'last_common': max(common, default=None),
                        'market_close_to_reference_ratio_min': float(ratio.min()),
                        'market_close_to_reference_ratio_max': float(ratio.max()),
                        'max_abs_daily_return_difference': float(differences.max()),
                        'same_close_values': bool(((a - b).abs() <= 1e-9).all()),
                        'compatibility': 'SEPARATE_EDITIONS_DO_NOT_AUTO_MERGE',
                        'calendar_scope': 'observed_common_sessions_only_no_fills'})
    return records


def _privacy_bytes(content: bytes) -> None:
    # Only explicitly selected research files enter the bundle. Scan names and
    # textual credential signatures as a second boundary; do not copy whole trees.
    import re
    patterns = (rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY',
                rb'\bgh[pousr]_[A-Za-z0-9]{25,}', rb'\bgithub_pat_[A-Za-z0-9_]{20,}',
                rb'\bAIza[A-Za-z0-9_-]{30,}')
    patterns += (rb'"(?:target_weight|previous_weight|weight_delta|formal_model_events|current_target|positions|holdings)"\s*:',
                 rb'"(?:api_key|access_token|refresh_token|password|secret)"\s*:\s*"[^"]+"')
    if any(re.search(p, content) for p in patterns):
        raise ExchangeError('credential or model/account signal signature in input')


def _privacy_check(path: Path) -> None:
    _privacy_bytes(path.read_bytes())


def build_local(root: Path, archive_root: Path, output: Path,
                supplement_root: Path | None = None) -> dict:
    root, archive_root, output = root.resolve(), archive_root.resolve(), output.resolve()
    if output.is_relative_to(root) or archive_root.is_relative_to(root):
        raise ExchangeError('all physical datasets must remain outside the public repository')
    if output.exists():
        raise ExchangeError('bundle destination already exists; choose a new immutable version')
    report = plan(root, detailed=True)
    authorities = json.loads((root / RECEIPT).read_text(encoding='utf-8'))
    authority_by_id = {s['source_id']: s for s in authorities['sources']}
    sources = _source_plan(root)
    inventories = {sid: inventory_archive(archive_root / rec['local_filename'], rec,
                                         authority_by_id[sid]) for sid, rec in sources.items()}
    output.mkdir(parents=True)
    components = []
    for market in ('us', 'cn'):
        item = next(m for m in report['markets'] if m['market'] == market)
        history = output / f'{market}_market_history.zip'
        local_history_pack(root, market, history)
        rows = []
        catalog = json.loads((root / f'data/research/market_evidence/{market}/catalog.json').read_text())
        price_manifest = json.loads((root / f'data/research/model_data_bundle_v1/components/{market}-selected-pool-prices.json').read_text())
        for rec in catalog['symbols']:
            payload = json.loads((root / f'data/research/market_evidence/{market}' / rec['path']).read_text())
            for bar in payload['bars']:
                rows.append({'market': market, 'symbol': str(rec['symbol']),
                             'date': bar['time'], **{k: bar[k] for k in ('open', 'high', 'low', 'close', 'volume')},
                             'provider': price_manifest['selected_providers'].get(str(rec['symbol'])),
                             'source_manifest_sha256': catalog['provider_manifest_sha256']})
        _parquet(output / 'normalized' / f'{market}_prices.parquet', rows)
        components.append({'market': market, 'family': 'market_history', 'rows': len(rows),
                           'candidate_count': item['candidate_symbol_count'],
                           'reference_symbols': item['reference_symbols'], 'cutoff': item['source_cutoff'],
                           'price_role': 'published_provider_adjusted_ohlcv_exact_edition',
                           'raw_price_and_adjustment_factors_in_projection': False,
                           'provider_identity_sha256': catalog['provider_identity_sha256'],
                           'retained_input_inventory': item['physical_inventory']})
    for sid, record in sources.items():
        original = archive_root / record['local_filename']
        target = output / 'sources' / record['local_filename']
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(original, target)
        except OSError:
            shutil.copyfile(original, target)
        if sid in ('us_events', 'cn_events'):
            for family in ('fundamentals', 'corporate_actions'):
                components.append(_event_component(original, family,
                    output / 'normalized' / f"{record['market']}_{family}.parquet", record['market']))
        elif sid == 'cn_alpha158':
            components.append(_normalize_alpha(original, output / 'normalized/cn_alpha158'))
        elif sid == 'qqq_reference':
            components.append(_normalize_reference(original, output / 'normalized/reference_20261014'))
    supplements = []
    if supplement_root:
        for symbol in ('301309', '301666', '600276'):
            source = supplement_root / symbol / 'receipt.json'
            if not source.exists():
                continue
            receipt = json.loads(source.read_text(encoding='utf-8'))
            event_source = supplement_root / symbol / 'events.jsonl'
            rows = [json.loads(line) for line in event_source.read_text(encoding='utf-8').splitlines() if line]
            if any(str(r.get('symbol')) != symbol or r.get('market') != 'cn' or
                   str(r.get('available_at', ''))[:10] > '2026-09-04' for r in rows):
                raise ExchangeError('supplement identity/availability mismatch')
            target_dir = output / 'supplements' / symbol
            target_dir.mkdir(parents=True)
            shutil.copyfile(source, target_dir / 'receipt.json')
            shutil.copyfile(event_source, target_dir / 'events.jsonl')
            if rows:
                _parquet(target_dir / 'events.parquet', rows)
            supplements.append({'symbol': symbol, 'status': receipt['status'],
                                'events': len(rows), 'original_source_sha_unchanged': True,
                                'new_retrieval_not_original_vintage': True})
        cache = supplement_root / 'source_cache'
        if cache.exists():
            for source in sorted(cache.rglob('*')):
                if not source.is_file() or source.is_symlink():
                    continue
                relative = source.relative_to(cache)
                if not set(relative.parts) & {'301309', '301666', '600276'}:
                    raise ExchangeError('unexpected supplemental source-cache symbol')
                dest = output / 'supplements/source_cache' / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
    # Preserve frozen configuration bytes and dependency versions beside archives.
    cfgs = [RECEIPT, Path('uv.lock'), Path('pyproject.toml'),
            Path('configs/data/selected_pool_event_population_v1.yaml'),
            Path('configs/data/alpha158_panel_v1.yaml'),
            Path('configs/data_quality/symbol_identity_and_lifecycle_v1.yaml'),
            Path('configs/providers/us_selected_equities_sec_cik_v3.yaml'),
            Path('configs/data/qqqi_qqq_tqqq_reference_research_v2.yaml')]
    for relative in cfgs:
        source = root / relative
        if not source.is_file():
            raise ExchangeError(f'missing pinned configuration: {relative}')
        dest = output / 'provenance' / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    _write_json(output / 'reports/dataset-plan.json', report)
    _write_json(output / 'reports/archive-inventory.json', inventories)
    _write_json(output / 'reports/component-coverage.json', components)
    _write_json(output / 'reports/supplement-coverage.json', supplements)
    _write_json(output / 'reports/reference-edition-comparison.json', _reference_comparison(output))
    gaps = [
        {'market': 'us', 'family': 'fundamentals', 'symbol': 'SBGSY',
         'class': 'SOURCE_NOT_SUPPORTED', 'detail': 'Reviewed identity exception: no SEC registrant Companyfacts; no CIK invented.'},
        {'market': 'cn', 'family': 'qlib_alpha158', 'symbol': '301666',
         'class': 'SOURCE_EDITION_INSUFFICIENT_LOOKBACK',
         'detail': 'Payload exists; factor-quality report preserves per-factor warmup and finite-row failures.'},
        {'family': 'market_history', 'class': 'RAW_CSV_EDITION_NOT_RECOVERED',
         'detail': 'Daily projections are real OHLCV bytes; local CSVs are older or absent. Raw/adjustment factors are not inferred.'},
        {'family': 'references', 'class': 'SOURCE_EDITION_AND_ADJUSTMENT_DIFFER',
         'detail': '2026-10-14 reference source and 2026-11-03 market projections stay separate; no blind join.'},
        {'family': 'rights', 'class': 'CLOUD_COPY_NOT_APPROVED',
         'detail': 'No per-source private cloud-copy proof has been attached; local build is not approval.'},
    ]
    for item in supplements:
        if item['status'] != 'ready' or not item['events']:
            gaps.append({'market': 'cn', 'family': 'fundamentals', 'symbol': item['symbol'],
                         'class': 'PROVIDER_MISSING', 'detail': 'See separate supplemental acquisition receipt.'})
    for item in report['markets']:
        inventory = item['physical_inventory']
        gaps.append({'market': item['market'], 'family': 'market_history',
                     'class': 'UNREVIEWED_PREFIX_HISTORY_LIMITS',
                     'symbols': inventory['symbols_with_prefix_limits'],
                     'detail': 'Separate actual listing dates from this source edition first rows; no backfill inferred.'})
        if inventory['symbols_with_interior_gaps']:
            gaps.append({'market': item['market'], 'family': 'market_history',
                         'class': 'UNEXPLAINED_INTERIOR_SESSION_GAPS',
                         'symbols': inventory['symbols_with_interior_gaps'],
                         'detail': 'May include suspension or provider gaps; exact missing dates are retained.'})
    _write_json(output / 'reports/gaps.json', gaps)
    all_files = sorted(p for p in output.rglob('*') if p.is_file())
    for path in all_files:
        if path.suffix in ('.json', '.jsonl', '.yaml', '.toml', '.lock'):
            _privacy_check(path)
    manifest = {'schema_version': VERSION, 'repo_revision': _git_head(root),
                'code_module_sha256': {p: sha256(root / p) for p in (
                    'src/research/comprehensive_bundle.py', 'src/research/comprehensive_dataset.py',
                    'src/research/dataset_inventory.py', 'src/research/source_archive_recovery.py',
                    'src/data/fundamentals/ashare_public_financials.py')},
                'research_only': True, 'trade_ready': False, 'pit_certified': False,
                'status': 'PARTIAL', 'transfer_scope': 'local_only',
                'owner_approved_private_cloud_copy': False,
                'cloud_copy_status': 'BLOCKED_PENDING_SOURCE_RIGHTS_AND_REMOTE_ACL',
                'colab_executed': False, 'source_archives': inventories,
                'supplements': supplements, 'gaps': gaps,
                'files': [_entry(output, p, 'original_source' if p.parent.name == 'sources' else 'research_component')
                          for p in all_files]}
    _write_json(output / 'bundle-manifest.json', manifest)
    return verify_bundle(output)


def verify_bundle(root: Path) -> dict:
    import pyarrow.parquet as pq

    root = root.resolve()
    manifest = json.loads(_file(root, 'bundle-manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('schema_version') != VERSION or manifest.get('research_only') is not True or
            manifest.get('trade_ready') is not False or manifest.get('pit_certified') is not False or
            manifest.get('transfer_scope') != 'local_only' or
            manifest.get('owner_approved_private_cloud_copy') is not False or
            manifest.get('status') != 'PARTIAL'):
        raise ExchangeError('invalid local dataset boundary')
    paths = [e['path'] for e in manifest['files']]
    if len(paths) != len(set(paths)):
        raise ExchangeError('duplicate aggregate manifest paths')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(paths) | {'bundle-manifest.json'}:
        raise ExchangeError('unlisted or missing bundle files')
    rows = 0
    for entry in manifest['files']:
        path = _file(root, entry['path'])
        if path.stat().st_size != entry['size_bytes'] or sha256(path) != entry['sha256']:
            raise ExchangeError(f"bundle SHA/size mismatch: {entry['path']}")
        if path.suffix == '.parquet':
            # Read all column pages, not just metadata, with no provider/network.
            table = pq.read_table(path)
            rows += table.num_rows
        if path.name in ('us_market_history.zip', 'cn_market_history.zip'):
            history = verify_local_history(path)
            if history['candidate_count'] != (87 if history['market'] == 'us' else 130):
                raise ExchangeError('frozen pool count mismatch')
    receipt = json.loads(_file(root, 'provenance/' + RECEIPT.as_posix()).read_text(encoding='utf-8'))
    by_id = {s['source_id']: s for s in receipt['sources']}
    if set(manifest['source_archives']) != ALLOWED:
        raise ExchangeError('all four frozen original source archives are mandatory')
    for sid, record in manifest['source_archives'].items():
        path = _file(root, f'sources/{sid}.zip')
        if 'sha256:' + sha256(path) != by_id[sid]['artifact_digest']:
            raise ExchangeError('aggregate source differs from frozen authority')
        checked = inventory_archive(path, {**record, 'local_filename': path.name}, by_id[sid])
        if checked != record:
            raise ExchangeError('archive member inventory changed')
    return {'status': 'PARTIAL', 'integrity': 'PASS', 'offline_read': 'PASS',
            'files': len(paths) + 1, 'total_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
            'parquet_rows_read': rows, 'original_archives_verified': len(manifest['source_archives']),
            'manifest_sha256': sha256(root / 'bundle-manifest.json'),
            'cloud_copy_approved': False, 'colab_executed': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('build-local')
    create.add_argument('--repo-root', type=Path, default=Path('.'))
    create.add_argument('--archive-root', type=Path, required=True)
    create.add_argument('--output-dir', type=Path, required=True)
    create.add_argument('--supplement-root', type=Path)
    check = sub.add_parser('verify')
    check.add_argument('--bundle', type=Path, required=True)
    repair = sub.add_parser('repair-cn-gaps')
    repair.add_argument('--repo-root', type=Path, default=Path('.'))
    repair.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'build-local':
            result = build_local(args.repo_root, args.archive_root, args.output_dir, args.supplement_root)
        elif args.action == 'repair-cn-gaps':
            result = repair_cn_gaps(args.repo_root, args.destination)
        else:
            result = verify_bundle(args.bundle)
        print(json.dumps(result, indent=2))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f'BLOCKED_LOCAL_DATASET: {exc}', file=sys.stderr)
        return 10


if __name__ == '__main__':
    raise SystemExit(main())
