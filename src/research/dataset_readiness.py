"""Bind physical P2 inputs to the existing model-data readiness contract.

This is a consumer projection. It does not create thresholds, substitute sources,
register strategies, certify PIT or approve training/Colab execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.data.model_data_bundle import DataComponent, evaluate_training_profile


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
