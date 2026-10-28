import { expect, test, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { racetrackFixture } from './fixtures/racetrack';

test.beforeEach(async ({ page }) => {
  await page.route('**/admin/shared/account-shell.js*', route => route.fulfill({ contentType: 'application/javascript', body: '' }));
  await page.addInitScript(() => {
    const state = { loading: false, isPro: false, user: null };
    (window as any).HaoAccount = { getState: () => state, open() {}, getClient: async () => null,
      subscribe: (listener: (state: unknown) => void) => { listener(state); return () => {}; } };
  });
});

async function install(page: Page, options: { count?: number; badHash?: boolean; missing?: boolean; delayUs?: boolean; badDetail?: boolean } = {}) {
  const reads: string[] = [];
  const fixtures = { us: racetrackFixture('us', options.count ?? 11), cn: racetrackFixture('cn', options.count ?? 11) };
  if (options.badDetail) {
    const f = fixtures.us; const ref = f.manifest.artifacts[f.manifest.runner_details[f.scoreboard.entries[0].runner_id]];
    const detail = JSON.parse(f.files[ref.path]); detail.runner_version = 'wrong';
    f.files[ref.path] = JSON.stringify(detail);
    ref.size_bytes = Buffer.byteLength(f.files[ref.path]);
    ref.sha256 = createHash('sha256').update(f.files[ref.path]).digest('hex');
  }
  await page.route('**/__racetrack/**', async route => {
    const url = new URL(route.request().url()); reads.push(url.pathname);
    const [, market, path] = url.pathname.match(/^\/__racetrack\/(us|cn)\/(.*)$/)!;
    if (options.delayUs && market === 'us' && path === 'manifest.json') await new Promise(resolve => setTimeout(resolve, 450));
    if (options.missing) return route.fulfill({ status: 404, body: '{}' });
    const f = fixtures[market as 'us' | 'cn'];
    const body = path === 'manifest.json' ? JSON.stringify(f.manifest) : f.files[path];
    await route.fulfill({ status: body ? 200 : 404, contentType: 'application/json',
      body: (body ?? '{}') + (options.badHash && path.endsWith('scoreboard_latest.json') ? ' ' : '') });
  });
  return { reads, fixtures };
}
async function open(page: Page) {
  await page.goto('/#/app');
  await page.getByRole('button', { name: 'Racetrack research', exact: true }).click();
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2);
}

test('NAV, published Top 10, lazy detail, windows and selection work together', async ({ page }, info) => {
  if (info.project.name === 'desktop') await page.setViewportSize({ width: 1440, height: 1100 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const fixture = await install(page);
  await page.goto('/#/app'); expect(fixture.reads).toHaveLength(0);
  await page.getByRole('button', { name: 'Racetrack research', exact: true }).click();
  await expect(page.getByRole('img', { name: 'Racetrack normalized NAV comparison' }).locator('canvas').first()).toBeVisible();
  const board = page.getByRole('region', { name: 'Published Top 10' });
  await expect(board.locator('tbody tr')).toHaveCount(10);
  await expect(board.getByText('fixture_us_11', { exact: true })).toHaveCount(0);
  expect(fixture.reads.filter(url => url.includes('/runners/'))).toHaveLength(0);
  await board.getByRole('button', { name: 'fixture_us_01', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Runner detail' });
  await expect(detail.getByText('Investment thesis', { exact: true })).toBeVisible();
  await expect(detail).toContainText('Synthetic thesis for fixture_us_01');
  expect(fixture.reads.filter(url => url.includes('/runners/'))).toHaveLength(1);
  await page.getByRole('button', { name: 'Close runner detail', exact: true }).click();
  await page.getByLabel('NAV legend').getByRole('button', { name: 'fixture_us_02', exact: true }).click();
  await expect(detail).toContainText('Synthetic thesis for fixture_us_02');
  await page.getByRole('button', { name: 'Close runner detail', exact: true }).click();
  await expect(board.getByRole('button', { name: 'fixture_us_02', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '1Y', exact: true }).click();
  await expect(board.getByText('Insufficient history', { exact: true })).toHaveCount(10);
  await expect(board.locator('tbody tr').first()).toContainText('fixture_us_01');
  await expect(page.getByText('Display NAV · 1.00 at 2026-07-01', { exact: true })).toBeVisible();
  const slider = page.getByRole('slider', { name: 'NAV readout date' });
  await slider.focus(); await slider.press('Home'); await slider.press('ArrowRight');
  await expect(page.getByText('2026-07-31', { exact: true })).toBeVisible();
  await noOverflow(page); expect(errors).toEqual([]);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.getByRole('heading', { name: 'NAV comparison', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`racetrack-${info.project.name}-chart.png`) });
  await board.getByRole('heading', { name: 'Published Top 10', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`racetrack-${info.project.name}-table.png`) });
  await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(page.getByRole('img', { name: 'Racetrack normalized NAV comparison' })).toBeVisible();
  await page.screenshot({ path: info.outputPath(`racetrack-${info.project.name}-dark.png`) });
  await board.getByRole('button', { name: 'fixture_us_02', exact: true }).click();
  await detail.getByRole('heading', { name: 'fixture_us_02', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath(`racetrack-${info.project.name}-detail.png`) });
  await page.getByRole('button', { name: 'Close runner detail', exact: true }).click();
  await expect(detail).toHaveCount(0);
  await page.getByRole('button', { name: 'Strategy monitor', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Daily research brief' })).toBeVisible();
});
test('market change discards late US reads and keeps CN evidence separate', async ({ page }) => {
  await install(page, { delayUs: true }); await open(page);
  await page.getByRole('combobox', { name: 'Racetrack market' }).selectOption('cn');
  await expect(page.getByText('cn_selected_equities_v3', { exact: false }).last()).toBeVisible();
  await expect(page.getByRole('region', { name: 'Published Top 10' })).toContainText('fixture_cn_01');
  await page.waitForTimeout(500);
  await expect(page.getByRole('region', { name: 'Published Top 10' })).not.toContainText('fixture_us_01');
  await noOverflow(page);
});
test('baseline-only shows both benchmarks and an honest empty leaderboard', async ({ page }) => {
  await install(page, { count: 0 }); await open(page);
  await expect(page.getByRole('region', { name: 'Published Top 10' })).toContainText('diagnostic baseline');
  await expect(page.getByLabel('NAV legend').getByRole('button')).toHaveCount(2);
  await expect(page.getByRole('region', { name: 'Runner detail' })).toHaveCount(0);
});
test('hash failure clears the research view, retries and leaves the strategy view usable', async ({ page }) => {
  await install(page, { badHash: true }); await open(page);
  await expect(page.getByRole('alert')).toContainText('hash/size mismatch');
  await expect(page.getByRole('region', { name: 'Published Top 10' })).toHaveCount(0);
  await page.unroute('**/__racetrack/**'); await install(page);
  await page.getByRole('button', { name: 'Retry projection', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Published Top 10' }).locator('tbody tr')).toHaveCount(10);
});
test('unpublished projection and mismatched detail stay explicit', async ({ page }) => {
  await install(page, { missing: true }); await open(page);
  await expect(page.getByRole('alert')).toContainText('No local projection');
  await page.unroute('**/__racetrack/**'); await install(page, { badDetail: true });
  await page.getByRole('button', { name: 'Retry projection', exact: true }).click();
  await page.getByRole('region', { name: 'Published Top 10' }).getByRole('button', { name: 'fixture_us_01', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Runner detail' });
  await expect(detail.getByRole('alert')).toContainText('identity mismatch');
  await expect(detail.getByText('Published summary only', { exact: true })).toBeVisible();
  await expect(detail.getByText('Hypothetical model weights', { exact: true })).toHaveCount(0);
});
