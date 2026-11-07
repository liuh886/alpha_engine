"""Bind physical P2 inputs to the existing model-data readiness contract.

This is a consumer projection. It does not create thresholds, substitute sources,
register strategies, certify PIT or approve training/Colab execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import tempfile
import zipfile
from dataclasses import replace

from src.data.model_data_bundle import (
    ComponentSpec, DataComponent, evaluate_training_profile, normalize_component,
)
from src.research.cloud_exchange import ExchangeError
from src.research.dataset_inventory import sha256

CONTRACT = 'configs/data_contracts/model_data_bundle_v1.yaml'


def evaluate_profiles(
    contract: Mapping[str, Any], components: Mapping[str, DataComponent],
    payloads: Mapping[str, dict], *, root: Path, evidence_cutoff: str,
    selected_pool_ids: set[str], references: Mapping[str, set[str]],
) -> dict:
    """Reuse governed gates, adding proof that their declared inputs really exist."""
    import yaml

    registry = yaml.safe_load((root / 'configs/pools/reference_instrument_registry_v1.yaml').read_text())
    aliases: dict[str, dict[str, str]] = {}
    for market, market_config in registry.get('markets', {}).items():
        aliases[market] = {}
        for name, record in market_config.get('instruments', {}).items():
            canonical = record['canonical_symbol']
            for alias in [name, canonical, *record.get('provider_aliases', [])]:
                aliases[market][str(alias)] = canonical
    rows = []
    for profile_id, profile in sorted(contract['profiles'].items()):
        if profile.get('candidate_pool_id') not in selected_pool_ids:
            continue
        result = evaluate_training_profile(profile_id, profile, components,
                                           root=root, evidence_cutoff=evidence_cutoff)
        failures = list(result['failed_gates'])
        cutoffs = {}
        evidence = []
        for requirement in result['required_components']:
            component_id = requirement['component_id']
            component = components.get(component_id)
            proof = payloads.get(component_id)
            if component is not None:
                cutoffs[component_id] = component.evidence_cutoff
                if component.expected_symbol_count != result['candidate_count']:
                    failures.append(f'payload:{component_id}:candidate_count_mismatch')
                if not proof or proof.get('status') != 'VERIFIED':
                    failures.append(f'payload:{component_id}:physical_payload_not_verified')
                elif proof.get('manifest_sha256') != component.manifest_sha256:
                    failures.append(f'payload:{component_id}:source_manifest_hash_mismatch')
            evidence.append({'component_id': component_id, 'physical_payload': proof})
        market = result['market']
        canonical = aliases.get(market, {})
        present = {canonical.get(r, r) for r in references.get(market, set())}
        for reference in result['references']:
            if canonical.get(reference, reference) not in present:
                failures.append(f'reference:{reference}:physical_price_payload_missing')
        result.update(
            contract_gate_status=result['status'],
            status='blocked' if failures else 'ready', failed_gates=failures,
            physical_evidence=evidence, source_cutoffs=cutoffs,
            earliest_required_source_cutoff=min((v for v in cutoffs.values() if v), default=None),
            evaluation_cutoff=evidence_cutoff,
            readiness_scope='existing_contract_coverage_and_verified_physical_payload',
            pit_certified=False,
        )
        rows.append(result)
    ready = sum(r['status'] == 'ready' for r in rows)
    status = 'READY' if rows and ready == len(rows) else ('PARTIAL' if ready else 'BLOCKED')
    return {'schema_version': 'p2_profile_payload_readiness_v1',
            'status': status, 'ready_profiles': ready, 'blocked_profiles': len(rows) - ready,
            'profiles': rows, 'research_only': True, 'trade_ready': False, 'pit_certified': False,
            'model_execution_authorized': False,
            'scope_note': 'READY applies to this existing data profile at its disclosed source editions; custom field, freshness, label, cost and PIT requirements remain separate.'}


def inspect_bundle_profiles(bundle: Path, contract_override: Path | None = None) -> dict:
    """Inspect saved bytes and reconstruct components for the existing evaluator."""
    import yaml
    from src.research.comprehensive_bundle import verify_local_history

    contract_path = contract_override or bundle / 'provenance' / CONTRACT
    contract = yaml.safe_load(contract_path.read_text(encoding='utf-8'))
    components: dict[str, DataComponent] = {}
    payloads = {}
    references = {}
    with tempfile.TemporaryDirectory(prefix='alpha-profile-inputs-') as directory:
        root = Path(directory)
        for market in ('us', 'cn'):
            history = verify_local_history(bundle / f'{market}_market_history.zip')
            with zipfile.ZipFile(bundle / f'{market}_market_history.zip') as archive:
                for entry in history['files']:
                    name = entry['path']
                    if name.startswith(('configs/pools/', 'configs/research_universes/')):
                        target = root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        content = archive.read('files/' + name)
                        if target.exists() and target.read_bytes() != content:
                            raise ExchangeError('market archives disagree on governed configuration')
                        target.write_bytes(content)
                canonical = json.loads(archive.read('files/data/research/model_data_bundle_v1/data-components.json'))
                native_bundle = json.loads(archive.read('files/data/research/model_data_bundle_v1/model-data-bundle.json'))
                if native_bundle['contract_sha256'] != sha256(contract_path):
                    raise ExchangeError('profile contract differs from frozen model-data source')
                by_id = {c['component_id']: c for c in canonical}
                # Price manifest is source authority; actual all-symbol data is
                # hash-bound in the existing data-only market archive.
                pool = history['pool_id']
                component_id = 'prices.' + pool
                meta = by_id[component_id]
                relative = 'data/research/model_data_bundle_v1/' + meta['manifest_path']
                content = archive.read('files/' + relative)
                if hashlib.sha256(content).hexdigest() != meta['manifest_sha256']:
                    raise ExchangeError('price component identity mismatch')
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                component = normalize_component(ComponentSpec(component_id, 'selected_pool_prices', target, market))
                components[component_id] = replace(component, manifest_path=relative)
                catalog_path = f'files/data/research/market_evidence/{market}/catalog.json'
                catalog = json.loads(archive.read(catalog_path))
                references[market] = {r['symbol'] for r in catalog['symbols']
                                      if 'selected_pool_candidate' not in r['roles']}
                if references[market] != set(history['reference_symbols']):
                    raise ExchangeError('declared references differ from physical catalog')
                records = []
                for rec in catalog['symbols']:
                    name = f"files/data/research/market_evidence/{market}/{rec['path']}"
                    payload = archive.read(name)
                    if hashlib.sha256(payload).hexdigest() != rec['sha256']:
                        raise ExchangeError('physical price symbol payload mismatch')
                    data = json.loads(payload)
                    if not data.get('bars'):
                        raise ExchangeError('physical price symbol has no observations')
                    records.append({'symbol': rec['symbol'], 'sha256': rec['sha256'], 'rows': len(data['bars'])})
                payloads[component_id] = {'status': 'VERIFIED', 'manifest_sha256': meta['manifest_sha256'],
                    'archive_sha256': sha256(bundle / f'{market}_market_history.zip'),
                    'symbol_count': len(records), 'symbols': records}
            source_path = bundle / f'sources/{market}_events.zip'
            with zipfile.ZipFile(source_path) as archive:
                for family in ('fundamentals', 'corporate_actions'):
                    component_id = family + '.' + pool
                    meta = by_id[component_id]
                    name = f'{family}/component_manifest.json'
                    content = archive.read(name)
                    if hashlib.sha256(content).hexdigest() != meta['manifest_sha256']:
                        raise ExchangeError('event component identity mismatch')
                    target = root / f'{market}_{family}.json'
                    target.write_bytes(content)
                    component = normalize_component(ComponentSpec(component_id, meta['component_kind'], target, market))
                    components[component_id] = replace(component, manifest_path=meta['manifest_path'])
                    native = json.loads(content)
                    files = []
                    for kind in ('events', 'coverage'):
                        details = native['details']
                        path = details[f'{kind}_path']
                        data = archive.read(path)
                        digest = hashlib.sha256(data).hexdigest()
                        if digest != details[f'{kind}_sha256'] or len(data) != details[f'{kind}_byte_size']:
                            raise ExchangeError('event/coverage physical payload mismatch')
                        files.append({'member': path, 'sha256': digest, 'size': len(data)})
                    payloads[component_id] = {'status': 'VERIFIED', 'manifest_sha256': meta['manifest_sha256'],
                                             'archive_sha256': sha256(source_path), 'files': files}
            if market == 'cn':
                component_id = 'factors.qlib_alpha158.panel.cn.v1'
                meta = by_id[component_id]
                source_path = bundle / 'sources/cn_alpha158.zip'
                with zipfile.ZipFile(source_path) as archive:
                    content = archive.read('alpha158/factor_panel_manifest.json')
                    if hashlib.sha256(content).hexdigest() != meta['manifest_sha256']:
                        raise ExchangeError('Alpha158 component identity mismatch')
                    native = json.loads(content)
                    target = root / 'cn_alpha158.json'
                    target.write_bytes(content)
                    component = normalize_component(ComponentSpec(component_id, meta['component_kind'], target, market))
                    components[component_id] = replace(component, manifest_path=meta['manifest_path'])
                    panels = []
                    for path, expected in native['files'].items():
                        digest = hashlib.sha256(archive.read('alpha158/' + path)).hexdigest()
                        if digest != expected:
                            raise ExchangeError('Alpha158 physical member mismatch')
                        if path.startswith('panels/'):
                            panels.append(path)
                    if len(panels) != component.expected_symbol_count:
                        raise ExchangeError('Alpha158 panel does not retain the complete selected pool')
                    payloads[component_id] = {'status': 'VERIFIED', 'manifest_sha256': meta['manifest_sha256'],
                        'archive_sha256': sha256(source_path), 'panel_count': len(panels),
                        'quality_sha256': native['files']['factor_quality.csv.gz'],
                        'not_yet_applicable_symbols': native.get('not_yet_applicable_symbols', [])}
        registry = yaml.safe_load((root / 'configs/pools/selected_pool_registry_v1.yaml').read_text())
        selected = {row['active_pool_id'] for row in registry['markets'].values()}
        result = evaluate_profiles(contract, components, payloads, root=root,
            evidence_cutoff=max(c.evidence_cutoff for c in components.values() if c.evidence_cutoff),
            selected_pool_ids=selected, references=references)
    result['contract_path'] = CONTRACT
    result['contract_sha256'] = sha256(contract_path)
    return result
