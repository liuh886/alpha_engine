"""Existing coverage gates require actual bound payloads, not copied READY labels."""
from dataclasses import replace
from pathlib import Path

import yaml

from src.data.model_data_bundle import DataComponent
from src.research.dataset_readiness import evaluate_profiles


def fixture(tmp_path: Path):
    cfg = tmp_path / 'configs/pools'
    cfg.mkdir(parents=True)
    (cfg / 'pool.yaml').write_text('candidate_count: 2\nsymbols: ["000001", "301666"]\n')
    (cfg / 'reference_instrument_registry_v1.yaml').write_text(yaml.safe_dump({
        'markets': {'cn': {'instruments': {'CSI300': {
            'canonical_symbol': '000300.SH', 'provider_aliases': ['000300', '000300.SH']}}}}}))
    component = DataComponent(
        component_id='factor.cn', component_kind='factor_panel', status='partial',
        market='cn', pool_id='cn_pool', manifest_path='factor.json', manifest_sha256='a' * 64,
        evidence_cutoff='2026-09-04', first_date='2021-01-04', last_date='2026-09-04',
        expected_symbol_count=2, ready_symbol_count=1, coverage_ratio=0.5,
        not_yet_applicable_symbols=('301666',), missing_symbols=(), invalid_symbols=(),
        quarantined_symbols=(), providers=('canonical',), professional_source_ready=None,
        research_only=True, trade_ready=False, details={})
    profile = {'market': 'cn', 'candidate_pool_id': 'cn_pool',
               'candidate_pool_spec': 'configs/pools/pool.yaml', 'references': ['000300.SH'],
               'required_components': [{'component_id': 'factor.cn', 'accepted_statuses': ['ready', 'partial'],
                                        'minimum_coverage_ratio': 1.0, 'allow_not_yet_applicable': True}]}
    return {'profiles': {'cn_alpha': profile}}, component


def run(tmp_path, contract, component, proof=None, refs=None):
    return evaluate_profiles(contract, {'factor.cn': component},
        {'factor.cn': proof or {'status': 'VERIFIED', 'manifest_sha256': 'a' * 64}},
        root=tmp_path, evidence_cutoff='2026-11-03', selected_pool_ids={'cn_pool'},
        references={'cn': {'000300'} if refs is None else refs})


def test_declared_not_yet_applicable_partition_passes_without_dropping_symbol(tmp_path):
    contract, component = fixture(tmp_path)
    result = run(tmp_path, contract, component)
    assert result['status'] == 'READY'
    row = result['profiles'][0]
    assert row['candidate_count'] == 2
    assert row['required_components'][0]['applicable_coverage_ratio'] == 1.0
    assert row['earliest_required_source_cutoff'] == '2026-09-04'
    assert row['evaluation_cutoff'] == '2026-11-03'
    assert not result['model_execution_authorized']


def test_copied_ready_metadata_without_payload_is_blocked(tmp_path):
    contract, component = fixture(tmp_path)
    result = run(tmp_path, contract, component, {'status': 'MISSING'})
    assert result['profiles'][0]['contract_gate_status'] == 'ready'
    assert result['status'] == 'BLOCKED'
    assert any('physical_payload_not_verified' in s for s in result['profiles'][0]['failed_gates'])


def test_payload_hash_must_match_exact_component_manifest(tmp_path):
    contract, component = fixture(tmp_path)
    result = run(tmp_path, contract, component, {'status': 'VERIFIED', 'manifest_sha256': 'b' * 64})
    assert any('source_manifest_hash_mismatch' in s for s in result['profiles'][0]['failed_gates'])


def test_missing_reference_blocks_even_if_coverage_metadata_is_ready(tmp_path):
    contract, component = fixture(tmp_path)
    result = run(tmp_path, contract, component, refs=set())
    assert result['status'] == 'BLOCKED'
    assert any('physical_price_payload_missing' in s for s in result['profiles'][0]['failed_gates'])


def test_no_new_lifecycle_exception_or_threshold_is_invented(tmp_path):
    contract, component = fixture(tmp_path)
    contract['profiles']['cn_alpha']['required_components'][0]['allow_not_yet_applicable'] = False
    result = run(tmp_path, contract, component)
    assert result['status'] == 'BLOCKED'
    assert any('coverage=' in s for s in result['profiles'][0]['failed_gates'])


def test_missing_independent_component_does_not_block_valid_profile(tmp_path):
    contract, component = fixture(tmp_path)
    other = dict(contract['profiles']['cn_alpha'])
    other['required_components'] = [{'component_id': 'missing', 'minimum_coverage_ratio': 1.0}]
    contract['profiles']['other'] = other
    result = run(tmp_path, contract, component)
    assert result['status'] == 'PARTIAL'
    assert result['ready_profiles'] == 1 and result['blocked_profiles'] == 1


def test_future_component_and_candidate_count_mismatch_remain_blockers(tmp_path):
    contract, component = fixture(tmp_path)
    component = replace(component, evidence_cutoff='2026-11-04', expected_symbol_count=3)
    result = run(tmp_path, contract, component)
    reasons = result['profiles'][0]['failed_gates']
    assert any('exceeds' in s for s in reasons)
    assert any('candidate_count_mismatch' in s for s in reasons)
