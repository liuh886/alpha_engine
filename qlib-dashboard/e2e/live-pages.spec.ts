import { expect, test, type Page } from '@playwright/test';

const FORMAL_ROOT = 'data/formal-model-runs';

type FormalCatalog = {
  schema_version?: string;
  channel?: string;
  research_only?: boolean;
  trade_ready?: boolean;
  records?: FormalRecord[];
};

type FormalRecord = {
  model_version_id?: string;
  bundle_id?: string;
  manifest_path?: string;
  manifest_sha256?: string;
  publication_status?: string;
};

type FormalManifest = {
  sections?: Array<{
    section_id?: string;
    availability_status?: string;
    path?: string;
  }>;
};

type FormalSummary = {
  display_name?: string;
  model_version_id?: string;
};

type FormalModel = {
  displayName: string;
  version: string;
};

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function fetchFormalJson<T>(page: Page, path: string): Promise<T> {
  const url = new URL(path, page.url());
  url.searchParams.set('live_acceptance', Date.now().toString());
  const response = await page.request.get(url.toString(), {
    headers: { 'cache-control': 'no-cache', pragma: 'no-cache' },
  });
  expect(response.ok(), `failed to load ${url.toString()}`).toBeTruthy();
  return response.json() as Promise<T>;
}

async function fetchFormalCatalog(page: Page): Promise<FormalCatalog> {
  return fetchFormalJson<FormalCatalog>(page, `${FORMAL_ROOT}/catalog.json`);
}

async function loadFormalModels(page: Page, catalog: FormalCatalog): Promise<FormalModel[]> {
  const models: FormalModel[] = [];
  for (const record of catalog.records ?? []) {
    expect(record.model_version_id).toBeTruthy();
    expect(record.manifest_path).toBeTruthy();
    const manifestPath = String(record.manifest_path);
    const manifest = await fetchFormalJson<FormalManifest>(
      page,
      `${FORMAL_ROOT}/${manifestPath}`,
    );
    const summarySection = manifest.sections?.find(
      (section) => section.section_id === 'summary' && section.availability_status === 'available',
    );
    expect(summarySection?.path).toBeTruthy();
    const manifestParent = manifestPath.split('/').slice(0, -1).join('/');
    const summary = await fetchFormalJson<FormalSummary>(
      page,
      `${FORMAL_ROOT}/${manifestParent}/${String(summarySection?.path)}`,
    );
    expect(summary.model_version_id).toBe(record.model_version_id);
    expect(summary.display_name).toBeTruthy();
    models.push({
      displayName: String(summary.display_name),
      version: String(record.model_version_id),
    });
  }
  return models;
}

async function openRun(page: Page, model: string): Promise<void> {
  await page.goto(`?live_acceptance=${Date.now()}#/runs`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible();
  const catalog = page.getByRole('region', { name: 'Governed model runs' });
  const modelButton = catalog.getByRole('button', { name: new RegExp(escapeRegex(model)) });
  await expect(modelButton).toBeVisible();
  await modelButton.click();
  await expect(page.getByRole('heading', { name: model })).toBeVisible();
}

async function exerciseAvailableEvidence(page: Page): Promise<void> {
  const tabs = page.getByRole('tablist', { name: 'Formal backtest evidence views' });
  for (const label of [
    'Performance',
    'Risk & robustness',
    'Portfolio',
    'Trades',
    'Attribution',
    'Evidence boundary',
  ]) {
    await expect(tabs.getByRole('tab', { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('heading', { name: 'Strategy, benchmark and excess path' })).toBeVisible();
  await tabs.getByRole('tab', { name: 'Risk & robustness', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Retained window robustness' })).toBeVisible();
  await tabs.getByRole('tab', { name: 'Portfolio', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Frozen portfolio contract' })).toBeVisible();
}

async function expectCompleteLedgers(page: Page): Promise<void> {
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();
  await expect(page.getByText('Trade ledger unavailable')).toHaveCount(0);
  await page.getByRole('tab', { name: 'Attribution', exact: true }).click();
  await expect(page.getByText('Attribution unavailable')).toHaveCount(0);
}

test('live Pages renders every catalog-governed formal Bundle v2 baseline end to end', async ({ page }, testInfo) => {
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

  const formalCatalog = await fetchFormalCatalog(page);
  expect(formalCatalog.schema_version).toBe('2.0.0');
  expect(formalCatalog.channel).toBe('formal');
  expect(formalCatalog.research_only).toBe(true);
  expect(formalCatalog.trade_ready).toBe(false);
  expect((formalCatalog.records ?? []).length).toBeGreaterThan(0);

  const formalModels = await loadFormalModels(page, formalCatalog);
  expect(formalModels).toHaveLength(formalCatalog.records?.length ?? 0);
  expect(new Set(formalModels.map((model) => model.version)).size).toBe(formalModels.length);
  expect(new Set(formalModels.map((model) => model.displayName)).size).toBe(formalModels.length);

  const catalogRegion = page.getByRole('region', { name: 'Governed model runs' });
  for (const model of formalModels) {
    await expect(
      catalogRegion.getByRole('button', { name: new RegExp(escapeRegex(model.displayName)) }),
    ).toBeVisible();
  }
  await expect(catalogRegion.getByText('formal', { exact: true })).toHaveCount(formalModels.length);

  for (const record of formalCatalog.records ?? []) {
    expect(record.publication_status).toBe('accepted_formal_baseline');
    expect(record.bundle_id).toMatch(/^[a-f0-9]{64}$/);
    expect(record.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(record.manifest_path).toMatch(/manifest\.json$/);
  }

  for (const model of formalModels) {
    await openRun(page, model.displayName);
    await exerciseAvailableEvidence(page);
    await expectCompleteLedgers(page);
    await assertNoHorizontalOverflow(page);
  }

  expect(pageErrors).toEqual([]);
  expect(failedRequiredResponses).toEqual([]);
  expect(legacyRequests).toEqual([]);
  await page.screenshot({
    path: `test-results/live-pages/formal-bundle-v2-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
