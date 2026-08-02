import { createHash } from 'node:crypto';
import { expect, test } from '@playwright/test';

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

const modelsText = JSON.stringify([
  {
    id: 'fixture-run-1',
    name: 'Static Evidence Fixture',
    market: 'us',
    model_type: 'lgbm',
    stage: 'CANDIDATE',
    created_at: '2026-07-31T00:00:00Z',
    metrics: { 'Sharpe Ratio': 1.2, 'Annualized Return': 0.18, 'Max Drawdown': -0.12 },
    payload: { data: { indicators: { sharpe: 1.2, annual_return: 0.18, max_drawdown: -0.12 } } },
  },
]);
const exportManifestText = JSON.stringify({ generated_at: '2026-08-02T00:00:00Z', snapshot_id: 'fixture-snapshot' });
const bundleManifest = {
  schema_version: '1.0.0',
  frontend_reader_range: '>=1.0.0 <2.0.0',
  bundle_id: 'a'.repeat(64),
  title: 'Static Browser Fixture',
  generated_at: '2026-08-02T00:00:00Z',
  evidence_cutoff: '2026-07-31',
  research_only: true,
  trade_ready: false,
  scope: { markets: ['us'], snapshot_id: 'fixture-snapshot', model_count: 1 },
  warnings: [],
  blocked_gates: ['trade_ready'],
  promotion_decision: 'research_candidate',
  artifacts: [
    { artifact_id: '1'.repeat(16), kind: 'model_index', path: 'data/models.json', media_type: 'application/json', byte_size: Buffer.byteLength(modelsText), sha256: sha256(modelsText), required: true },
    { artifact_id: '2'.repeat(16), kind: 'static_export_manifest', path: 'data/manifest.json', media_type: 'application/json', byte_size: Buffer.byteLength(exportManifestText), sha256: sha256(exportManifestText), required: true },
  ],
};

async function mockBundle(page: Parameters<typeof test>[0]['page']) {
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
}

test('static studio opens without authentication or backend APIs', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url());
  });
  await mockBundle(page);
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Research Artifact Studio' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Research studio navigation' })).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Static Browser Fixture').first()).toBeVisible();
  await expect(page.getByText('Sign in')).toHaveCount(0);
  expect(apiRequests).toEqual([]);

  await page.getByRole('link', { name: 'Data' }).click();
  await expect(page.getByRole('heading', { name: 'Data identity and readiness' })).toBeVisible();
  await expect(page.getByText('2026-07-31').first()).toBeVisible();

  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'Evidence view not found' })).toBeVisible();
  expect(apiRequests).toEqual([]);

  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement?.tagName.toLowerCase());
  expect(['a', 'button', 'input']).toContain(focused);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);

  await page.screenshot({ path: `test-results/static-artifact/${testInfo.project.name}.png`, fullPage: true });
});

test('installed shell reopens offline after first visit', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Offline lifecycle is checked once on desktop Chromium.');
  await mockBundle(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Research Artifact Studio' })).toBeVisible();
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Research Artifact Studio' })).toBeVisible();
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText('Alpha Engine', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
});
