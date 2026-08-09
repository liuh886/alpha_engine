import { expect, test, type Page } from '@playwright/test';

import { publicModelDisplayName } from '../src/lib/model-presentation';

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
      displayName: publicModelDisplayName(String(summary.display_name), {
        modelVersionId: String(record.model_version_id),
      }),
      version: String(record.model_version_id),
    });
  }
  return models;
}

async function openStrategy(page: Page, model: FormalModel): Promise<'accessible' | 'gated'> {
  await page.goto(
    `?live_acceptance=${Date.now()}#/strategies/${encodeURIComponent(model.version)}`,
    { waitUntil: 'networkidle' },
  );
  const main = page.getByRole('main');
  const strategyHeading = main.getByRole('heading', {
    name: model.displayName,
    exact: true,
    level: 1,
  });
  const memberGate = main.getByRole('heading', { name: `Sign in to open ${model.displayName}`, exact: true });
  const proGate = main.getByRole('heading', { name: `${model.displayName} is a Pro product`, exact: true });
  const ownerGate = main.getByRole('heading', { name: `${model.displayName} requires Owner access`, exact: true });
  await expect(strategyHeading.or(memberGate).or(proGate).or(ownerGate)).toBeVisible();

  if (!(await strategyHeading.isVisible())) {
    await expect(main.getByRole('button', { name: /Sign in to continue|View Pro access|Open account/ })).toBeVisible();
    return 'gated';
  }
  await expect(page.getByRole('heading', { name: 'Current decision state', exact: true })).toBeVisible();
  return 'accessible';
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

async function assertPrimaryNavigation(page: Page, projectName: string): Promise<void> {
  const mobile = projectName === 'mobile';
  if (mobile) await page.getByRole('button', { name: 'Open strategy navigation' }).click();
  const navigation = page.getByRole('navigation', {
    name: mobile ? 'Mobile strategy console navigation' : 'Strategy console navigation',
  });
  for (const label of ['Overview', 'Strategies', 'Research', 'System']) {
    await expect(navigation.getByRole('link', { name: label, exact: true })).toBeVisible();
  }
  await expect(navigation.getByRole('link', { name: 'Runs', exact: true })).toHaveCount(0);
  await expect(navigation.getByRole('link', { name: 'Backtests', exact: true })).toHaveCount(0);
  if (mobile) await page.getByRole('button', { name: 'Close strategy navigation' }).click();
}

test('live Pages renders or explicitly policy-gates every catalog-governed formal strategy', async ({ page }, testInfo) => {
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
        || url.includes('/data/strategy-operations/')
        || url.includes('/assets/'))
    ) {
      failedRequiredResponses.push(`${response.status()} ${url}`);
    }
  });

  await page.goto(`?live_acceptance=${Date.now()}#/app`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?', exact: true })).toBeVisible();
  await assertPrimaryNavigation(page, testInfo.project.name);

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

  const fleet = page.getByRole('region', { name: 'Formal strategy fleet' });
  for (const model of formalModels) {
    await expect(fleet.getByText(model.displayName, { exact: true })).toBeVisible();
  }

  for (const record of formalCatalog.records ?? []) {
    expect(record.publication_status).toBe('accepted_formal_baseline');
    expect(record.bundle_id).toMatch(/^[a-f0-9]{64}$/);
    expect(record.manifest_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(record.manifest_path).toMatch(/manifest\.json$/);
  }

  for (const model of formalModels) {
    const access = await openStrategy(page, model);
    if (access === 'accessible') {
      await exerciseAvailableEvidence(page);
      await expectCompleteLedgers(page);
    }
    await assertNoHorizontalOverflow(page);
  }

  expect(pageErrors).toEqual([]);
  expect(failedRequiredResponses).toEqual([]);
  expect(legacyRequests).toEqual([]);
  await page.screenshot({
    path: `test-results/live-pages/strategy-console-live-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
