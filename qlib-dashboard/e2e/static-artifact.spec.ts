import { createHash } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

function machineMarker(prefix: string, payload: object): string {
  return `<!-- ${prefix}:${Buffer.from(JSON.stringify(payload)).toString('base64url')} -->`;
}

const modelsText = JSON.stringify([
  {
    id: 'fixture-run-1',
    name: 'Static Evidence Fixture',
    market: 'us',
    model_type: 'lgbm',
    stage: 'CANDIDATE',
    created_at: '2026-07-31T00:00:00Z',
    metrics: { 'Sharpe Ratio': 1.2, 'Annualized Return': 0.18, 'Max Drawdown': -0.12 },
    payload: { data: { indicators: { sharpe: 1.2, annual_return: 0.18, max_drawdown: -0.12 } } },
  },
]);
const exportManifestText = JSON.stringify({ generated_at: '2026-08-02T00:00:00Z', snapshot_id: 'fixture-snapshot' });
const bundleManifest = {
  schema_version: '1.0.0',
  frontend_reader_range: '>=1.0.0 <2.0.0',
  bundle_id: 'a'.repeat(64),
  title: 'Static Browser Fixture',
  generated_at: '2026-08-02T00:00:00Z',
  evidence_cutoff: '2026-07-31',
  research_only: true,
  trade_ready: false,
  scope: { markets: ['us'], snapshot_id: 'fixture-snapshot', model_count: 1 },
  warnings: [],
  blocked_gates: ['trade_ready'],
  promotion_decision: 'research_candidate',
  artifacts: [
    { artifact_id: '1'.repeat(16), kind: 'model_index', path: 'data/models.json', media_type: 'application/json', byte_size: Buffer.byteLength(modelsText), sha256: sha256(modelsText), required: true },
    { artifact_id: '2'.repeat(16), kind: 'static_export_manifest', path: 'data/manifest.json', media_type: 'application/json', byte_size: Buffer.byteLength(exportManifestText), sha256: sha256(exportManifestText), required: true },
  ],
};

const runtimeEvent = {
  schema_version: '1.0',
  event_id: 'fixture-event',
  event_type: 'state_change',
  research_only: true,
  trade_ready: false,
  actionable: true,
  status: 'awaiting_next_open',
  signal_date: '2026-07-31',
  latest_data_date_at_creation: '2026-07-31',
  data_freshness_ok: true,
  execution_time: 'next_session_open',
  fingerprint: 'fixture-fingerprint',
  transition_type: 'open_risk_bridge',
  decision_reason: 'enter_qqq_early_repair_vix_easing',
  current_state: 0,
  target_state: 1,
  current_weights: { QQQI: 1, QQQ: 0, TQQQ: 0 },
  target_weights: { QQQI: 0.5, QQQ: 0.5, TQQQ: 0 },
  turnover_units: 1,
  estimated_transaction_cost: 0.001,
  signal_close_features: {
    vix_close: 15.99,
    vix_return_5d: -0.139,
    vxn_close: 26,
    vxn_return_1d: -0.056,
    vxn_return_5d: -0.084,
    qqq_distance_ma_short: -0.0186,
  },
  recovery_precursor_boolean: false,
  outcome_horizons_sessions: [1, 2, 3, 5, 10, 20, 40],
};

const runtimeObservation = {
  schema_version: '1.0',
  event_id: 'fixture-event',
  as_of_data_date: '2026-08-03',
  status: 'observing_outcomes',
  previous_status: 'awaiting_next_open',
  status_changed: true,
  available_sessions: 1,
  completed_horizons: [1],
  new_horizons: [1],
  execution: {
    execution_date: '2026-08-03',
    theoretical_next_open_prices: { QQQI: 52, QQQ: 690, TQQQ: 56 },
    qqq_opening_gap: 0.002,
  },
  outcomes: {
    '1': {
      qqq_return: 0.004,
      tqqq_return: 0.011,
      directional_leverage_component: 0.002,
      tracking_compounding_component: -0.0002,
    },
  },
};

const runtimeMonth = {
  schema_version: '1.0',
  month: '2026-07',
  research_only: true,
  trade_ready: false,
  event_count: 1,
  state_change_event_count: 1,
  recovery_precursor_event_count: 0,
  unresolved_40_session_count: 1,
  completed_horizon_counts: { '1': 1, '2': 0, '3': 0, '5': 0, '10': 0, '20': 0, '40': 0 },
  model_change_authorized: false,
};

async function mockBundle(page: Page) {
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
}

async function mockRuntimeLedger(page: Page) {
  await page.route('https://api.github.com/repos/liuh886/alpha_engine/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith('/issues/333/comments')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            body: machineMarker('prospective-evidence-update', runtimeObservation),
            html_url: 'https://github.com/liuh886/alpha_engine/issues/333#issuecomment-fixture',
            updated_at: '2026-08-03T22:00:00Z',
          },
        ]),
      });
      return;
    }

    if (pathname.endsWith('/issues')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            number: 405,
            title: '[Prospective evidence monthly report] 2026-07',
            body: machineMarker('prospective-evidence-month', runtimeMonth),
            state: 'open',
            html_url: 'https://github.com/liuh886/alpha_engine/issues/405',
            updated_at: '2026-08-03T22:00:00Z',
          },
          {
            number: 333,
            title: '[Strategy signal] v4.2 transition',
            body: machineMarker('prospective-evidence-record', runtimeEvent),
            state: 'open',
            html_url: 'https://github.com/liuh886/alpha_engine/issues/333',
            updated_at: '2026-08-03T22:00:00Z',
          },
        ]),
      });
      return;
    }

    await route.fulfill({ status: 404, body: 'not declared' });
  });
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function openStudio(page: Page) {
  await page.goto('/#/');
  await expect(page.locator('#root')).not.toBeEmpty();
  await expect(page.getByRole('heading', { name: 'Decide what the evidence supports.' })).toBeVisible();
  await expect(page.locator('.research-context-bar').getByText('Static Browser Fixture', { exact: true })).toBeVisible();
}

test('static studio opens without authentication or backend APIs', async ({ page }, testInfo) => {
  const apiRequests: string[] = [];
  const pageErrors: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await mockBundle(page);
  await mockRuntimeLedger(page);
  await openStudio(page);

  if (testInfo.project.name === 'mobile') {
    await page.getByRole('button', { name: 'Open research navigation' }).click();
    const mobileNavigation = page.getByRole('navigation', { name: 'Mobile research studio navigation' });
    await expect(mobileNavigation).toBeVisible();
    await expect(mobileNavigation.getByRole('link', { name: 'v4.2 Operations', exact: true })).toBeVisible();
    await expect(mobileNavigation.getByRole('link', { name: 'Data', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Close research navigation' }).first().click();
  } else {
    await expect(page.getByRole('navigation', { name: 'Research studio navigation' })).toBeVisible();
  }
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Sign in')).toHaveCount(0);
  expect(apiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/overview-${testInfo.project.name}.png`, fullPage: true });

  await page.goto('/#/operations');
  await expect(page.getByRole('heading', { name: 'Observing outcomes' })).toBeVisible();
  await expect(page.getByText('Last executed allocation at signal close')).toBeVisible();
  await expect(page.getByText('Close-time target allocation')).toBeVisible();
  await expect(page.getByText('2026-08-03', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('1/7 declared outcome horizons complete.')).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/operations-${testInfo.project.name}.png`, fullPage: true });

  await page.goto('/#/data');
  await expect(page.getByRole('heading', { name: 'Data identity and readiness' })).toBeVisible();
  await expect(page.locator('main').getByText('2026-07-31', { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/data-${testInfo.project.name}.png`, fullPage: true });

  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'Evidence view not found' })).toBeVisible();
  await expect(page.locator('.research-topbar').getByRole('heading', { name: 'Unavailable route' })).toBeVisible();
  expect(apiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);

  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement?.tagName.toLowerCase());
  expect(['a', 'button', 'input']).toContain(focused);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: `test-results/static-artifact/runtime-blocked-${testInfo.project.name}.png`, fullPage: true });
});

test('installed shell reopens offline after first visit', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Offline lifecycle is checked once on desktop Chromium.');
  await mockBundle(page);
  await mockRuntimeLedger(page);
  await openStudio(page);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Decide what the evidence supports.' })).toBeVisible();
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText('Alpha Engine', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
});
