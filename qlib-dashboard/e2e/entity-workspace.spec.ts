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
  // A traded benchmark may list the models that traded/hold it.
  await expect(page.getByTestId('related-models')).toBeVisible();

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
    await expect(page.getByTestId('related-models')).toHaveCount(0);
    await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
  }
});

test('an instrument lists the bound models that traded or held it and opens one', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/securities/cn/002594');
  await expect(page.getByRole('heading', { name: 'BYD · 002594', exact: true })).toBeVisible();

  const panel = page.getByTestId('related-models');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('never inferred from event weights');
  await expect(panel.getByTestId('related-model')).toHaveCount(2);

  const byd = panel.locator('[data-model-id="byd_v1_3_recovery_event_low_vol_confirmation_v1"]');
  await expect(byd.getByTestId('related-model-events')).toContainText('106 retained events');
  await expect(byd.getByTestId('related-model-events')).toContainText('last Sell on 2026-08-04');
  const bydHolding = byd.getByTestId('related-model-holding');
  await expect(bydHolding).toContainText('Held at last publication · 75.0%');
  await expect(bydHolding).toContainText('as of 2026-11-13');
  await expect(bydHolding).toContainText('cutoff 2026-11-16');

  const cn27 = panel.locator('[data-model-id="cn_27_v1_3"]');
  await expect(cn27.getByTestId('related-model-events')).toContainText('9 retained events');
  await expect(cn27.getByTestId('related-model-events')).toContainText('last Sell on 2025-08-28');
  await expect(cn27.getByTestId('related-model-holding')).toContainText('Not held at last publication');

  // Each row is a keyboard-reachable 44px model route.
  const bydLink = byd.getByRole('link', { name: 'BYD v1.3', exact: true });
  await bydLink.focus();
  await expect(bydLink).toBeFocused();

  await panel.scrollIntoViewIfNeeded();
  await capture(page, testInfo, 'entity-workspace-related-models');

  await bydLink.click();
  await expect(page).toHaveURL(/#\/strategies\/byd_v1_3_recovery_event_low_vol_confirmation_v1$/);
  await expectOneShell(page, 'model');
  await expect(page.getByTestId('entity-title')).toHaveText('BYD v1.3');
  expect(errors).toEqual([]);
});

test('a model trade row links to its resolved instrument and keeps unresolved symbols plain text', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/strategies/byd_v1_3_recovery_event_low_vol_confirmation_v1');
  await page.getByRole('tab', { name: 'Trades', exact: true }).click();

  const link = page.getByRole('link', { name: 'View BYD price and model events', exact: true }).first();
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute(
    'href',
    '#/securities/cn/002594?model=byd_v1_3_recovery_event_low_vol_confirmation_v1',
  );

  // An unpublished trade symbol stays plain text with a short reason.
  const cash = page.getByTestId('security-link-unresolved').filter({ hasText: 'CASH' }).first();
  await expect(cash).toBeVisible();
  await expect(cash).toContainText('No published price history');
  await expect(page.getByRole('link', { name: 'View CASH price and model events' })).toHaveCount(0);
  // A CN model never links a US instrument.
  await expect(page.locator('a[href*="/securities/us/"]')).toHaveCount(0);

  await link.click();
  await expect(page).toHaveURL(/#\/securities\/cn\/002594/);
  await expect(page.getByRole('heading', { name: 'BYD · 002594', exact: true })).toBeVisible();
  await expect(page.getByTestId('related-models')).toBeVisible();
  await page.getByTestId('related-models').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`model-to-instrument-${testInfo.project.name}.png`), fullPage: false });
  expect(errors).toEqual([]);
});

test('a model page exposes retained-trade instrument links before any evidence tab is opened', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/strategies/byd_v1_3_recovery_event_low_vol_confirmation_v1');

  // The default view keeps the Performance tab mounted and no trade table.
  await expect(page.getByTestId('formal-backtest-review')).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Trades', exact: true })).toHaveAttribute('aria-selected', 'false');

  // The shell's related section is the always-visible model → instrument entry point.
  const panel = page.getByTestId('related-instruments');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('not inferred holdings');

  const linker = panel.getByRole('link', { name: 'View BYD price and model events', exact: true });
  await expect(linker).toBeVisible();
  await expect(linker).toHaveAttribute(
    'href',
    '#/securities/cn/002594?model=byd_v1_3_recovery_event_low_vol_confirmation_v1',
  );
  await expect(panel.getByTestId('related-instrument').filter({ hasText: 'BYD' })).toContainText('retained trades');

  // CASH is retained in the ledger but unpublished: plain text with a reason.
  await expect(panel.getByTestId('security-link-unresolved').filter({ hasText: 'CASH' })).toContainText('No published price history');
  await expect(panel.getByRole('link', { name: 'View CASH price and model events' })).toHaveCount(0);

  // Every instrument anchor on the default page is a well-formed, same-market route.
  const hrefs = await page.evaluate(() => [...document.querySelectorAll('a[href*="/securities/"]')]
    .map(anchor => anchor.getAttribute('href') ?? ''));
  expect(hrefs.length).toBeGreaterThan(0);
  for (const href of hrefs) {
    expect(href).toMatch(/^#\/securities\/cn\/[^/?#]+(?:\?model=[^#]+)?$/);
  }

  await panel.scrollIntoViewIfNeeded();
  await capture(page, testInfo, 'model-related-instruments');

  await linker.click();
  await expect(page).toHaveURL(/#\/securities\/cn\/002594/);
  await expect(page.getByRole('heading', { name: 'BYD · 002594', exact: true })).toBeVisible();
  await expect(page.getByTestId('related-models')).toBeVisible();
  expect(errors).toEqual([]);
});

test('a strategy chart adds one same-market model and keeps markers on the base only', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');

  const panel = page.getByTestId('strategy-chart-hero');
  await panel.scrollIntoViewIfNeeded();
  await expect(page.getByTestId('strategy-nav-chart')).toBeVisible();

  // The picker lists accepted same-market formal models only; the base model
  // never appears as its own overlay.
  const trigger = page.getByTestId('compare-control-trigger');
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveAccessibleName('US compare: 0 of 3 overlays');
  await trigger.click();
  await expect(page.getByTestId('compare-option-model:us:us_x1_3')).toBeVisible();
  await expect(page.getByTestId('compare-option-model:us:qqqi_qqq_tqqq_v4_3')).toHaveCount(0);

  await page.getByTestId('compare-option-model:us:us_x1_3').click();
  await page.keyboard.press('Escape');

  const overlay = page.getByTestId('compare-legend-model:us:us_x1_3');
  await expect(overlay).toBeVisible();
  await expect(overlay.getByRole('link', { name: 'US x1.3', exact: true }))
    .toHaveAttribute('href', '#/strategies/us_x1_3');
  await expect(page.getByTestId('compare-loading-model:us:us_x1_3')).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByTestId('compare-legend-base')).toContainText('base · indexed NAV');
  await expect(page.getByTestId('compare-legend-baseline')).toBeVisible();

  const disclosure = page.getByTestId('strategy-model-comparison-disclosure');
  await expect(disclosure).toContainText('2 same-market formal models');
  await expect(disclosure).toContainText('exact common window');
  await expect(disclosure).toContainText('historical research evidence, not a signal');
  await expect(disclosure).toContainText('base model (QQQR v4.3) only');
  await expect(page.getByTestId('nav-chart-marker-scope')).toContainText('base model (QQQR v4.3) only');

  // The overlay never breaks the one-axis / no-overflow contract.
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);

  await panel.scrollIntoViewIfNeeded();
  await capture(page, testInfo, 'strategy-model-comparison');
  expect(errors).toEqual([]);
});

test('the strategy chart plot stays above the 390x844 handset fold', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');

  const chart = page.getByTestId('strategy-nav-chart');
  await expect(chart).toBeVisible();
  const chartBox = await chart.boundingBox();
  const tileBox = await page.getByTestId('hero-period-return').boundingBox();
  expect(chartBox && tileBox).toBeTruthy();
  expect(chartBox!.y, 'chart top reaches the 390x844 first screen').toBeLessThan(844);
  expect(chartBox!.y, 'chart precedes the numeric tiles on a handset').toBeLessThan(tileBox!.y);
});
