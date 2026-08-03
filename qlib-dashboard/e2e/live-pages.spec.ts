import { expect, test, type Page } from '@playwright/test';

const FORMAL_MODELS = ['QQQ Rotation v4.2', 'US x1.1', 'CN x1.0'] as const;
const FORMAL_VERSIONS = ['qqqi_qqq_tqqq_v4_2', 'us_x1_1', 'cn_x1_0'] as const;

type FormalCatalog = {
  schema_version?: string;
  channel?: string;
  research_only?: boolean;
  trade_ready?: boolean;
  records?: Array<{
    model_version_id?: string;
    bundle_id?: string;
    manifest_path?: string;
    manifest_sha256?: string;
    publication_status?: string;
  }>;
};

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function fetchFormalCatalog(page: Page): Promise<FormalCatalog> {
  const url = new URL('data/formal-model-runs/catalog.json', page.url());
  url.searchParams.set('live_acceptance', Date.now().toString());
  const response = await page.request.get(url.toString(), {
    headers: { 'cache-control': 'no-cache', pragma: 'no-cache' },
  });
  expect(response.ok(), `failed to load ${url.toString()}`).toBeTruthy();
  return response.json() as Promise<FormalCatalog>;
}

async function openRun(page: Page, model: typeof FORMAL_MODELS[number]): Promise<void> {
  await page.goto(`?live_acceptance=${Date.now()}#/runs`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible();
  const catalog = page.getByRole('region', { name: 'Governed model runs' });
  await expect(catalog.getByRole('button', { name: new RegExp(model.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })).toBeVisible();
  await catalog.getByRole('button', { name: new RegExp(model.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click();
  await expect(page.getByRole('heading', { name: model })).toBeVisible();
}

async function exerciseAvailableEvidence(page: Page): Promise<void> {
  const tabs = page.getByRole('tablist', { name: 'Run capability evidence' });
  for (const label of ['Summary', 'Alpha', 'Risk', 'Robustness', 'Portfolio']) {
    await expect(tabs.getByRole('tab', { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByText('Source:', { exact: true }).first()).toBeVisible();

  await tabs.getByRole('tab', { name: 'Alpha', exact: true }).click();
  await expect(page.getByText(/performance\.json/)).toBeVisible();
  await tabs.getByRole('tab', { name: 'Risk', exact: true }).click();
  await expect(page.getByText(/risk\.json/)).toBeVisible();
  await tabs.getByRole('tab', { name: 'Robustness', exact: true }).click();
  await expect(page.getByText(/robustness\.json/)).toBeVisible();
  await tabs.getByRole('tab', { name: 'Portfolio', exact: true }).click();
  await expect(page.getByText(/portfolio\.json/)).toBeVisible();
}

test('live Pages renders all governed formal Bundle v2 baselines end to end', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const failedRequiredResponses: string[] = [];
  const legacyRequests: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (request.url().includes('/data/formal-backtests/')) legacyRequests.push(request.url());
  });
  page.on('response', (response) => {
    const url = response.url();
    if (
      response.status() >= 400
      && (url.includes('/bundle/')
        || url.includes('/data/formal-model-runs/')
        || url.includes('/data/model-runs/')
        || url.includes('/data/model-decisions/')
        || url.includes('/assets/'))
    ) {
      failedRequiredResponses.push(`${response.status()} ${url}`);
    }
  });

  await page.goto(`?live_acceptance=${Date.now()}#/runs`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Experiments', { exact: true })).toHaveCount(0);

  const catalogRegion = page.getByRole('region', { name: 'Governed model runs' });
  for (const model of FORMAL_MODELS) {
    await expect(catalogRegion.getByRole('button', { name: new RegExp(model.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })).toBeVisible();
  }
  await expect(catalogRegion.getByText('formal', { exact: true })).toHaveCount(3);
  await expect(catalogRegion.getByText('US x1.0', { exact: true })).toHaveCount(0);

  const formalCatalog = await fetchFormalCatalog(page);
  expect(formalCatalog.schema_version).toBe('2.0.0');
  expect(formalCatalog.channel).toBe('formal');
  expect(formalCatalog.research_only).toBe(true);
  expect(formalCatalog.trade_ready).toBe(false);
  expect(formalCatalog.records).toHaveLength(3);
  expect(new Set(formalCatalog.records?.map((record) => record.model_version_id))).toEqual(new Set(FORMAL_VERSIONS));
  for (const record of formalCatalog.records ?? []) {
    expect(record.publication_status).toBe('accepted_formal_baseline');
    expect(record.bundle_id).toMatch(/^[a-f0-9]{64}$/);
    expect(record.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(record.manifest_path).toMatch(/manifest\.json$/);
  }

  await openRun(page, 'QQQ Rotation v4.2');
  await exerciseAvailableEvidence(page);
  await expect(page.getByText(/trades\.json/)).toBeVisible();
  await expect(page.getByText(/attribution\.json/)).toBeVisible();
  await assertNoHorizontalOverflow(page);

  await openRun(page, 'US x1.1');
  await exerciseAvailableEvidence(page);
  await expect(page.getByText(/trades\.json/)).toBeVisible();
  await expect(page.getByText(/attribution\.json/)).toBeVisible();
  await assertNoHorizontalOverflow(page);

  await openRun(page, 'CN x1.0');
  await exerciseAvailableEvidence(page);
  await expect(page.getByRole('heading', { name: 'Trades unavailable' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Attribution unavailable' })).toBeVisible();
  await assertNoHorizontalOverflow(page);

  expect(pageErrors).toEqual([]);
  expect(failedRequiredResponses).toEqual([]);
  expect(legacyRequests).toEqual([]);
  await page.screenshot({
    path: `test-results/live-pages/formal-bundle-v2-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
