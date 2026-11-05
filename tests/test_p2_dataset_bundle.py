"""P2 physical payload, honest coverage and local/cloud separation regressions."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.data.fundamentals.ashare_public_financials import AsharePublicFinancialClient
from src.research.cloud_exchange import ExchangeError, verify
from src.research.comprehensive_bundle import inventory_archive, local_history_pack, verify_local_history
from src.research.dataset_inventory import inspect_security
from src.research.comprehensive_dataset import approved_pack
from src.research.source_archive_recovery import inspect_market_archive


class P2DatasetBundleTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)

    def _history_fixture(self):
        from tests.test_comprehensive_dataset import FullMarketHistoryTest
        fixture = FullMarketHistoryTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_local_only_history_cannot_pass_cloud_exchange_verifier(self):
        fixture = self._history_fixture()
        out = self.home / 'history.zip'
        result = local_history_pack(fixture.root, 'us', out)
        self.assertFalse(result['cloud_copy_approved'])
        self.assertFalse(verify_local_history(out)['owner_approved_private_cloud_copy'])
        with self.assertRaisesRegex(ExchangeError, 'unsupported'):
            verify(out)

    def test_local_archive_is_deterministic_and_refuses_overwrite(self):
        fixture = self._history_fixture()
        a, b = self.home / 'a.zip', self.home / 'b.zip'
        self.assertEqual(local_history_pack(fixture.root, 'us', a)['sha256'],
                         local_history_pack(fixture.root, 'us', b)['sha256'])
        before = a.read_bytes()
        with self.assertRaises(FileExistsError):
            local_history_pack(fixture.root, 'us', a)
        self.assertEqual(a.read_bytes(), before)

    def _add_model_events(self, fixture):
        path = fixture.root / 'data/research/market_evidence/us/symbols/U000.json'
        payload = json.loads(path.read_text())
        payload['formal_model_events'] = [{'target_weight': 0.25, 'previous_weight': 0.1}]
        path.write_text(json.dumps(payload), encoding='utf-8')
        catalog = fixture.root / fixture.catalog_path
        data = json.loads(catalog.read_text())
        data['symbols'][0]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        catalog.write_text(json.dumps(data), encoding='utf-8')
        return data['symbols'][0]['sha256']

    def test_market_data_projection_excludes_model_weights_but_pins_original_sha(self):
        fixture = self._history_fixture()
        original_sha = self._add_model_events(fixture)
        out = self.home / 'clean.zip'
        local_history_pack(fixture.root, 'us', out)
        manifest = verify_local_history(out)
        with zipfile.ZipFile(out) as archive:
            payload = archive.read('files/data/research/market_evidence/us/symbols/U000.json')
            self.assertNotIn(b'target_weight', payload)
            self.assertNotIn(b'formal_model_events', payload)
        entry = next(f for f in manifest['files'] if f['path'].endswith('U000.json'))
        self.assertEqual(entry['upstream_sha256'], original_sha)

    def test_legacy_cloud_market_pack_fails_closed_on_mixed_model_payload(self):
        fixture = self._history_fixture()
        self._add_model_events(fixture)
        fixture._rights(True)
        with self.assertRaisesRegex(ExchangeError, 'model events'):
            approved_pack(fixture.root, 'us', fixture.approval, self.home / 'cloud.zip')

    def test_history_member_tampering_is_rejected(self):
        fixture = self._history_fixture()
        original, changed = self.home / 'a.zip', self.home / 'changed.zip'
        local_history_pack(fixture.root, 'us', original)
        with zipfile.ZipFile(original) as src, zipfile.ZipFile(changed, 'w') as dst:
            for name in src.namelist():
                data = src.read(name)
                if name.endswith('U000.json'):
                    data += b' '
                dst.writestr(name, data)
        with self.assertRaisesRegex(ExchangeError, 'size mismatch'):
            verify_local_history(changed)

    def test_inner_source_binding_cannot_be_replaced_by_matching_outer_zip_hash(self):
        path = self.home / 'source.zip'
        component = {'files': {'payload.jsonl': '0' * 64}}
        content = json.dumps(component).encode()
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('component.json', content)
            archive.writestr('payload.jsonl', b'{}\n')
        record = {'source_id': 'us_events', 'market': 'us', 'cutoff': '2026-09-30',
                  'size_bytes': path.stat().st_size,
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        authority = {'component_manifests': [{'path': 'component.json',
                     'sha256': hashlib.sha256(content).hexdigest()}]}
        with self.assertRaisesRegex(ExchangeError, 'inner component file SHA'):
            inventory_archive(path, record, authority)

    def test_symbol_presence_does_not_hide_prefix_interior_or_non_session_gaps(self):
        row = {'open': 1.0, 'high': 2.0, 'low': 1.0, 'close': 1.5, 'volume': 10.0}
        payload = {'symbol': '301666', 'bars': [dict(row, time=d) for d in (
            '2026-04-16', '2026-04-18', '2026-04-20')]}
        result = inspect_security(payload, ['2026-04-15', '2026-04-16', '2026-04-17',
                                          '2026-04-20', '2026-04-21'], '2026-04-15', '2026-04-21')
        self.assertEqual(result['missing_prefix_sessions'], ['2026-04-15'])
        self.assertEqual(result['missing_interior_sessions'], ['2026-04-17'])
        self.assertEqual(result['missing_suffix_sessions'], ['2026-04-21'])
        self.assertEqual(result['non_session_dates'], ['2026-04-18'])
        self.assertFalse(result['historical_completeness_certified'])

    def test_terminal_listing_does_not_generate_false_suffix_missingness(self):
        row = {'open': 1, 'high': 2, 'low': 1, 'close': 1, 'volume': 1, 'time': '2026-08-04'}
        result = inspect_security({'symbol': 'EA', 'bars': [row]},
            ['2026-08-04', '2026-08-05'], '2026-08-04', '2026-08-05', '2026-08-04')
        self.assertEqual(result['missing_suffix_sessions'], [])

    def test_new_listing_empty_annual_category_does_not_hide_halfyear_report(self):
        expected = pd.DataFrame([{'代码': '301666', '公告标题': '2026年半年度报告',
                                  '公告时间': '2026-08-25'}])
        message = "None of [Index(['代码', '简称', '公告标题', '公告时间', 'announcementId', 'orgId'])] are in the [columns]"
        def fetch(**kwargs):
            if kwargs['category'] == '半年报':
                return expected
            raise KeyError(message)
        fake = SimpleNamespace(stock_zh_a_disclosure_report_cninfo=fetch)
        with patch.object(AsharePublicFinancialClient, '_akshare', return_value=fake):
            result = AsharePublicFinancialClient().fetch_disclosures(
                symbol='301666', start_date='20210101', end_date='20260904')
        pd.testing.assert_frame_equal(result, expected)

    def test_unrelated_disclosure_schema_error_still_blocks(self):
        fake = SimpleNamespace(stock_zh_a_disclosure_report_cninfo=lambda **_: (_ for _ in ()).throw(KeyError('orgId')))
        with patch.object(AsharePublicFinancialClient, '_akshare', return_value=fake):
            with self.assertRaisesRegex(KeyError, 'orgId'):
                AsharePublicFinancialClient().fetch_disclosures(
                    symbol='301666', start_date='20210101', end_date='20260904')

    def test_market_archive_must_match_existing_per_symbol_source_hash(self):
        root = self.home / 'repo'
        base = root / 'data/research/market_evidence/us'
        (base / 'symbols').mkdir(parents=True)
        (base / 'catalog.json').write_text(json.dumps({'cutoff':'2026-11-03',
            'symbols':[{'symbol':'AAPL','path':'symbols/AAPL.json'}]}))
        expected = b'date,close,factor\n2026-11-03,10,1\n'
        (base / 'symbols/AAPL.json').write_text(json.dumps(
            {'source_csv_sha256':hashlib.sha256(expected).hexdigest()}))
        archive = self.home / 'provider.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('data/csv_source/AAPL.csv', expected)
        record = {'market':'us','cutoff':'2026-11-03','size_bytes':archive.stat().st_size,
                  'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
        self.assertEqual(inspect_market_archive(root,archive,record)['verified_symbols'],1)
        (base / 'symbols/AAPL.json').write_text(json.dumps({'source_csv_sha256':'0'*64}))
        with self.assertRaisesRegex(ExchangeError,'exact market source CSV mismatch'):
            inspect_market_archive(root,archive,record)


if __name__ == '__main__':
    unittest.main()
