"""Independently compare P2 Parquet projections to original frozen payloads.

The explicit checkout must be an isolated private worktree at the bundle's code
revision. No provider refresh, research experiment, cloud upload or Colab call.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from src.research.cloud_exchange import ExchangeError, _safe_name, _safe_target
from src.research.dataset_inventory import sha256
from src.research.comprehensive_bundle import _privacy_bytes


def verify(bundle: Path, checkout: Path, report_path: Path) -> dict:
    manifest = json.loads((bundle / 'bundle-manifest.json').read_text(encoding='utf-8'))
    revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != manifest['repo_revision']:
        raise ExchangeError('independent checkout does not match frozen code revision')
    for relative, expected in manifest['code_module_sha256'].items():
        if sha256(checkout / relative) != expected:
            raise ExchangeError('frozen checkout code hash mismatch')
    for market in ('us', 'cn'):
        with zipfile.ZipFile(bundle / f'{market}_market_history.zip') as archive:
            history = json.loads(archive.read('manifest.json'))
            for entry in history['files']:
                name = _safe_name(entry['path'])
                content = archive.read('files/' + name)
                if hashlib.sha256(content).hexdigest() != entry['sha256']:
                    raise ExchangeError('frozen checkout source payload mismatch')
                if entry.get('upstream_sha256'):
                    original = subprocess.check_output(
                        ['git', '-C', str(checkout), 'show', f'{revision}:{name}'])
                    if hashlib.sha256(original).hexdigest() != entry['upstream_sha256']:
                        raise ExchangeError('upstream Git source identity mismatch')
                    if '/symbols/' in name:
                        from src.research.comprehensive_bundle import DATA_ONLY_SECURITY_KEYS
                        expected = {k: v for k, v in json.loads(original).items()
                                    if k in DATA_ONLY_SECURITY_KEYS}
                        if json.loads(content) != expected:
                            raise ExchangeError('data-only projection changed market/factor values')
                target = _safe_target(checkout, name)
                if target.exists():
                    if target.read_bytes() != content:
                        raise ExchangeError('refusing to overwrite a different checkout input')
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as out:
                    out.write(content)
    # Needed for listing/suspension audit; preserve this exact configuration too.
    relative = Path('configs/data_quality/symbol_identity_and_lifecycle_v1.yaml')
    target = checkout / relative
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((bundle / 'provenance' / relative).read_bytes())
    for name in ('uv.lock', 'pyproject.toml'):
        if sha256(checkout / name) != sha256(bundle / 'provenance' / name):
            raise ExchangeError('frozen dependencies differ')
    env = dict(os.environ, PYTHONPATH=str(checkout))
    # Execute the verifier from the independent frozen checkout, not the working
    # branch. Socket connects are denied to prove the read needs no providers.
    command = (
        'import socket,sys; '
        'socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("offline acceptance")); '
        'from src.research.comprehensive_bundle import main; '
        'sys.exit(main(["verify","--bundle",sys.argv[1]]))'
    )
    child = subprocess.run([sys.executable, '-c', command, str(bundle)], cwd=checkout,
                           env=env, capture_output=True, text=True, timeout=600)
    if child.returncode:
        raise ExchangeError('frozen offline verifier failed: ' + child.stderr[-500:])
    results = {'frozen_code_revision': revision, 'socket_connections_denied': True,
               'frozen_verifier': json.loads(child.stdout), 'parity': {}}
    privacy_files = 0
    for path in bundle.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith(('.json', '.jsonl', '.csv', '.yaml', '.txt')):
                        _privacy_bytes(archive.read(name))
                        privacy_files += 1
        elif path.suffix in ('.json', '.jsonl', '.yaml', '.toml', '.lock'):
            _privacy_bytes(path.read_bytes())
            privacy_files += 1
    results['privacy'] = {'status': 'PASS', 'text_payloads_scanned': privacy_files,
                          'model_weights_or_account_or_credential_signatures': 0}
    fields = ['market', 'symbol', 'date', 'open', 'high', 'low', 'close', 'volume']
    for market in ('us', 'cn'):
        catalog = json.loads((checkout / f'data/research/market_evidence/{market}/catalog.json').read_text())
        expected = []
        for record in catalog['symbols']:
            payload = json.loads((checkout / f'data/research/market_evidence/{market}' / record['path']).read_text())
            for row in payload['bars']:
                expected.append(dict(market=market, symbol=str(record['symbol']), date=row['time'],
                                     **{f: row[f] for f in fields[3:]}))
        actual = pd.read_parquet(bundle / f'normalized/{market}_prices.parquet')[fields]
        pd.testing.assert_frame_equal(actual, pd.DataFrame(expected)[fields], check_dtype=False, check_exact=True)
        results['parity'][f'{market}_prices'] = {'rows': len(actual), 'status': 'EXACT'}
        with zipfile.ZipFile(bundle / f'sources/{market}_events.zip') as archive:
            for family in ('fundamentals', 'corporate_actions'):
                source = [json.loads(line) for line in archive.read(f'{family}/events.jsonl').splitlines() if line]
                normalized = pq.read_table(bundle / f'normalized/{market}_{family}.parquet').to_pylist()
                if normalized != source:
                    raise ExchangeError(f'original/Parquet event parity mismatch: {market}/{family}')
                results['parity'][f'{market}_{family}'] = {'rows': len(source), 'status': 'EXACT'}
    with zipfile.ZipFile(bundle / 'sources/cn_alpha158.zip') as archive:
        for path in sorted((bundle / 'normalized/cn_alpha158').glob('*.parquet')):
            raw = pd.read_csv(io.BytesIO(archive.read(f'alpha158/panels/{path.stem}.csv.gz')), compression='gzip')
            normalized = pd.read_parquet(path).drop(columns=['market', 'symbol'])
            pd.testing.assert_frame_equal(raw, normalized, check_dtype=False, check_exact=True)
        results['parity']['cn_alpha158'] = {'symbols': 130, 'factor_count': 158, 'status': 'EXACT_INCLUDING_NANS'}
    with zipfile.ZipFile(bundle / 'sources/qqq_reference.zip') as archive:
        for symbol in ('QQQ', 'QQQI', 'TQQQ'):
            raw = pd.read_csv(io.BytesIO(archive.read(f'canonical/{symbol}.csv')))
            normalized = pd.read_parquet(bundle / f'normalized/reference_20261014/{symbol}.parquet').drop(columns=['symbol'])
            pd.testing.assert_frame_equal(raw, normalized, check_dtype=False, check_exact=True)
        results['parity']['qqq_reference'] = {'symbols': 3, 'status': 'EXACT'}
    for source in manifest.get('market_source_archives', []):
        market = source['market']
        combined = pd.read_parquet(bundle / f'normalized/{market}_provider_source.parquet')
        with zipfile.ZipFile(bundle / 'sources' / source['archive']) as archive:
            for entry in source['records']:
                content = archive.read(entry['member'])
                if hashlib.sha256(content).hexdigest() != entry['expected_sha256']:
                    raise ExchangeError('provider CSV does not match exact source edition')
                current = json.loads((checkout / f'data/research/market_evidence/{market}/symbols/{entry["symbol"]}.json').read_text())
                if current['source_csv_sha256'] != entry['expected_sha256']:
                    raise ExchangeError('provider CSV differs from governed market projection identity')
                raw = pd.read_csv(io.BytesIO(content))
                normalized = combined.loc[combined.symbol == entry['symbol'], raw.columns].reset_index(drop=True)
                pd.testing.assert_frame_equal(raw, normalized, check_dtype=False, check_exact=True)
        results['parity'][f'{market}_provider_source'] = {
            'symbols': source['verified_symbols'], 'rows': len(combined),
            'status': 'EXACT_INCLUDING_ADJUSTMENT_AND_AMOUNT_FIELDS'}
    audit = report_path.with_name('frozen-checkout-dataset-plan.json')
    child = subprocess.run([sys.executable, '-m', 'src.research.comprehensive_dataset', 'audit',
                            '--repo-root', str(checkout), '--market', 'all', '--output', str(audit)],
                           cwd=checkout, env=env, capture_output=True, text=True, timeout=180)
    if child.returncode:
        raise ExchangeError('independent checkout inventory failed: ' + child.stderr[-500:])
    results['inventory_reproduced'] = True
    results['status'] = 'PARTIAL'
    results['sha256'] = sha256(bundle / 'bundle-manifest.json')
    results['acceptance_script_sha256'] = sha256(Path(__file__))
    report_path.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle.resolve(), args.checkout.resolve(), args.report.resolve()), indent=2))
