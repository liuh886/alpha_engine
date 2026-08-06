import { createHash } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

function marker(prefix: string, payload: object): string {
  return `<!-- ${prefix}:${Buffer.from(JSON.stringify(payload)).toString('base64url')} -->`;
}

const modelsText = JSON.stringify([
  {
    id: 'qqqi_qqq_tqqq_v4_2',
    name: 'QQQ Rotation v4.2',
    market: 'us',
    model_type: 'rule_based_rotation',
    stage: 'BASELINE',
    created_at: '2026-08-02T00:00:00Z',
    metrics: { 'Annualized Return': 0.2, 'Max Drawdown': -0.15 },
  },
]);
const exportManifestText = JSON.stringify({
  generated_at: '2026-08-02T00:00:00Z',
  snapshot_id: 'operations-fixture',
});
const bundleManifest = {
  schema_version: '1.0.0',
  frontend_reader_range: '>=1.0.0 <2.0.0',
  bundle_id: 'a'.repeat(64),
  title: 'Operations Browser Fixture',
  generated_at: '2026-08-02T00:00:00Z',
  evidence_cutoff: '2026-07-31',
  research_only: true,
  trade_ready: false,
  scope: { markets: ['us'], snapshot_id: 'operations-fixture', model_count: 1 },
  warnings: [],
  blocked_gates: ['trade_ready'],
  promotion_decision: 'formal_baseline',
  artifacts: [
    {
      artifact_id: '1'.repeat(16),
      kind: 'model_index',
      path: 'data/models.json',
      media_type: 'application/json',
      byte_size: Buffer.byteLength(modelsText),
      sha256: sha256(modelsText),
      required: true,
    },
    {
      artifact_id: '2'.repeat(16),
      kind: 'static_export_manifest',
      path: 'data/manifest.json',
      media_type: 'application/json',
      byte_size: Buffer.byteLength(exportManifestText),
      sha256: sha256(exportManifestText),
      required: true,
    },
  ],
};

const eventRecord = {
  schema_version: '1.0',
  event_id: 'v42-2026-07-31-state-change',
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
    vix_return_5d: -0.05,
    vxn_close: 18.2,
    vxn_return_1d: -0.02,
    vxn_return_5d: -0.04,
    qqq_distance_ma_short: 0.01,
  },
  recovery_precursor_boolean: false,
  outcome_horizons_sessions: [1, 2, 3, 5, 10, 20, 40],
};

const observation = {
  schema_version: '1.0',
  event_id: eventRecord.event_id,
  as_of_data_date: '2026-08-01',
  status: 'observing_outcomes',
  previous_status: 'awaiting_next_open',
  status_changed: true,
  available_sessions: 2,
  completed_horizons: [1, 2],
  new_horizons: [1, 2],
  execution: {
    execution_date: '2026-08-01',
    theoretical_next_open_prices: { QQQI: 51.2, QQQ: 571.4, TQQQ: 82.1 },
    qqq_opening_gap: 0.002,
  },
  outcomes: {
    '1': { qqq_return: 0.006, tqqq_return: 0.018 },
    '2': { qqq_return: 0.01, tqqq_return: 0.03 },
  },
};

const monthlySummary = {
  schema_version: '1.0',
  month: '2026-08',
  research_only: true,
  trade_ready: false,
  event_count: 1,
  state_change_event_count: 1,
  recovery_precursor_event_count: 0,
  unresolved_40_session_count: 1,
  completed_horizon_counts: { '1': 1, '2': 1 },
  model_change_authorized: false,
  interpretation: 'Prospective evidence remains research-only.',
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

async function mockGitHubLedger(page: Page) {
  await page.route('https://api.github.com/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/issues') || url.pathname.endsWith('/issues/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            number: 9001,
            title: 'v4.2 prospective evidence',
            body: marker('prospective-evidence-record', eventRecord),
            state: 'open',
            html_url: 'https://github.com/liuh886/alpha_engine/issues/9001',
            updated_at: '2026-08-02T00:00:00Z',
          },
          {
            number: 9002,
            title: 'v4.2 monthly evidence',
            body: marker('prospective-evidence-month', monthlySummary),
            state: 'open',
            html_url: 'https://github.com/liuh886/alpha_engine/issues/9002',
            updated_at: '2026-08-02T00:01:00Z',
          },
        ]),
      });
      return;
    }
    if (url.pathname.endsWith('/issues/9001/comments')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            body: marker('prospective-evidence-update', observation),
            html_url: 'https://github.com/liuh886/alpha_engine/issues/9001#issuecomment-1',
            updated_at: '2026-08-02T00:02:00Z',
          },
        ]),
      });
      return;
    }
    if (url.pathname.includes('/actions/workflows/') && url.pathname.endsWith('/runs')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_count: 1,
          workflow_runs: [
            {
              id: 7001,
              name: 'v4.2 workflow',
              status: 'completed',
              conclusion: 'success',
              event: 'schedule',
              html_url: 'https://github.com/liuh886/alpha_engine/actions/runs/7001',
              run_started_at: '2026-08-02T00:00:00Z',
              updated_at: '2026-08-02T00:05:00Z',
              head_sha: 'b'.repeat(40),
            },
          ],
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, body: 'unmatched GitHub fixture' });
  });
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

test('v4.2 operations displays only durable read-only evidence', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await mockBundle(page);
  await mockGitHubLedger(page);

  await page.goto('/#/operations');
  await expect(page.getByRole('heading', { name: 'Observing outcomes' })).toBeVisible();
  await expect(page.getByText('v4.2 active baseline', { exact: true })).toBeVisible();
  await expect(page.getByText('Research only', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Not trade-ready', { exact: true })).toBeVisible();
  await expect(page.getByText('Read-only ledger', { exact: true })).toBeVisible();
  await expect(page.getByText('Last executed allocation at signal close', { exact: true })).toBeVisible();
  await expect(page.getByText('Close-time target allocation', { exact: true })).toBeVisible();
  await expect(page.getByText('2 sessions', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Workflow succeeded', { exact: true })).toHaveCount(2);
  await expect(page.getByText('Sign in')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({
    path: `test-results/static-artifact/v42-operations-${testInfo.project.name}.png`,
    fullPage: true,
  });
});
