import { expect, test, type Page } from '@playwright/test';
import { installMembershipFixture } from './membership-fixture';

/**
 * Per-route smoke contract for the four task-based destinations: one page
 * heading, one visible research-only boundary, no horizontal page scroll and
 * no console error. Rows that show a return must also show their own as-of.
 */

interface PublishedRun {
  modelVersionId: string;
  asOf: string;
  staleDays: number;
}

const ROUTES = [
  { name: 'overview', path: '/#/app', rows: true },
  { name: 'strategies', path: '/#/strategies', rows: true },
  { name: 'strategy detail', path: '/#/strategies/qqqi_qqq_tqqq_v4_3', rows: false },
  { name: 'instrument', path: '/#/securities/us/QQQ', rows: false },
  { name: 'research', path: '/#/research', rows: false },
  { name: 'system', path: '/#/system', rows: false },
] as const;

async function loadPublishedRuns(page: Page): Promise<PublishedRun[]> {
  const response = await page.request.get('/data/formal-model-runs/catalog.json');
  expect(response.ok()).toBeTruthy();
  const catalog = await response.json() as { records?: Array<{ manifest_path?: string; model_version_id?: string }> };
  const runs: PublishedRun[] = [];
  for (const record of catalog.records ?? []) {
    const base = '/data/formal-model-runs/' + String(record.manifest_path).replace(/manifest\.json$/, '');
    const navResponse = await page.request.get(base + 'nav.json');
    expect(navResponse.ok()).toBeTruthy();
    const nav = await navResponse.json() as { evidence_cutoff: string; rows: Array<{ date: string }> };
    const last = nav.rows[nav.rows.length - 1];
    expect(last?.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    runs.push({
      modelVersionId: String(record.model_version_id),
      asOf: last.date,
      staleDays: Math.round((Date.parse(`${nav.evidence_cutoff}T00:00:00Z`) - Date.parse(`${last.date}T00:00:00Z`)) / 86_400_000),
    });
  }
  expect(runs.length).toBeGreaterThan(0);
  return runs;
}

test('every product route keeps one heading, one research boundary and no overflow', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on('pageerror', error => consoleErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await installMembershipFixture(page, { loading: false, isPro: false, user: null });
  const runs = await loadPublishedRuns(page);

  for (const route of ROUTES) {
    await page.goto(route.path);
    await expect(page.getByRole('main'), `${route.name}: main region`).toBeVisible();

    const headings = page.getByRole('heading', { level: 1 });
    await expect(headings, `${route.name}: exactly one H1`).toHaveCount(1);
    await expect(headings, `${route.name}: H1 visible`).toBeVisible();

    // The shell states the research boundary once; retired duplicate labels
    // must not return to the topbar, context bar or sidebar.
    const topbar = page.locator('.research-topbar');
    await expect(topbar.getByText('Alpha Engine / Research only', { exact: true })).toHaveCount(1);
    await expect(page.locator('.research-context-bar').getByText('Research only', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Research workspace', { exact: true })).toHaveCount(0);

    if (route.rows) {
      for (const run of runs) {
        const row = page.getByTestId('fleet-' + run.modelVersionId);
        await expect(row, `${route.name}: ${run.modelVersionId} row`).toBeVisible();
        await expect(row).toContainText(`As of ${run.asOf}`);
        await expect(row).toHaveAttribute('data-stale', run.staleDays > 14 ? 'true' : 'false');
      }
    }

    if (route.path.includes('/strategies/')) {
      const hero = page.getByTestId('strategy-chart-hero');
      await expect(hero).toBeVisible();
      const run = runs.find(candidate => route.path.endsWith(candidate.modelVersionId));
      expect(run, `${route.name}: published run for the route`).toBeTruthy();
      await expect(hero).toContainText(`As of ${run!.asOf}`);
      if (testInfo.project.name === 'mobile') {
        const controls = [
          ...await hero.getByRole('group', { name: 'Chart horizon' }).getByRole('button').all(),
          ...await hero.getByRole('button', { name: /baseline:/ }).all(),
        ];
        expect(controls.length).toBeGreaterThan(0);
        for (const control of controls) {
          const box = await control.boundingBox();
          expect(box?.height ?? 0, `${route.name}: coarse-pointer target height`).toBeGreaterThanOrEqual(44);
          expect(box?.width ?? 0, `${route.name}: coarse-pointer target width`).toBeGreaterThanOrEqual(44);
        }
      }
    }

    if (route.path.includes('/securities/')) {
      await expect(page.getByTestId('security-last-close')).toBeVisible();
      await expect(page.locator('dt').filter({ hasText: 'As of' }).first()).toBeVisible();
    }

    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
      `${route.name}: no horizontal page scroll at ${testInfo.project.name}`,
    ).toBeLessThanOrEqual(2);
  }

  expect(consoleErrors).toEqual([]);
});
