import { expect, test, type Page } from '@playwright/test';

type FormalCatalog = { records?: Array<{ manifest_path?: string; model_version_id?: string; evidence_cutoff?: string }> };
type FormalManifest = { comparability_key?: { start: string; end: string }; sections?: Array<{ section_id?: string; availability_status?: string; path?: string }> };
type FormalSummary = { display_name?: string; model_version_id?: string };

interface MembershipFixture {
  loading: boolean;
  isPro: boolean;
  user: { id: string; app_metadata?: { alpha_engine_role?: string } } | null;
}

async function installMembershipFixture(page: Page, initial: MembershipFixture): Promise<void> {
  await page.route('**/admin/shared/account-shell.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.addInitScript((snapshot) => {
    let current = snapshot;
    const listeners = new Set<(value: MembershipFixture) => void>();
    const policies = [
      { product_code: 'alpha_engine', resource_type: 'module', resource_id: 'securities', required_tier: 'authenticated', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'qqq_rotation', required_tier: 'pro', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'us_x', required_tier: 'public', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'cn_x', required_tier: 'public', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'byd', required_tier: 'public', updated_at: '2026-08-12T00:00:00Z' },
    ];
    (window as any).HaoAccount = {
      getState: () => current,
      open: () => undefined,
      subscribe: (listener: (value: MembershipFixture) => void) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      getClient: async () => ({
        from: (table: string) => {
          if (table === 'product_access_policies') {
            return {
              select: () => ({
                eq: async () => ({ data: policies, error: null }),
              }),
            };
          }
          return {
            select: () => {
              const query: any = {
                eq: () => query,
                maybeSingle: async () => ({ data: null, error: null }),
              };
              return query;
            },
            upsert: async () => ({ error: null }),
          };
        },
      }),
    };
    (window as any).__setAlphaMembership = (next: MembershipFixture) => {
      current = next;
      listeners.forEach((listener) => listener(current));
    };
  }, initial);
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
    if (/\/bundle\/|\/data\/model-runs\/|\/data\/market-evidence\//.test(request.url())) retiredRequests.push(request.url());
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/');
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  const names = await loadFormalDisplayNames(page);
  await expect(brief.getByRole('article')).toHaveCount(Math.min(3, names.length));
  const fleet = page.getByRole('region', { name: 'Formal strategy fleet' });
  await expect(fleet.getByRole('article')).toHaveCount(names.length);
  for (const name of names) await expect(fleet.getByRole('button', { name: `Open ${name} strategy detail`, exact: true }).first()).toBeVisible();
  if (testInfo.project.name === 'mobile') await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('tab')).toHaveCount(2);
  else await expect(page.getByRole('navigation', { name: 'Strategy console navigation' }).getByRole('link')).toHaveCount(2);
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

test('fleet periods retain visible evidence windows and do not promote expired returns', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/app');
  const fleet = page.getByRole('region', { name: 'Formal strategy fleet' });
  await expect(fleet.getByRole('article')).toHaveCount(4);
  const catalog = await (await page.request.get('/data/formal-model-runs/catalog.json')).json() as FormalCatalog;
  const sources = await Promise.all((catalog.records ?? []).map(async record => {
    const base = '/data/formal-model-runs/' + String(record.manifest_path).replace(/manifest\.json$/, '');
    const manifest = await (await page.request.get(base + 'manifest.json')).json() as FormalManifest;
    const summaryPath = manifest.sections?.find(section => section.section_id === 'summary')?.path;
    const performancePath = manifest.sections?.find(section => section.section_id === 'performance')?.path;
    const summary = await (await page.request.get(base + summaryPath)).json() as { metrics: Array<{ metric_id: string; availability_status: string; unavailable_reason?: string }> };
    const performance = await (await page.request.get(base + performancePath)).json() as { report: Array<{ date: string; holding_end_date?: string }>; public_evidence_context?: { total_return_window: { start: string; end: string; sample_count: number } } };
    const row = fleet.getByTestId('fleet-' + record.model_version_id);
    const sourceWindow = performance.public_evidence_context?.total_return_window;
    await expect(row.locator('[data-testid="fleet-window"]:visible')).toContainText(sourceWindow
      ? `Source return window ${sourceWindow.start} – ${sourceWindow.end}`
      : `Declared run window ${manifest.comparability_key?.start} – ${manifest.comparability_key?.end}`);
    expect(await row.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(2);
    const excess = summary.metrics.find(metric => metric.metric_id === 'excess_return');
    if (excess?.availability_status !== 'available') {
      await expect(row).toContainText('Excess unavailable:');
      if (excess?.unavailable_reason) await expect(row).toContainText(excess.unavailable_reason);
    }
    return { record, performance };
  }));
  await fleet.getByRole('button', { name: '1M', exact: true }).click();
  await expect(fleet.getByRole('note')).toContainText('Drawdown uses retained wealth marks');
  for (const { record, performance } of sources) {
    const row = fleet.getByTestId('fleet-' + record.model_version_id);
    const last = performance.report[performance.report.length - 1];
    const end = last.holding_end_date ?? last.date;
    const cutoff = new Date(String(record.evidence_cutoff) + 'T00:00:00Z');
    const day = cutoff.getUTCDate();
    cutoff.setUTCDate(1); cutoff.setUTCMonth(cutoff.getUTCMonth() - 1);
    cutoff.setUTCDate(Math.min(day, new Date(Date.UTC(cutoff.getUTCFullYear(), cutoff.getUTCMonth() + 1, 0)).getUTCDate()));
    const expired = end <= cutoff.toISOString().slice(0, 10);
    await expect(row.locator('[data-testid="fleet-window"]:visible')).toContainText(`– ${end}`);
    expect(await row.evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(2);
    expect(await row.locator('[data-testid="fleet-window"]:visible').evaluate(element => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(2);
    await expect(row).toHaveAttribute('data-window-status', expired ? 'expired' : 'observed');
    if (expired) {
      await expect(row).toContainText('Window expired');
      await expect(row).toContainText('Period metrics unavailable:');
      expect(await row.getByTestId('fleet-return').allTextContents()).toEqual(['—', '—']);
    }
  }
  await expect(fleet.getByText(/[-+]0\.0%/)).toHaveCount(0);
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
    if (path.includes('/data/market-evidence/')) retiredRequests.push(path);
    if (path.includes('/data/formal-model-runs/') && /\/(performance|risk|robustness|portfolio|trades|attribution|diagnostics|lineage)\.json$/.test(path)) sections.push(path);
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/app');
  const strategy = page.getByRole('region', { name: 'Formal strategy fleet' }).getByRole('button', { name: 'Open QQQR v4.3 strategy detail', exact: true }).first();
  await expect(strategy).toBeVisible();
  expect(sections).toHaveLength(0);
  await strategy.click();
  await expect(page.getByRole('tablist', { name: 'Formal backtest evidence views' })).toBeVisible();
  expect(sections).toHaveLength(8);
  expect(sections.filter(path => path.endsWith('/performance.json'))).toHaveLength(1);
  await page.getByRole('main').getByRole('link', { name: 'Overview', exact: true }).click();
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
  await expect(assessment).toContainText('Evidence through');
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
  await expect(page.getByTestId('chart-return-basis')).toContainText('includes the first interval');
  await expect(scope).toContainText('Source opening wealth');
  await expect(scope).toContainText('excludes provisional marks');
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
  await page.goto('/#/research');
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
