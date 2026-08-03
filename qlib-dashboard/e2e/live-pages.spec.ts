import { expect, test, type Page } from '@playwright/test';

const FORMAL_MODELS = ['QQQ Rotation v4.2', 'US x1.1', 'CN x1.0'] as const;
const REQUIRED_FRESHNESS_CUTOFF = '2026-07-31';

type FormalPackage = {
  model_id?: string;
  evidence_cutoff?: string;
  date_range?: { end?: string };
  trades?: unknown[];
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function fetchFormalPackage(page: Page, modelId: string): Promise<FormalPackage> {
  const packageUrl = new URL(`data/formal-backtests/${modelId}.json`, page.url());
  packageUrl.searchParams.set('live_acceptance', Date.now().toString());
  const response = await page.request.get(packageUrl.toString(), {
    headers: { 'cache-control': 'no-cache', pragma: 'no-cache' },
  });
  expect(response.ok(), `failed to load ${packageUrl.toString()}`).toBeTruthy();
  return response.json() as Promise<FormalPackage>;
}

async function openSelector(page: Page) {
  const trigger = page.getByRole('button', {
    name: /QQQ Rotation v4\.2|US x1\.1|CN x1\.0/,
  }).first();
  await expect(trigger).toBeVisible();
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Select formal baseline' })).toBeVisible();
  await expect(dialog.getByTestId('formal-model-card')).toHaveCount(3);
  for (const model of FORMAL_MODELS) {
    await expect(dialog.getByText(model, { exact: true })).toBeVisible();
  }
  await expect(dialog.getByText('US x1.0', { exact: true })).toHaveCount(0);
  return dialog;
}

async function selectModel(page: Page, model: typeof FORMAL_MODELS[number]): Promise<void> {
  const dialog = await openSelector(page);
  await dialog.getByTestId('formal-model-card').filter({ hasText: model }).click();
  await expect(page.getByRole('button', { name: new RegExp(escapeRegExp(model)) }).first()).toBeVisible();
  await expect(dialog).toBeHidden();
}

test('live Pages renders every governed formal baseline end to end', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const failedRequiredResponses: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('response', (response) => {
    const url = response.url();
    if (response.status() >= 400 && (url.includes('/bundle/') || url.includes('/data/formal-backtests/') || url.includes('/assets/'))) {
      failedRequiredResponses.push(`${response.status()} ${url}`);
    }
  });

  await page.goto(`?live_acceptance=${Date.now()}#/dashboard`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Complete backtest review' })).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Experiments', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Ann: null|IR: null/)).toHaveCount(0);

  const initialDialog = await openSelector(page);
  await page.keyboard.press('Escape');
  await expect(initialDialog).toBeHidden();

  await expect(page.getByRole('button', { name: /QQQ Rotation v4\.2/ }).first()).toBeVisible();
  const v42Curve = page.getByTestId('equity-curve-container');
  await expect(v42Curve).toBeVisible();
  const v42PointCount = Number(await v42Curve.getAttribute('data-strategy-point-count'));
  expect(v42PointCount).toBeGreaterThan(600);
  await expect(page.getByText('Retained allocation contributions', { exact: true })).toBeVisible();
  await expect(page.getByText(/stock picking ability/i)).toHaveCount(0);
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByText('Formal backtest evidence', { exact: true })).toBeVisible();
  await expect(page.getByText('Complete retained trace', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);

  const usPackage = await fetchFormalPackage(page, 'us_x1_1');
  expect(usPackage.model_id).toBe('us_x1_1');
  expect(usPackage.evidence_cutoff).toBe(REQUIRED_FRESHNESS_CUTOFF);
  expect(usPackage.date_range?.end).toBe(REQUIRED_FRESHNESS_CUTOFF);
  expect(Array.isArray(usPackage.trades)).toBeTruthy();
  const usTradeRowCount = usPackage.trades?.length ?? 0;
  expect(usTradeRowCount).toBeGreaterThan(1_075);

  await selectModel(page, 'US x1.1');
  await expect(page.getByText('Complete retained evidence', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Holdings' }).click();
  await expect(page.getByText(/Positions Snapshot:/)).toBeVisible();
  await expect(page.getByText('15 Assets', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Trades' }).click();
  await expect(page.getByText('Complete transaction ledger', { exact: true })).toBeVisible();
  await expect(page.getByText(`${usTradeRowCount.toLocaleString('en-US')} rows`, { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Attribution' }).click();
  await expect(page.getByText('Contribution table', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByText('Complete retained trace', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);

  const cnPackage = await fetchFormalPackage(page, 'cn_x1_0');
  expect(cnPackage.model_id).toBe('cn_x1_0');
  expect(cnPackage.evidence_cutoff).toBe(REQUIRED_FRESHNESS_CUTOFF);
  expect(cnPackage.date_range?.end).toBe(REQUIRED_FRESHNESS_CUTOFF);

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
  await page.screenshot({ path: `test-results/live-pages/formal-baselines-${testInfo.project.name}.png`, fullPage: true });
});
