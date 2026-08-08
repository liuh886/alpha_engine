import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const publicRoot = path.resolve(process.cwd(), 'public');

test.use({ serviceWorkers: 'block' });

async function openConsole(page: Page) {
  await page.goto('/#/app');
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
}

async function loadFormalDisplayNames(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const catalog = await fetch('./data/formal-model-runs/catalog.json').then((response) => response.json());
    return catalog.records.map((record: { manifest_path: string }) => record.manifest_path).length
      ? Promise.all(catalog.records.map(async (record: { manifest_path: string }) => {
          const manifest = await fetch(`./data/formal-model-runs/${record.manifest_path}`).then((response) => response.json());
          return String(manifest.display_name);
        }))
      : [];
  });
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

test.beforeEach(async ({ page }) => {
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') {
      await route.abort();
      return;
    }
    await route.continue();
  });
});

test('product homepage opens the strategy console', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto('/#/');
  await expect(page.getByRole('heading', { name: 'Run systematic strategies with the evidence still attached.' })).toBeVisible();
  await expect(page.getByText('Start with what the strategies are doing now.').first()).toBeVisible();
  await expect(page.getByText('Decision first. Evidence on demand.')).toBeVisible();
  await assertNoHorizontalOverflow(page);
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: `test-results/static-artifact/landing-${testInfo.project.name}.png`, fullPage: true });

  await page.getByRole('link', { name: 'Open Strategy Console' }).click();
  await expect(page).toHaveURL(/#\/app$/);
  await expect(page.getByRole('heading', { name: 'What are the strategies doing now?' })).toBeVisible();
});

test('strategy console exposes four primary destinations and formal strategy drill-down', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith('/api/')) apiRequests.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await openConsole(page);
  const navName = testInfo.project.name === 'mobile' ? 'Mobile strategy console navigation' : 'Strategy console navigation';
  if (testInfo.project.name === 'mobile') await page.getByRole('button', { name: 'Open strategy navigation' }).click();
  const navigation = page.getByRole('navigation', { name: navName });
  for (const label of ['Overview', 'Strategies', 'Research', 'System']) {
    await expect(navigation.getByRole('link', { name: label, exact: true })).toBeVisible();
  }
  await expect(navigation.getByRole('link', { name: 'Runs', exact: true })).toHaveCount(0);
  await expect(navigation.getByRole('link', { name: 'Backtests', exact: true })).toHaveCount(0);
  if (testInfo.project.name === 'mobile') await page.getByRole('button', { name: 'Close strategy navigation' }).click();

  const formalNames = await loadFormalDisplayNames(page);
  const fleet = page.getByRole('region', { name: 'Formal strategy fleet' });
  for (const name of formalNames) await expect(fleet.getByText(name, { exact: true })).toBeVisible();
  await fleet.getByText('QQQ Rotation v4.3', { exact: true }).click();
  await expect(page).toHaveURL(/#\/strategies\/qqqi_qqq_tqqq_v4_3$/);
  await expect(page.getByRole('heading', { name: 'QQQ Rotation v4.3' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Current decision state' })).toBeVisible();
  const formalTabs = page.getByRole('tablist', { name: 'Formal backtest evidence views' });
  for (const label of ['Performance', 'Risk & robustness', 'Portfolio', 'Trades', 'Attribution', 'Evidence boundary']) {
    await expect(formalTabs.getByRole('tab', { name: label, exact: true })).toBeVisible();
  }
  await assertNoHorizontalOverflow(page);

  await page.goto('/#/research');
  await expect(page.getByRole('heading', { name: 'Research', exact: true })).toBeVisible();
  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'System', exact: true })).toBeVisible();
  await page.goto('/#/dashboard');
  await expect(page.getByRole('heading', { name: 'Strategy view not found' })).toBeVisible();

  expect(apiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);

  await page.screenshot({ path: `test-results/static-artifact/strategy-console-${testInfo.project.name}.png`, fullPage: true });
});

test('installed shell reopens offline after first visit', async ({ page, context }) => {
  test.skip(test.info().project.name !== 'desktop', 'Offline shell smoke runs once on desktop.');
  await page.goto('/#/');
  await expect(page.getByRole('heading', { name: 'Run systematic strategies with the evidence still attached.' })).toBeVisible();
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Run systematic strategies with the evidence still attached.' })).toBeVisible();
});
