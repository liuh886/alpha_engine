import { createHash } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

const modelsText = JSON.stringify([
  {
    id: 'qqqi_qqq_tqqq_v4_3',
    name: 'QQQ Rotation v4.3',
    market: 'us',
    model_type: 'rule_based_rotation',
    stage: 'BASELINE',
    created_at: '2026-08-02T00:00:00Z',
    metrics: { 'Annualized Return': 0.2, 'Max Drawdown': -0.15 },
  },
]);
const exportManifestText = JSON.stringify({
  generated_at: '2026-08-02T00:00:00Z',
  snapshot_id: 'operations-fixture',
});
const bundleManifest = {
  schema_version: '1.0.0',
  frontend_reader_range: '>=1.0.0 <2.0.0',
  bundle_id: 'a'.repeat(64),
  title: 'Strategy Operations Fixture',
  generated_at: '2026-08-02T00:00:00Z',
  evidence_cutoff: '2026-07-31',
  research_only: true,
  trade_ready: false,
  scope: { markets: ['us'], snapshot_id: 'operations-fixture', model_count: 1 },
  warnings: [],
  blocked_gates: ['trade_ready'],
  promotion_decision: 'formal_baseline',
  artifacts: [
    {
      artifact_id: '1'.repeat(16),
      kind: 'model_index',
      path: 'data/models.json',
      media_type: 'application/json',
      byte_size: Buffer.byteLength(modelsText),
      sha256: sha256(modelsText),
      required: true,
    },
    {
      artifact_id: '2'.repeat(16),
      kind: 'static_export_manifest',
      path: 'data/manifest.json',
      media_type: 'application/json',
      byte_size: Buffer.byteLength(exportManifestText),
      sha256: sha256(exportManifestText),
      required: true,
    },
  ],
};

const operations = {
  schema_version: '2.0.0',
  generated_at: '2026-08-02T00:03:00Z',
  research_only: true,
  trade_ready: false,
  records: [
    {
      model_version_id: 'qqqi_qqq_tqqq_v4_3',
      status: 'target_pending_execution',
      as_of: '2026-07-31',
      latest_completed_session: '2026-07-31',
      decision_cadence: 'Every completed US market session',
      next_decision_policy: 'Evaluate at close; target applies to the next eligible open.',
      state_label: 'Defensive → Transition',
      decision_reason: 'QQQ repair with easing volatility',
      allocations: [
        { asset: 'QQQ', current: 0, target: 0.5, delta: 0.5 },
        { asset: 'QQQI', current: 1, target: 0.5, delta: -0.5 },
        { asset: 'TQQQ', current: 0, target: 0, delta: 0 },
      ],
      turnover: 1,
      estimated_cost: 0.001,
      data_freshness: 'current',
      factor_freshness: 'current',
      delivery_status: 'sent',
      source_label: 'Governed QQQ signal ledger',
      source_href: 'https://github.com/liuh886/alpha_engine/issues/9001',
      note: 'Target is awaiting next-open execution evidence.',
      factor_evidence: [
        {
          factor_id: 'strategy.qqq.vix_close',
          factor_version: '1.0',
          implementation_hash: 'd'.repeat(64),
          display_name: 'VIX close',
          information_family: 'volatility',
          value: 15.99,
          reference: { normal: 18, stress: 22 },
          state: 'calm',
          effect: 'veto',
          reason_code: 'vix_easing_supports_release',
          observed_at: '2026-07-31',
        },
        {
          factor_id: 'strategy.qqq.qqq_vs_ma20',
          factor_version: '1.0',
          implementation_hash: 'e'.repeat(64),
          display_name: 'QQQ distance to SMA20',
          information_family: 'trend',
          value: 0.01,
          reference: 0,
          state: 'at_or_above',
          effect: 'veto',
          reason_code: 'price_repair_supports_release',
          observed_at: '2026-07-31',
        },
      ],
      source_identity: {
        formal_bundle_id: 'a'.repeat(64),
        formal_run_id: 'qqq-formal-run',
        formal_evidence_cutoff: '2026-07-31',
        ledger_fingerprint: 'fixture-fingerprint',
        signal_sha256: 'b'.repeat(64),
        factor_catalog_implementation_hash: 'f'.repeat(64),
        workflow_run_id: '12345',
        commit_sha: 'c'.repeat(40),
        github_issue_number: 9001,
      },
    },
  ],
};

async function mockBundle(page: Page) {
  await page.route('**/bundle/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith('/alpha-engine-bundle.json')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bundleManifest) });
    } else if (pathname.endsWith('/data/models.json')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: modelsText });
    } else if (pathname.endsWith('/data/manifest.json')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: exportManifestText });
    } else {
      await route.fulfill({ status: 404, body: 'not declared' });
    }
  });
  await page.route('**/data/strategy-operations/snapshots.json', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(operations) });
  });
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

test('QQQ operating evidence is rendered from the governed static read model', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const githubApiRequests: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (request.url().startsWith('https://api.github.com/')) githubApiRequests.push(request.url());
  });
  await mockBundle(page);

  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await expect(page.getByRole('main').getByRole('heading', { name: 'QQQ Rotation v4.3', exact: true, level: 1 })).toBeVisible();

  const now = page.getByRole('region', { name: 'Current decision state' });
  await expect(now).toBeVisible();
  await expect(now.getByText('Defensive → Transition', { exact: true })).toBeVisible();
  await expect(now.getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(now.getByText('QQQI', { exact: true })).toBeVisible();
  await expect(now.getByText('QQQ', { exact: true })).toBeVisible();
  await expect(now.getByText('VIX close', { exact: true })).toBeVisible();
  await expect(now.getByText('15.99', { exact: true })).toBeVisible();
  await expect(now.getByText('calm', { exact: true })).toBeVisible();
  await expect(now.getByText('vix_easing_supports_release', { exact: false })).toBeVisible();
  await expect(page.getByText('New target', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Source record' })).toHaveAttribute('href', 'https://github.com/liuh886/alpha_engine/issues/9001');

  const evidenceTabs = page.getByRole('tablist', { name: 'Formal backtest evidence views' });
  await expect(evidenceTabs.getByRole('tab', { name: 'Performance', exact: true })).toBeVisible();
  await expect(evidenceTabs.getByRole('tab', { name: 'Risk & robustness', exact: true })).toBeVisible();
  await expect(page.getByText('Sign in')).toHaveCount(0);
  expect(githubApiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({
    path: `test-results/static-artifact/strategy-operations-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
