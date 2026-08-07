import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

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

type FormalCatalog = { records?: Array<{ manifest_path?: string }> };
type FormalManifest = { sections?: Array<{ section_id?: string; availability_status?: string; path?: string }> };
type FormalSummary = { display_name?: string; model_version_id?: string };

async function installBundleFixture(): Promise<void> {
  const root = resolve(process.cwd(), 'dist', 'bundle');
  await mkdir(resolve(root, 'data'), { recursive: true });
  await Promise.all([
    writeFile(resolve(root, 'alpha-engine-bundle.json'), JSON.stringify(bundleManifest), 'utf8'),
    writeFile(resolve(root, 'data', 'models.json'), modelsText, 'utf8'),
    writeFile(resolve(root, 'data', 'manifest.json'), exportManifestText, 'utf8'),
  ]);
}

test.beforeAll(async () => { await installBundleFixture(); });

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function openConsole(page: Page) {
  await page.goto('/#/app');
  await expect(page.locator('#root')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  await expect(page.locator('.research-context-bar').getByText('Static Browser Fixture', { exact: true })).toBeVisible();
}

async function loadFormalDisplayNames(page: Page): Promise<string[]> {
  const catalogResponse = await page.request.get('/data/formal-model-runs/catalog.json');
  expect(catalogResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json() as FormalCatalog;
  const names: string[] = [];
  for (const record of catalog.records ?? []) {
    const manifestPath = String(record.manifest_path);
    const manifestResponse = await page.request.get(`/data/formal-model-runs/${manifestPath}`);
    expect(manifestResponse.ok()).toBeTruthy();
    const manifest = await manifestResponse.json() as FormalManifest;
    const summarySection = manifest.sections?.find((section) => section.section_id === 'summary' && section.availability_status === 'available');
    const parent = manifestPath.split('/').slice(0, -1).join('/');
    const summaryResponse = await page.request.get(`/data/formal-model-runs/${parent}/${String(summarySection?.path)}`);
    expect(summaryResponse.ok()).toBeTruthy();
    const summary = await summaryResponse.json() as FormalSummary;
    expect(summary.display_name).toBeTruthy();
    names.push(String(summary.display_name));
  }
  expect(names.length).toBeGreaterThan(0);
  return names;
}

test('product homepage opens the strategy console', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/#/');
  await expect(page.getByRole('heading', { name: 'Run systematic strategies with the evidence still attached.' })).toBeVisible();
  await expect(page.getByText('Start with what the strategies are doing now.').first()).toBeVisible();
  await expect(page.getByText('Decision first. Evidence on demand.')).toBeVisible();
  await assertNoHorizontalOverflow(page);
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: `test-results/static-artifact/landing-${testInfo.project.name}.png`, fullPage: true });

  await page.getByRole('link', { name: 'Open Strategy Console' }).click();
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
});

test('strategy console exposes four primary destinations and formal strategy drill-down', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith('/api/')) apiRequests.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await openConsole(page);
  const navName = testInfo.project.name === 'mobile' ? 'Mobile strategy console navigation' : 'Strategy console navigation';
  if (testInfo.project.name === 'mobile') await page.getByRole('button', { name: 'Open strategy navigation' }).click();
  const navigation = page.getByRole('navigation', { name: navName });
  for (const label of ['Overview', 'Strategies', 'Research', 'System']) {
    await expect(navigation.getByRole('link', { name: label, exact: true })).toBeVisible();
  }
  await expect(navigation.getByRole('link', { name: 'Runs', exact: true })).toHaveCount(0);
  await expect(navigation.getByRole('link', { name: 'Backtests', exact: true })).toHaveCount(0);
  if (testInfo.project.name === 'mobile') await page.getByRole('button', { name: 'Close strategy navigation' }).click();

  const formalNames = await loadFormalDisplayNames(page);
  const fleet = page.getByRole('region', { name: 'Formal strategy fleet' });
  for (const name of formalNames) await expect(fleet.getByText(name, { exact: true })).toBeVisible();
  await fleet.getByText('QQQ Rotation v4.2', { exact: true }).click();
  await expect(page).toHaveURL(/#\/strategies\/qqqi_qqq_tqqq_v4_2$/);
  await expect(page.getByRole('heading', { name: 'QQQ Rotation v4.2' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Current decision state' })).toBeVisible();
  const formalTabs = page.getByRole('tablist', { name: 'Formal backtest evidence views' });
  for (const label of ['Performance', 'Risk & robustness', 'Portfolio', 'Trades', 'Attribution', 'Evidence boundary']) {
    await expect(formalTabs.getByRole('tab', { name: label, exact: true })).toBeVisible();
  }
  await assertNoHorizontalOverflow(page);

  await page.goto('/#/research');
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible();
  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'System', exact: true })).toBeVisible();
  await page.goto('/#/dashboard');
  await expect(page.getByRole('heading', { name: 'Strategy view not found' })).toBeVisible();

  expect(apiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/strategy-console-${testInfo.project.name}.png`, fullPage: true });
});

test('installed shell reopens offline after first visit', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Offline lifecycle is checked once on desktop Chromium.');
  await openConsole(page);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText('Alpha Engine', { exact: true }).first()).toBeVisible();
});
