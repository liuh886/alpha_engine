import { expect, test, type Page } from '@playwright/test';

const FORMAL_MODELS = ['QQQ Rotation v4.2', 'US x1.1', 'CN x1.0'] as const;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function openSelector(page: Page) {
  const trigger = page.getByRole('button', {
    name: /QQQ Rotation v4\.2|US x1\.1|CN x1\.0/,
  }).first();
  await expect(trigger).toBeVisible();
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Select formal baseline' })).toBeVisible();
  await expect(dialog.locator('tbody tr')).toHaveCount(3);
  for (const model of FORMAL_MODELS) {
    await expect(dialog.getByText(model, { exact: true })).toBeVisible();
  }
  await expect(dialog.getByText('US x1.0', { exact: true })).toHaveCount(0);
  return dialog;
}

async function selectModel(page: Page, model: typeof FORMAL_MODELS[number]): Promise<void> {
  const dialog = await openSelector(page);
  await dialog.locator('tbody tr').filter({ hasText: model }).click();
  await expect(page.getByRole('button', { name: new RegExp(escapeRegExp(model)) }).first()).toBeVisible();
  await expect(dialog).toBeHidden();
}

test('live Pages renders every governed formal baseline end to end', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const failedRequiredResponses: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('response', (response) => {
    const url = response.url();
    if (
      response.status() >= 400
      && (url.includes('/bundle/') || url.includes('/data/formal-backtests/') || url.includes('/assets/'))
    ) {
      failedRequiredResponses.push(`${response.status()} ${url}`);
    }
  });

  await page.goto(`?live_acceptance=${Date.now()}#/dashboard`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Complete backtest review' })).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Experiments', { exact: true })).toHaveCount(0);

  const initialDialog = await openSelector(page);
  await page.keyboard.press('Escape');
  await expect(initialDialog).toBeHidden();

  // QQQ Rotation v4.2: complete daily trace and evidence identity.
  await expect(page.getByRole('button', { name: /QQQ Rotation v4\.2/ }).first()).toBeVisible();
  const v42Curve = page.getByTestId('equity-curve-container');
  await expect(v42Curve).toBeVisible();
  const v42PointCount = Number(await v42Curve.getAttribute('data-strategy-point-count'));
  expect(v42PointCount).toBeGreaterThan(600);
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByText('Formal backtest evidence', { exact: true })).toBeVisible();
  await expect(page.getByText('Complete retained trace', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);

  // US x1.1: exact holdings, transactions and attribution must all render.
  await selectModel(page, 'US x1.1');
  await expect(page.getByText('Complete retained evidence', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Holdings' }).click();
  await expect(page.getByText(/Positions Snapshot:/)).toBeVisible();
  await expect(page.getByText('15 Assets', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Trades' }).click();
  await expect(page.getByText('Complete transaction ledger', { exact: true })).toBeVisible();
  await expect(page.getByText('1,075 rows', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Attribution' }).click();
  await expect(page.getByText('Contribution table', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByText('Complete retained trace', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);

  // CN x1.0: partial evidence must stay explicit; missing ledgers are never fabricated.
  await selectModel(page, 'CN x1.0');
  await expect(page.getByText('Partial retained evidence', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Holdings' }).click();
  await expect(page.getByText(/Positions Snapshot:/)).toBeVisible();
  await expect(page.getByText('15 Assets', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Trades' }).click();
  await expect(page.getByText('Transaction ledger was not retained', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Attribution' }).click();
  await expect(page.getByText('Attribution evidence is not declared', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByText('Source evidence is incomplete', { exact: true })).toBeVisible();
  await expect(page.getByText('rebalance trade ledger', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);

  expect(pageErrors).toEqual([]);
  expect(failedRequiredResponses).toEqual([]);
  await page.screenshot({
    path: `test-results/live-pages/formal-baselines-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
