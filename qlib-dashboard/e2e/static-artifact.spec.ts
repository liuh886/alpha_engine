import { expect, test, type Page } from '@playwright/test';

interface FormalCatalogRecord {
  model_family_id: string;
  model_version_id: string;
  run_id: string;
  manifest_path: string;
}

interface FormalCatalog {
  records: FormalCatalogRecord[];
}

interface FormalManifestSection {
  section_id: string;
  availability_status: string;
  path: string | null;
}

interface FormalManifest {
  model_family_id: string;
  model_version_id: string;
  run_id: string;
  evidence_cutoff: string;
  sections: FormalManifestSection[];
}

interface FormalSummary {
  display_name?: string;
  model_version_id?: string;
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

async function installMembershipFixture(
  page: Page,
  state: { loading: boolean; isPro: boolean; user: { id: string } | null },
) {
  await page.addInitScript((fixture) => {
    const listeners = new Set<(value: typeof fixture) => void>();
    let current = fixture;
    Object.defineProperty(window, '__alphaEngineMembership', {
      configurable: true,
      value: {
        subscribe(listener: (value: typeof fixture) => void) {
          listeners.add(listener);
          listener(current);
          return () => listeners.delete(listener);
        },
        getSnapshot() { return current; },
        signIn() {
          current = { ...current, user: { id: 'signed-in-fixture' } };
          listeners.forEach((listener) => listener(current));
        },
        signOut() {
          current = { ...current, user: null, isPro: false };
          listeners.forEach((listener) => listener(current));
        },
      },
    });
  }, state);
}

async function formalStrategyNames(page: Page): Promise<string[]> {
  const catalogResponse = await page.request.get('/data/formal-model-runs/catalog.json');
  expect(catalogResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json() as FormalCatalog;
  const names: string[] = [];
  for (const record of catalog.records) {
    const manifestResponse = await page.request.get(`/data/formal-model-runs/${record.manifest_path}`);
    expect(manifestResponse.ok()).toBeTruthy();
    const manifest = await manifestResponse.json() as FormalManifest;
    const summarySection = manifest.sections.find((section) => section.section_id === 'summary');
    expect(summarySection?.availability_status).toBe('available');
    expect(summarySection?.path).toBeTruthy();
    const base = record.manifest_path.includes('/')
      ? record.manifest_path.slice(0, record.manifest_path.lastIndexOf('/') + 1)
      : '';
    const summaryResponse = await page.request.get(`/data/formal-model-runs/${base}${summarySection!.path}`);
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

test('Security Explorer requires sign-in and remains available to Free accounts', async ({ page }) => {
  const marketEvidenceRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/data/market-evidence/')) marketEvidenceRequests.push(request.url());
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });

  await page.goto('/#/securities');
  await expect(page.getByRole('heading', { name: 'Sign in to open Security Explorer' })).toBeVisible();
  await expect(page.getByText('AlphaEngine Pro is not required.')).toBeVisible();
  expect(marketEvidenceRequests).toEqual([]);

  await page.evaluate(() => {
    const membership = window as unknown as { __alphaEngineMembership: { signIn(): void } };
    membership.__alphaEngineMembership.signIn();
  });
  await expect(page.getByRole('heading', { name: 'Security Explorer' })).toBeVisible();
  await expect.poll(() => marketEvidenceRequests.length).toBeGreaterThan(0);
});

test('Free users see an explicit Pro product gate for an advanced model', async ({ page }) => {
  await installMembershipFixture(page, { loading: false, isPro: false, user: { id: 'free-fixture' } });
  await page.goto('/#/strategies');
  await page.getByRole('region', { name: 'Formal strategy fleet' }).getByText('QQQR v4.3', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'QQQR v4.3 is a Pro product' })).toBeVisible();
  await expect(page.getByText('This product requires an active AlphaEngine Pro subscription.')).toBeVisible();
});

test('only a verified Owner can open access settings', async ({ page }) => {
  await installMembershipFixture(page, { loading: false, isPro: false, user: { id: 'owner-fixture' } });
  await page.addInitScript(() => {
    localStorage.setItem('alpha-engine-owner-fixture', 'true');
  });
  await page.goto('/#/app');
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
});

async function openConsole(page: Page) {
  await page.goto('/#/app');
  await expect(page.locator('#root')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  await expect(page.locator('.research-context-bar').getByText('Static Browser Fixture', { exact: true })).toBeVisible();
}

test('product homepage opens the strategy console', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/#/');
  await expect(page.getByRole('heading', { name: 'Know what your systematic strategy is doing — and why.' })).toBeVisible();
  await expect(page.getByText('QQQR v4.3', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Performance before persuasion.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Every decision is traceable.' })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: `test-results/static-artifact/landing-${testInfo.project.name}.png`, fullPage: true });

  await page.locator('.landing-actions').getByRole('link', { name: 'Open console' }).click();
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
});

test('strategy console exposes four primary destinations and formal strategy drill-down', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith('/api/') || pathname.startsWith('/auth/')) apiRequests.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await installMembershipFixture(page, { loading: false, isPro: true, user: { id: 'pro-fixture' } });
  await openConsole(page);
  const formalNames = await formalStrategyNames(page);
  const expectedTopLevel = ['Overview', 'Strategies', 'Securities', 'Research'];
  for (const label of expectedTopLevel) {
    await expect(page.getByRole('link', { name: label, exact: true }).first()).toBeVisible();
  }
  for (const modelName of formalNames) {
    await expect(page.getByText(modelName, { exact: true }).first()).toBeVisible();
  }
  await assertNoHorizontalOverflow(page);
  expect(apiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: `test-results/static-artifact/app-${testInfo.project.name}.png`, fullPage: true });
});

test('installed shell reopens offline after first visit', async ({ page, context }) => {
  test.skip(test.info().project.name !== 'desktop', 'Offline PWA acceptance only runs once on desktop.');
  await page.goto('/#/app');
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
  await page.waitForFunction(async () => {
    if (!('serviceWorker' in navigator)) return false;
    const registrations = await navigator.serviceWorker.getRegistrations();
    return registrations.length > 0;
  });

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
});
