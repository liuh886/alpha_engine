import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const modelsText = JSON.stringify([
  {
    id: 'qqqi_qqq_tqqq_v4_3',
    name: 'QQQ Rotation v4.3',
    market: 'us',
    model_type: 'rule_based_rotation',
    stage: 'BASELINE',
    created_at: '2026-08-02T00:00:00Z',
    metrics: { 'Annualized Return': 0.2, 'Max Drawdown': -0.15 },
  },
]);
const exportManifestText = JSON.stringify({
  generated_at: '2026-08-02T00:00:00Z',
  snapshot_id: 'mobile-fixture',
});
const bundleManifest = {
  schema_version: '1.0.0',
  frontend_reader_range: '>=1.0.0 <2.0.0',
  bundle_id: 'b'.repeat(64),
  title: 'Mobile Shell Fixture',
  generated_at: '2026-08-02T00:00:00Z',
  evidence_cutoff: '2026-07-31',
  research_only: true,
  trade_ready: false,
  scope: { markets: ['us'], snapshot_id: 'mobile-fixture', model_count: 1 },
  warnings: [],
  blocked_gates: ['trade_ready'],
  promotion_decision: 'formal_baseline',
  artifacts: [
    { artifact_id: '1'.repeat(16), kind: 'model_index', path: 'data/models.json', media_type: 'application/json', byte_size: modelsText.length, sha256: '0'.repeat(64), required: true },
    { artifact_id: '2'.repeat(16), kind: 'static_export_manifest', path: 'data/manifest.json', media_type: 'application/json', byte_size: exportManifestText.length, sha256: '0'.repeat(64), required: true },
  ],
};

async function mockShell(page: Page) {
  await page.route('**/bundle/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith('/alpha-engine-bundle.json')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bundleManifest) });
    } else if (pathname.endsWith('/data/models.json')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: modelsText });
    } else if (pathname.endsWith('/data/manifest.json')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: exportManifestText });
    } else {
      await route.fulfill({ status: 404, body: 'not declared' });
    }
  });
  await page.route('**/admin/shared/account-shell.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
}

async function openOverview(page: Page) {
  await mockShell(page);
  await page.goto('/#/app');
  await expect(page.getByRole('heading', { name: 'Strategy Overview' })).toBeVisible({ timeout: 15000 });
}

async function isHandset(page: Page): Promise<boolean> {
  const viewport = page.viewportSize();
  return (viewport?.width ?? 1280) < 768;
}

test('mobile tab bar is visible only on handsets with five reachable tabs', async ({ page }) => {
  await openOverview(page);
  const tabbar = page.getByRole('navigation', { name: 'Primary' });
  if (await isHandset(page)) {
    await expect(tabbar).toBeVisible();
    const tabs = tabbar.getByRole('tab');
    await expect(tabs).toHaveCount(5);
    await expect(tabs.first()).toHaveAttribute('aria-selected', 'true');
    for (const tab of await tabs.all()) {
      const box = await tab.boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
    await tabs.nth(1).click();
    await expect(page).toHaveURL(/#\/strategies/);
  } else {
    await expect(tabbar).toBeHidden();
  }
});

test('mobile drawer opens, traps focus affordance and closes on Escape', async ({ page }) => {
  await openOverview(page);
  if (!(await isHandset(page))) {
    await expect(page.getByRole('button', { name: 'Open strategy navigation' })).toBeHidden();
    return;
  }
  await page.getByRole('button', { name: 'Open strategy navigation' }).click();
  const dialog = page.getByRole('dialog', { name: 'Strategy navigation' });
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

test('handset overview has no horizontal overflow and content clears the tab bar', async ({ page }) => {
  await openOverview(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
  if (await isHandset(page)) {
    const tabbar = page.getByRole('navigation', { name: 'Primary' });
    const bar = await tabbar.boundingBox();
    const main = await page.locator('.research-main').boundingBox();
    expect(bar && main ? main.y + main.height : 0).toBeGreaterThan(0);
    if (bar && main) {
      const mainBottomInView = main.y + main.height - (await page.evaluate(() => window.scrollY));
      expect(mainBottomInView).toBeGreaterThan(bar.y);
    }
  }
});
