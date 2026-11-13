import { expect, test, type Page } from '@playwright/test';
import { installMembershipFixture } from './membership-fixture';

type FormalCatalog = { records?: Array<{ manifest_path?: string; model_version_id?: string; evidence_cutoff?: string }> };
type FormalManifest = { comparability_key?: { start: string; end: string }; sections?: Array<{ section_id?: string; availability_status?: string; path?: string }> };
type FormalSummary = { display_name?: string; model_version_id?: string };

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
    names.push(String(summary.model_version_id).startsWith('qqqi_qqq_tqqq_')
      ? String(summary.display_name).replace(/^QQQ Rotation\b/, 'QQQR')
      : String(summary.display_name));
  }
  expect(names.length).toBeGreaterThan(0);
  return names;
}

test('the homepage opens daily research and reads only the formal operating surface', async ({ page }, testInfo) => {
  const errors: string[] = [], retiredRequests: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (/\/bundle\/|\/data\/model-runs\//.test(request.url())) retiredRequests.push(request.url());
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/');
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  const names = await loadFormalDisplayNames(page);
  await expect(brief.getByRole('article')).toHaveCount(Math.min(3, names.length));
  const ranking = page.getByRole('region', { name: 'Model ranking' });
  await expect(ranking.getByRole('link', { name: /Inspect evidence/ })).toHaveCount(names.length);
  for (const name of names) await expect(ranking.getByText(name, { exact: true })).toBeVisible();
  const markets = page.getByRole('region', { name: 'Benchmark markets' });
  await expect(markets.getByTestId('benchmark-card-us')).toContainText('QQQ');
  await expect(markets.getByTestId('benchmark-card-cn')).toContainText('CSI 300');
  const sp500 = markets.getByTestId('benchmark-card-sp500');
  await expect(sp500).toContainText('Not governed');
  await expect(sp500.locator('svg')).toHaveCount(0);
  await expect(markets.locator('[data-testid="sparkline"]')).toHaveCount(2);
  if (testInfo.project.name === 'mobile') await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('tab')).toHaveCount(4);
  else await expect(page.getByRole('navigation', { name: 'Research workspace navigation' }).getByRole('link')).toHaveCount(4);
  expect(retiredRequests).toEqual([]);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('focused-daily-overview.png'), fullPage: false });
});

test('pending catalog and operations reads show verification rather than empty or denied states', async ({ page }, testInfo) => {
  let releaseCatalog!: () => void;
  let releaseOperations!: () => void;
  const catalogGate = new Promise<void>(resolve => { releaseCatalog = resolve; });
  const operationsGate = new Promise<void>(resolve => { releaseOperations = resolve; });
  await page.route('**/data/formal-model-runs/catalog.json', async route => { await catalogGate; await route.continue(); });
  await page.route('**/data/strategy-operations/snapshots.json', async route => { await operationsGate; await route.continue(); });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  try {
    await page.goto('/#/app');
    const context = page.getByRole('status', { name: 'Strategy fleet context' });
    await expect(context).toContainText('Reading formal strategy catalog…');
    await expect(context).not.toContainText('0 strategies');
    await expect(page.getByRole('status', { name: 'Loading formal strategy evidence' })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('catalog-verification-pending.png'), fullPage: false });
    releaseCatalog();
    const brief = page.getByRole('region', { name: 'Daily research brief' });
    await expect(brief).toHaveAttribute('aria-busy', 'true');
    await expect(brief.getByRole('article')).toHaveCount(3);
    await expect(brief).toContainText('Verifying access and current observations…');
    await expect(brief).not.toContainText('Current observations require strategy access.');
    await expect(brief.getByRole('button', { name: 'Check strategy access' })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('operations-verification-pending.png'), fullPage: false });
    releaseOperations();
    await expect(brief).toHaveAttribute('aria-busy', 'false');
    await expect(brief).not.toContainText('Verifying access and current observations…');
    await expect(context).toContainText('4 strategies');
  } finally {
    releaseCatalog(); releaseOperations();
  }
});

test('fleet horizons disclose retained coverage, per-row as-of dates and stale evidence', async ({ page }, testInfo) => {
  const errors: string[] = [];
  const extraSections: string[] = [];
  const retiredRequests: string[] = [];
  const marketEvidence: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/\/bundle\//.test(path) || path.includes('/data/model-runs/')) retiredRequests.push(path);
    if (path.includes('/data/market-evidence/')) marketEvidence.push(path);
    if (path.includes('/data/formal-model-runs/')
      && /\/(performance|risk|robustness|portfolio|trades|attribution|diagnostics|lineage)\.json$/.test(path)) extraSections.push(path);
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/strategies');
  const fleet = page.getByRole('region', { name: 'Formal strategy fleet' });
  await expect(fleet.locator('[data-kind="strategy"]')).toHaveCount(4);
  await expect(fleet.locator('[data-kind="index"]')).toHaveCount(2);

  const catalog = await (await page.request.get('/data/formal-model-runs/catalog.json')).json() as FormalCatalog;
  const sources = await Promise.all((catalog.records ?? []).map(async record => {
    const base = '/data/formal-model-runs/' + String(record.manifest_path).replace(/manifest\.json$/, '');
    const navResponse = await page.request.get(base + 'nav.json');
    expect(navResponse.ok()).toBeTruthy();
    const nav = await navResponse.json() as {
      evidence_cutoff: string;
      rows: Array<{ date: string; account: number }>;
    };
    const last = nav.rows[nav.rows.length - 1];
    expect(last?.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const staleDays = Math.round((Date.parse(`${nav.evidence_cutoff}T00:00:00Z`) - Date.parse(`${last.date}T00:00:00Z`)) / 86_400_000);
    return { record, last: last.date, staleDays };
  }));

  for (const { record, last, staleDays } of sources) {
    const id = String(record.model_version_id);
    const row = fleet.getByTestId('fleet-' + id);
    await expect(row).toBeVisible();
    await expect(row).toContainText(`As of ${last}`);
    await expect(row).toHaveAttribute('data-stale', staleDays > 14 ? 'true' : 'false');
    if (staleDays > 14) {
      await expect(row.getByTestId('stale-' + id)).toContainText(`Stale · ${staleDays}d behind cutoff`);
    }
    for (const period of ['1w', '1m', '3m', '1y', '2y', '3y']) {
      const cell = row.getByTestId(`cell-${id}-${period}`);
      await expect(cell).toBeVisible();
      await expect(cell).toHaveText(/—|[+-]\d+\.\d%/);
    }
    expect(await row.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(2);
  }

  const narrow = (page.viewportSize()?.width ?? 1280) < 768;
  for (const label of ['1W', '1M', '3M', '1Y', '2Y', '3Y']) {
    await fleet.getByRole('button', { name: label, exact: true }).click();
    if (narrow) {
      await expect(fleet.getByRole('group', { name: 'Sort ranking by horizon' })
        .getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', 'true');
    } else {
      await expect(fleet.getByRole('columnheader', { name: label, exact: true })).toHaveAttribute('aria-sort', 'descending');
    }
  }
  await expect(fleet.getByText(/[-+]0\.0%/)).toHaveCount(0);

  const cn = sources.find(source => String(source.record.model_version_id).startsWith('cn_27'));
  expect(cn).toBeTruthy();
  expect(cn!.staleDays).toBeGreaterThan(14);
  await expect(fleet.getByTestId('fleet-' + cn!.record.model_version_id))
    .toContainText(`Stale · ${cn!.staleDays}d behind cutoff`);
  await expect(fleet.getByTestId('fleet-' + cn!.record.model_version_id)).toContainText(`As of ${cn!.last}`);

  const us = sources.find(source => String(source.record.model_version_id).startsWith('us_x'));
  expect(us).toBeTruthy();
  const usWeek = fleet.getByTestId('fleet-' + us!.record.model_version_id).getByTestId(`cell-${us!.record.model_version_id}-1w`);
  await expect(usWeek).toContainText('—');
  await expect(usWeek).toHaveAttribute('title', /no measured return is shown|denser series/);

  await expect(fleet.getByTestId('ranking-index-us-QQQ').getByRole('link', { name: /Price history/ }))
    .toHaveAttribute('href', /\/securities\/us\/QQQ$/);
  await expect(fleet.getByTestId('ranking-index-cn-000300')).toContainText('CSI 300');
  expect(marketEvidence).not.toEqual([]);
  expect(extraSections).toEqual([]);
  expect(retiredRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  expect(errors).toEqual([]);
  await fleet.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('fleet-period-evidence.png'), fullPage: false });
});

test('strategy navigation reuses verified formal sections without loading them on overview', async ({ page }, testInfo) => {
  const sections: string[] = [];
  const retiredRequests: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/\/bundle\//.test(path) || path.includes('/data/model-runs/')) retiredRequests.push(path);
    if (path.includes('/data/formal-model-runs/') && /\/(performance|risk|robustness|portfolio|trades|attribution|diagnostics|lineage)\.json$/.test(path)) sections.push(path);
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/strategies');
  const strategy = page.getByRole('region', { name: 'Formal strategy fleet' }).getByRole('link', { name: 'QQQR v4.3', exact: true }).first();
  await expect(strategy).toBeVisible();
  expect(sections).toHaveLength(0);
  await strategy.click();
  await expect(page.getByRole('tablist', { name: 'Formal backtest evidence views' })).toBeVisible();
  expect(sections).toHaveLength(8);
  expect(sections.filter(path => path.endsWith('/performance.json'))).toHaveLength(1);
  await page.getByRole('main').getByRole('link', { name: 'Overview', exact: true }).click();
  await page.goto('/#/strategies');
  await strategy.click();
  await expect(page.getByRole('tablist', { name: 'Formal backtest evidence views' })).toBeVisible();
  expect(sections).toHaveLength(8);
  await page.getByRole('button', { name: 'Benchmark comparisons', exact: true }).click();
  await expect(page.getByText('Benchmarks & comparisons', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Search benchmarks', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Compare QQQ', exact: true, pressed: true })).toBeVisible();
  expect(retiredRequests).toEqual([]);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('retained-benchmark-comparisons.png'), fullPage: false });
});

test('formal QQQ evidence stays public while current operations follow account policy', async ({ page }) => {
  await installMembershipFixture(page, { loading: false, isPro: false, user: { id: 'free-fixture' } });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await expect(page.getByRole('main').getByRole('heading', { name: 'QQQR v4.3', level: 1, exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Current holdings and live signals are protected', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Performance, risk, holdings and attribution', exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Performance', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Current decision state' })).toHaveCount(0);
});

test('strategy detail separates source metrics from chart observations and keeps the declared benchmark', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/strategies/us_x1_3');
  const assessment = page.getByRole('region', { name: 'Research tracking assessment' });
  await expect(assessment).toContainText('Continuing effectiveness awaits review.');
  await assessment.getByText('Supporting evidence, counterevidence, limits and next validation', { exact: true }).click();
  for (const name of ['Supporting evidence', 'Gates', 'Counterevidence', 'Interpretation limits', 'Next permitted validation']) {
    await expect(assessment.getByRole('heading', { name, exact: true })).toBeVisible();
  }
  await expect(assessment).toContainText('Research only.');
  await expect(assessment).toContainText('Formal evidence through');
  expect(await assessment.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(2);
  await assessment.getByRole('heading', { name: 'Supporting evidence', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('formal-evidence-review.png') });
  await assessment.getByRole('heading', { name: 'Next permitted validation', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('formal-evidence-next-validation.png') });
  const scope = page.getByRole('region', { name: 'Published metric scope' });
  await expect(scope).toContainText('source return observations');
  await expect(scope).toContainText('non-provisional through');
  await expect(scope).toContainText('provisional (unsettled marks)');
  await expect(page.getByTestId('chart-return-basis')).toContainText('not the published source return');
  const catalog = await (await page.request.get('/data/formal-model-runs/catalog.json')).json() as FormalCatalog;
  const record = catalog.records?.find(row => row.model_version_id === 'us_x1_3');
  expect(record?.manifest_path).toBeTruthy();
  const base = '/data/formal-model-runs/' + String(record?.manifest_path).replace(/manifest\.json$/, '');
  const manifest = await (await page.request.get(base + 'manifest.json')).json() as FormalManifest;
  const performancePath = manifest.sections?.find(section => section.section_id === 'performance')?.path;
  const response = await page.request.get(base + performancePath);
  expect(response.ok()).toBeTruthy();
  const performance = await response.json() as { public_evidence_context?: unknown };
  if (performance.public_evidence_context) {
    await expect(page.getByTestId('chart-return-basis')).toContainText('includes the first interval');
    await expect(scope).toContainText('Source opening wealth');
    await expect(scope).toContainText('excludes provisional marks');
  } else {
    await expect(page.getByTestId('chart-return-basis')).toContainText('excludes the interval ending at that observation');
    await expect(scope).not.toContainText('Source opening wealth');
    await expect(scope).toContainText('The declared run window does not identify every metric');
  }
  await expect(page.getByTestId('chart-return-basis')).toContainText('provisional observation(s)');
  await expect(page.getByTestId('visible-period-dates')).toContainText('Chart comparison');
  await page.getByTestId('chart-return-basis').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('us-chart-return-scope.png'), fullPage: false });

  await page.goto('/#/strategies/byd_v1_3_recovery_event_low_vol_confirmation_v1');
  await expect(page.getByTestId('equity-curve-container')).toHaveAttribute('data-default-benchmark', 'BYD v1.2');
  await expect(page.getByTestId('visible-benchmark-return')).not.toHaveText('—');
  await expect(page.getByTestId('visible-excess-return')).not.toHaveText('—');
  await expect(page.getByTestId('chart-return-basis')).toContainText('not the published source return');
  await page.getByRole('button', { name: 'Benchmark comparisons', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Compare BYD v1.2', exact: true, pressed: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Compare BYD', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Benchmark comparisons', exact: true }).click();
  await page.getByTestId('chart-return-basis').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('byd-declared-benchmark.png'), fullPage: false });
  expect(errors).toEqual([]);
});

test('retired product views have no alternate execution path', async ({ page }) => {
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/runs');
  await expect(page.getByRole('heading', { name: 'View unavailable', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Open overview', exact: true }).click();
  await expect(page).toHaveURL(/#\/app$/);
});

test('retiring offline support clears only Alpha Engine caches and registrations', async ({ page }) => {
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/app');
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  await page.evaluate(async () => {
    const activate = async (scope: string) => {
      const registration = await navigator.serviceWorker.register('/legacy-worker.js?scope=' + encodeURIComponent(scope), { scope });
      const worker = registration.installing || registration.waiting || registration.active;
      if (!worker) throw new Error('Fixture worker was not created');
      await new Promise<void>(resolve => {
        const check = () => { if (worker.state === 'activated') resolve(); };
        worker.addEventListener('statechange', check);
        check();
      });
    };
    await activate('/');
    await activate('/other-project/');
    await (await caches.open('alpha-engine-shell-v5')).put('/sentinel', new Response('old shell'));
    await (await caches.open('other-project-shell')).put('/sentinel', new Response('retain'));
  });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).map(row => new URL(row.scope).pathname))).toEqual(['/other-project/']);
  await expect.poll(() => page.evaluate(async () => (await caches.keys()).includes('alpha-engine-shell-v5'))).toBe(false);
  expect(await page.evaluate(async () => (await caches.keys()).includes('other-project-shell'))).toBe(true);
});
