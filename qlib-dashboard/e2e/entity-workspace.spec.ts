import { expect, test } from '@playwright/test';

const DISCLOSURE = 'Historical research evidence, not a live signal or fill.';

async function expectOneShell(page: import('@playwright/test').Page, kind: string) {
  const workspace = page.getByTestId('entity-workspace');
  await expect(workspace).toBeVisible();
  await expect(workspace).toHaveAttribute('data-entity-kind', kind);
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
  await expect(page.getByTestId('entity-header')).toBeVisible();
  await expect(page.getByTestId('entity-kind-badge')).toBeVisible();
  await expect(page.getByTestId('entity-facts')).toContainText('Research only · Not trade ready');
  await expect(page.getByTestId('entity-chart-disclosure')).toHaveText(DISCLOSURE);
  await expect(page.getByTestId('entity-back')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
}

async function capture(page: import('@playwright/test').Page, testInfo: import('@playwright/test').TestInfo, name: string) {
  await page.screenshot({ path: testInfo.outputPath(`${name}-light-${testInfo.project.name}.png`), fullPage: false });
  await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.screenshot({ path: testInfo.outputPath(`${name}-dark-${testInfo.project.name}.png`), fullPage: false });
}

test('the model detail page uses the shared entity workspace shell', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');

  await expectOneShell(page, 'model');
  await expect(page.getByTestId('entity-kind-badge')).toHaveText('Model');
  await expect(page.getByTestId('entity-title')).toHaveText('QQQR v4.3');
  await expect(page.getByTestId('entity-back')).toHaveAttribute('href', '#/app');
  await expect(page.getByTestId('entity-facts')).toContainText('Evidence cutoff');
  await expect(page.getByTestId('entity-facts')).toContainText('Benchmark');

  // The model renderer stays the NAV chart inside the shared panel frame.
  const panel = page.getByTestId('strategy-chart-hero');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('group', { name: 'Chart horizon' })).toBeVisible();
  await expect(page.getByTestId('strategy-nav-chart')).toBeVisible();
  await expect(page.getByTestId('entity-evidence-sections')).toBeVisible();

  await panel.scrollIntoViewIfNeeded();
  await capture(page, testInfo, 'entity-workspace-model');
  expect(errors).toEqual([]);
});

test('the instrument detail page uses the same shell with the price renderer', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/securities/us/AAPL');

  await expectOneShell(page, 'instrument');
  await expect(page.getByTestId('entity-kind-badge')).toHaveText('Instrument');
  await expect(page.getByTestId('entity-title')).toHaveText('AAPL');
  await expect(page.getByTestId('entity-back')).toHaveAttribute('href', '#/app');
  await expect(page.getByTestId('entity-facts')).toContainText('Selected pool candidate');

  const panel = page.getByTestId('security-history-chart');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('group', { name: 'Security chart range' })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'US baseline: No baseline', exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: /US indicators:/ })).toBeVisible();
  await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
  await expect(page.getByTestId('entity-evidence-sections')).toBeVisible();

  await panel.scrollIntoViewIfNeeded();
  await capture(page, testInfo, 'entity-workspace-instrument');
  expect(errors).toEqual([]);
});

test('index and reference pages take their badge from the governed catalog roles', async ({ page }) => {
  await page.goto('/#/securities/us/QQQ');
  await expectOneShell(page, 'index');
  await expect(page.getByTestId('entity-kind-badge')).toHaveText('Index');
  await expect(page.getByTestId('entity-facts')).toContainText('Market benchmark');
  await expect(page.getByTestId('entity-role-context')).toContainText('Market benchmark');
  await expect(page.getByTestId('entity-role-kind')).toHaveText('Index');
  // QQQ is formally traded, so its real bound events stay on the ledger.
  await expect(page.getByRole('region', { name: 'Historical model event ledger' })).toBeVisible();

  const catalogResponse = await page.request.get('/data/market-evidence/us/catalog.json');
  expect(catalogResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json() as { symbols?: Array<{ symbol?: string; roles?: string[] }> };
  const spx = (catalog.symbols ?? []).find(row => row.symbol === 'SPX');

  if (spx) {
    await page.goto('/#/securities/us/SPX');
    await expectOneShell(page, 'reference');
    await expect(page.getByTestId('entity-kind-badge')).toHaveText('Reference');
    await expect(page.getByTestId('entity-facts')).toContainText('Formal auxiliary');
    await expect(page.getByTestId('entity-role-context')).toContainText('Formal auxiliary');
    // No model evidence is attached when the catalog binds none.
    await expect(page.getByRole('region', { name: 'Historical model event ledger' })).toHaveCount(0);
    await expect(page.getByText('No retained model events for this instrument and selection.')).toHaveCount(0);
    await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
  }
});
