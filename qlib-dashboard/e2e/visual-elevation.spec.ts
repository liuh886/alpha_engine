import { expect, test } from '@playwright/test';
import { installMembershipFixture } from './membership-fixture';

/**
 * Slice 9 visual contract. Every assertion is derived from published data or
 * live layout, never from a fixed pixel fixture of the whole page.
 */

test('Today keeps the verified-change summary above benchmark cards, ranking and brief', async ({ page }) => {
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/app');

  const summary = page.getByTestId('today-decision-summary');
  await expect(summary).toBeVisible();
  await expect(summary).not.toBeEmpty();
  await expect(summary).toHaveAttribute('role', 'status');

  const cards = page.getByRole('region', { name: 'Benchmark markets' });
  const ranking = page.getByRole('region', { name: 'Model ranking' });
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  for (const region of [cards, ranking, brief]) await expect(region).toBeVisible();

  const [summaryBox, cardsBox, rankingBox, briefBox] = await Promise.all([
    summary.boundingBox(), cards.boundingBox(), ranking.boundingBox(), brief.boundingBox(),
  ]);
  expect(summaryBox && cardsBox).toBeTruthy();
  expect((summaryBox!.y + summaryBox!.height)).toBeLessThanOrEqual(cardsBox!.y + 1);
  expect(cardsBox!.y).toBeLessThan(rankingBox!.y);
  expect(rankingBox!.y).toBeLessThan(briefBox!.y);
});

test('Today reports a completed read and keeps the access-gated brief compact and disclosed', async ({ page }) => {
  await page.goto('/#/app');

  const reader = page.getByRole('region', { name: 'Current operations reader' });
  const status = reader.getByRole('status');
  await expect(status).toContainText(/Checked \d{2}:\d{2} UTC · \d+ of \d+ observation reads succeeded/);
  await expect(status).not.toContainText('observations verified');

  const brief = page.getByRole('region', { name: 'Daily research brief' });
  await expect(brief.getByText(/Showing 3 of 4 priority observations/)).toBeVisible();
  await expect(brief.getByText(/Every strategy stays in the model ranking above with its own as-of date/)).toBeVisible();
  await expect(brief.getByRole('button', { name: 'Check strategy access' })).toHaveCount(1);

  const accessRows = brief.getByRole('article').filter({ has: page.getByText('Access required', { exact: true }) });
  await expect(accessRows).toHaveCount(3);
  const firstAccess = accessRows.first();
  await expect(firstAccess.getByText('Access required', { exact: true })).toBeVisible();
  await expect(firstAccess).toContainText(/Formal evidence as of \d{4}-\d{2}-\d{2}/);
  await expect(firstAccess).toContainText('Review: Review state not verified');
  await expect(firstAccess).not.toContainText('Current observations require strategy access.');
});

test('the full ranking exposes metric sorts, row details and value-basis disclosures', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'Mobile uses the card layout covered by the handset test.');
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/strategies');

  for (const header of ['1W', '1M', '3M', '1Y', '2Y', '3Y', 'Excess', 'Max DD', 'Signal']) {
    await expect(page.getByRole('button', { name: header, exact: true })).toBeVisible();
  }
  await page.getByRole('button', { name: 'Excess', exact: true }).click();
  await expect(page.getByRole('columnheader', { name: 'Excess', exact: true })).toHaveAttribute('aria-sort', 'descending');
  await expect(page.getByRole('columnheader', { name: '1M', exact: true })).toHaveAttribute('aria-sort', 'none');

  const firstRow = page.getByTestId(/^fleet-/).first();
  const details = firstRow.getByRole('button', { name: /Row details/ });
  await expect(details).toHaveAttribute('aria-expanded', 'false');
  await details.click();
  await expect(details).toHaveAttribute('aria-expanded', 'true');
  const panel = page.locator('[id^="row-details-"]').first();
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Retained window');

  const basis = firstRow.locator('summary').filter({ has: page.getByText('retained', { exact: true }) }).first();
  if (await basis.count()) {
    await basis.click();
    await expect(basis.locator('..')).toHaveAttribute('open');
  }
});

test('the NAV chart announces the hovered date and draws a horizontal crosshair', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'Touch projects do not have a stable hover pointer.');
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  const chart = page.locator('.recharts-wrapper').first();
  await expect(chart).toBeVisible();
  const box = await chart.boundingBox();
  expect(box).toBeTruthy();
  await chart.hover({ position: { x: box!.width * 0.55, y: box!.height * 0.5 } });
  await expect(page.getByTestId('nav-chart-tooltip-date')).toBeVisible();
  await expect(page.getByTestId('nav-chart-tooltip-date')).toHaveText(/\w{3} \d{1,2}, \d{4}/);
  await expect(page.getByTestId('nav-chart-tooltip')).toContainText('Observation date');
  await expect(page.locator('.nav-chart-hover-line')).toHaveCount(1);
  await page.mouse.move(0, 0);
  await expect(page.locator('.nav-chart-hover-line')).toHaveCount(0);
});

test('the security ledger uses readable actions and reasons while retaining raw ids', async ({ page }) => {
  await page.goto('/#/securities/us/QQQ');
  await expect(page.getByRole('heading', { name: 'QQQ', exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Show complete ledger' }).check();
  const ledger = page.getByRole('region', { name: 'Historical model event ledger' });
  const firstRow = ledger.locator('tbody tr').first();
  const action = firstRow.locator('td').nth(2);
  await expect(action).toHaveText(/^(Buy|Sell|Increase|Decrease)$/);
  const reason = firstRow.locator('td').nth(4).locator('span[title]').first();
  await expect(reason).toBeVisible();
  const raw = await reason.getAttribute('title');
  expect(raw).toMatch(/_/);
  await expect(reason).not.toContainText('_');
  await expect(firstRow).not.toContainText('No reason retained');

  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'Operating Status', exact: true })).toBeVisible();
  await expect(page.getByText('Source degraded', { exact: true })).toHaveCount(0);
});

test('the as-of sort sits inline beside the Model label instead of reading as an empty column', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'The ranking table is replaced by cards on handsets.');
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  for (const path of ['/#/app', '/#/strategies']) {
    await page.goto(path);
    const header = page.getByRole('columnheader', { name: /Model/ }).first();
    const button = header.getByRole('button', { name: 'Sort by as-of freshness' });
    await expect(header).toBeVisible();
    await expect(button).toBeVisible();

    // There is no second, phantom AS OF column: exactly one header owns the control.
    await expect(page.getByRole('columnheader', { name: /^As of/ })).toHaveCount(0);
    await expect(page.getByRole('columnheader').filter({ has: page.getByRole('button', { name: 'Sort by as-of freshness' }) })).toHaveCount(1);

    const [labelBox, buttonBox, headerBox] = await Promise.all([
      header.getByText('Model', { exact: true }).boundingBox(),
      button.boundingBox(),
      header.boundingBox(),
    ]);
    expect(labelBox && buttonBox && headerBox).toBeTruthy();
    const inlineGap = buttonBox!.x - (labelBox!.x + labelBox!.width);
    expect(inlineGap, 'the control follows the Model label in one inline cluster').toBeGreaterThanOrEqual(-1);
    expect(inlineGap, 'the control is not separated from its label').toBeLessThanOrEqual(16);
    const trailingGap = headerBox!.x + headerBox!.width - (buttonBox!.x + buttonBox!.width);
    expect(trailingGap, 'the control is not pushed to the far edge of the wide Model column').toBeGreaterThan(80);

    await button.click();
    await expect(header).toHaveAttribute('aria-sort', 'descending');
    await expect(button).toHaveAttribute('aria-pressed', 'true');
    await expect(button).toHaveClass(/underline/);
  }
});

test('the visible-range price data disclosure is keyboard reachable and bounded', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'The handset chart is covered by the handset layout test.');
  await page.goto('/#/securities/us/QQQ');
  await expect(page.getByRole('heading', { name: 'QQQ', exact: true })).toBeVisible();
  const details = page.getByTestId('price-data');
  await expect(details).toBeVisible();
  await expect(details).not.toHaveAttribute('open', '');
  const summary = details.locator('summary');
  await expect(summary).toHaveText('View price data table');
  await summary.press('Enter');
  await expect(details).toHaveAttribute('open', '');

  await expect(details.locator('thead th')).toHaveText(['Date', 'Open', 'High', 'Low', 'Close', 'Volume']);
  const rows = details.locator('tbody tr');
  const rowCount = await rows.count();
  expect(rowCount, 'the DOM is bounded to the most recent 120 sessions').toBeGreaterThan(0);
  expect(rowCount).toBeLessThanOrEqual(120);
  await expect(rows.first().locator('th')).toHaveText(/^\d{4}-\d{2}-\d{2}$/);
  await expect(details.locator('p')).toContainText(/Showing (the most recent 120 of \d+|all \d+) visible-range session/);
  await expect(details.locator('p')).toContainText('Raw OHLCV, not split or dividend adjusted.');
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(2);
});

test('the baseline comparison announces loading through a chart-shaped status, not a bare sentence', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One deterministic loading check is enough for the consent-free static artifact.');
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/data/market-evidence/cn/symbols/000300.json', async route => {
    await gate;
    await route.continue();
  });
  try {
    await page.goto('/#/securities/cn/002594');
    await expect(page.getByRole('heading', { name: 'BYD · 002594' })).toBeVisible();
    await expect(page.getByTestId('security-lightweight-chart-container')).toBeVisible();
    const mode = page.getByRole('group', { name: 'Security chart mode' });
    await mode.getByRole('button', { name: 'vs baseline', exact: true }).click();

    const skeleton = page.getByTestId('security-chart-loading');
    await expect(skeleton).toBeVisible();
    await expect(skeleton).toHaveAttribute('role', 'status');
    await expect(skeleton).toHaveAttribute('aria-busy', 'true');
    await expect(skeleton).toContainText('Loading CSI 300');
    await expect(skeleton).toContainText('baseline evidence');
    // The loaded chart remains the same single instance; the skeleton is only an overlay.
    await expect(page.getByTestId('security-lightweight-chart-container')).toHaveCount(1);
    await expect(page.getByTestId('security-chart-empty')).toHaveCount(0);
  } finally {
    release();
  }
  await expect(page.getByTestId('security-chart-loading')).toHaveCount(0);
  await expect(page.getByTestId('security-chart-baseline')).toContainText('CSI 300 (000300.SH)');
});

test('a handset context bar wraps without clipping and every destination keeps its width', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'Handset-specific width.');
  await page.setViewportSize({ width: 390, height: 844 });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });

  for (const path of ['/#/app', '/#/strategies', '/#/securities/us/QQQ', '/#/system', '/#/research']) {
    await page.goto(path);
    await expect(page.getByRole('main')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
      `${path} keeps the page inside the 390px viewport`).toBeLessThanOrEqual(2);
  }

  await page.goto('/#/app');
  const bar = page.getByRole('status', { name: 'Strategy fleet context' });
  await expect(bar).toContainText('Formal strategy fleet · 4 strategies');
  await expect(bar).toContainText('Evidence cutoffs shown per strategy');
  const metrics = await bar.evaluate(element => ({
    hiddenWidth: element.scrollWidth - element.clientWidth,
    clippedHeight: element.scrollHeight - element.clientHeight,
    height: element.getBoundingClientRect().height,
  }));
  expect(metrics.hiddenWidth, 'no clipped facts behind a hidden scrollbar').toBeLessThanOrEqual(2);
  expect(metrics.clippedHeight).toBeLessThanOrEqual(2);
  expect(metrics.height, 'at most two compact lines').toBeLessThanOrEqual(48);
});

test('handset Strategies brings the first ranking card forward with one sort row and 44px controls', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'Handset layout is asserted only in the mobile project.');
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  await page.goto('/#/strategies');
  const fold = page.viewportSize()?.height ?? 844;
  const firstCard = page.locator('main li[data-testid]').first();
  await expect(firstCard).toBeVisible();
  const cardBox = await firstCard.boundingBox();
  expect(cardBox).toBeTruthy();
  expect(cardBox!.y, 'first ranking card starts within one handset screen').toBeLessThan(fold);

  const firstStrategy = page.getByTestId(/^fleet-/).first();
  const strategyBox = await firstStrategy.boundingBox();
  expect(strategyBox, 'first formal strategy card').toBeTruthy();
  expect(strategyBox!.y, 'first strategy card lands within 1.2 handset screens').toBeLessThan(fold * 1.2);

  const sortGroup = page.getByRole('group', { name: 'Sort ranking by horizon' });
  const sortBox = await sortGroup.boundingBox();
  expect(sortBox!.height, 'sort controls stay on one vertically compact row').toBeLessThanOrEqual(60);

  for (const control of await page.locator('header, main').locator('button, summary, select').all()) {
    if (!(await control.isVisible())) continue;
    const box = await control.boundingBox();
    if (!box) continue;
    expect(box.height, `coarse-pointer target ${await control.innerText().catch(() => '')}`).toBeGreaterThanOrEqual(44);
  }

  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  const chart = page.getByTestId('strategy-nav-chart');
  await expect(chart).toBeVisible();
  const chartBox = await chart.boundingBox();
  const tile = page.getByTestId('hero-period-return');
  const tileBox = await tile.boundingBox();
  expect(chartBox && tileBox).toBeTruthy();
  expect(chartBox!.y, 'chart-first hero reaches the plot within one handset screen').toBeLessThan(fold);
  expect(chartBox!.y, 'chart precedes the numeric tiles on a handset').toBeLessThan(tileBox!.y);
});
