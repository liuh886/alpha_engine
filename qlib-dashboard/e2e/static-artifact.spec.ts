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

async function installBundleFixture(): Promise<void> {
  const root = resolve(process.cwd(), 'dist', 'bundle');
  await mkdir(resolve(root, 'data'), { recursive: true });
  await Promise.all([
    writeFile(resolve(root, 'alpha-engine-bundle.json'), JSON.stringify(bundleManifest), 'utf8'),
    writeFile(resolve(root, 'data', 'models.json'), modelsText, 'utf8'),
    writeFile(resolve(root, 'data', 'manifest.json'), exportManifestText, 'utf8'),
  ]);
}

test.beforeAll(async () => {
  await installBundleFixture();
});

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function openStudio(page: Page) {
  await page.goto('/#/app');
  await expect(page.locator('#root')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'Decide what the evidence supports.' })).toBeVisible();
  await expect(page.locator('.research-context-bar').getByText('Static Browser Fixture', { exact: true })).toBeVisible();
}

test('product homepage explains the workflow and opens the research studio', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/#/');
  await expect(page.getByRole('heading', { name: 'Turn systematic research into decisions you can inspect.' })).toBeVisible();
  await expect(page.getByText('Choose the run before reading the result.')).toBeVisible();
  await expect(page.getByText('Performance is only useful when its source is visible.')).toBeVisible();
  await expect(page.getByText('Every conclusion keeps its evidence attached.')).toBeVisible();
  await assertNoHorizontalOverflow(page);
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: `test-results/static-artifact/landing-${testInfo.project.name}.png`, fullPage: true });

  await page.getByRole('link', { name: 'Open Research Studio' }).click();
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByRole('heading', { name: 'Decide what the evidence supports.' })).toBeVisible();
});

test('static studio opens without authentication or backend APIs', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  const legacyFormalRequests: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith('/api/')) apiRequests.push(request.url());
    if (pathname.includes('/data/formal-backtests/')) legacyFormalRequests.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await openStudio(page);

  if (testInfo.project.name === 'mobile') {
    await page.getByRole('button', { name: 'Open research navigation' }).click();
    const mobileNavigation = page.getByRole('navigation', { name: 'Mobile research studio navigation' });
    await expect(mobileNavigation).toBeVisible();
    await expect(mobileNavigation.getByRole('link', { name: 'Runs', exact: true })).toBeVisible();
    await expect(mobileNavigation.getByRole('link', { name: 'Data', exact: true })).toBeVisible();
    await expect(mobileNavigation.getByRole('link', { name: 'Experiments', exact: true })).toHaveCount(0);
    await expect(mobileNavigation.getByRole('link', { name: 'Backtests', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Close research navigation' }).first().click();
  } else {
    const navigation = page.getByRole('navigation', { name: 'Research studio navigation' });
    await expect(navigation).toBeVisible();
    await expect(navigation.getByRole('link', { name: 'Runs', exact: true })).toBeVisible();
    await expect(navigation.getByRole('link', { name: 'Experiments', exact: true })).toHaveCount(0);
    await expect(navigation.getByRole('link', { name: 'Backtests', exact: true })).toBeVisible();
  }
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Sign in')).toHaveCount(0);
  expect(apiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/overview-${testInfo.project.name}.png`, fullPage: true });

  await page.goto('/#/runs');
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible();
  const catalog = page.getByRole('region', { name: 'Governed model runs' });
  await expect(catalog.getByRole('button', { name: /QQQ Rotation v4\.2/ })).toBeVisible();
  await expect(catalog.getByRole('button', { name: /US x1\.1/ })).toBeVisible();
  await expect(catalog.getByRole('button', { name: /CN x1\.1/ })).toBeVisible();
  await expect(catalog.getByRole('button', { name: /BYD Dividend Sleeve V1\.0/ })).toBeVisible();
  await expect(catalog.getByText('formal', { exact: true })).toHaveCount(4);
  await catalog.getByRole('button', { name: /QQQ Rotation v4\.2/ }).click();
  await expect(page).toHaveURL(/#\/review\?channel=formal&family=qqq_rotation&version=qqqi_qqq_tqqq_v4_2/);
  await expect(page.getByRole('heading', { name: 'QQQ Rotation v4.2' })).toBeVisible();
  const formalTabs = page.getByRole('tablist', { name: 'Formal backtest evidence views' });
  for (const label of ['Performance', 'Risk & robustness', 'Portfolio', 'Trades', 'Attribution', 'Evidence boundary']) {
    await expect(formalTabs.getByRole('tab', { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: 'Strategy, benchmark and excess path' })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/governed-review-${testInfo.project.name}.png`, fullPage: true });

  await page.goto('/#/backtests');
  await expect(page.getByRole('main').getByRole('heading', { name: 'Formal Backtests', exact: true, level: 2 })).toBeVisible();
  const baselines = page.getByRole('region', { name: 'Accepted formal backtest baselines' });
  await expect(baselines.getByRole('button', { name: /QQQ Rotation v4\.2/ })).toBeVisible();
  await expect(baselines.getByRole('button', { name: /US x1\.1/ })).toBeVisible();
  await expect(baselines.getByRole('button', { name: /CN x1\.1/ })).toBeVisible();
  await expect(baselines.getByRole('button', { name: /BYD Dividend Sleeve V1\.0/ })).toBeVisible();
  await expect(page.getByTestId('formal-backtest-review')).toBeVisible();
  await assertNoHorizontalOverflow(page);

  await page.goto('/#/dashboard');
  await expect(page).toHaveURL(/#\/backtests$/);
  await expect(page.getByRole('main').getByRole('heading', { name: 'Formal Backtests', exact: true, level: 2 })).toBeVisible();

  await page.goto('/#/data');
  await expect(page.getByRole('heading', { name: 'Data identity and readiness' })).toBeVisible();
  await expect(page.locator('main').getByText('2026-07-31', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/data-${testInfo.project.name}.png`, fullPage: true });

  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'Evidence view not found' })).toBeVisible();
  await expect(page.locator('.research-topbar').getByRole('heading', { name: 'Unavailable route' })).toBeVisible();
  expect(apiRequests).toEqual([]);
  expect(legacyFormalRequests).toEqual([]);
  expect(pageErrors).toEqual([]);

  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement?.tagName.toLowerCase());
  expect(['a', 'button', 'input']).toContain(focused);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/runtime-blocked-${testInfo.project.name}.png`, fullPage: true });
});

test('installed shell reopens offline after first visit', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Offline lifecycle is checked once on desktop Chromium.');
  await openStudio(page);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Decide what the evidence supports.' })).toBeVisible();
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText('Alpha Engine', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
});
