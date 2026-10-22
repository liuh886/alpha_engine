import { expect, test, type Page } from '@playwright/test';

type FormalCatalog = { records?: Array<{ manifest_path?: string }> };
type FormalManifest = { sections?: Array<{ section_id?: string; availability_status?: string; path?: string }> };
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
  await expect(brief.getByRole('article')).toHaveCount(names.length);
  for (const name of names) await expect(brief.getByRole('link', { name, exact: true })).toBeVisible();
  if (testInfo.project.name === 'mobile') await expect(page.getByRole('navigation', { name: 'Primary' }).getByRole('tab')).toHaveCount(2);
  else await expect(page.getByRole('navigation', { name: 'Strategy console navigation' }).getByRole('link')).toHaveCount(2);
  expect(retiredRequests).toEqual([]);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
  await page.screenshot({ path: testInfo.outputPath('focused-daily-overview.png'), fullPage: false });
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
  const strategy = page.getByRole('region', { name: 'Daily research brief' }).getByRole('link', { name: 'QQQR v4.3', exact: true });
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
