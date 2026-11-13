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
  await expect(page.getByRole('columnheader', { name: 'Excess' })).toHaveAttribute('aria-sort', 'descending');
  await expect(page.getByRole('columnheader', { name: '1M' })).toHaveAttribute('aria-sort', 'none');

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
