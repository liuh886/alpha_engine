import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

// Bind current-state fixtures to the exact formal catalog shipped by this build.
// Signal dates below intentionally differ from formal historical cutoffs.
const formal = JSON.parse(readFileSync(new URL('../dist/data/formal-model-runs/catalog.json', import.meta.url), 'utf8'))
  .records.find((row: { model_version_id: string }) => row.model_version_id === 'qqqi_qqq_tqqq_v4_3');
const formalIdentity = { formal_bundle_id: formal.bundle_id, formal_run_id: formal.run_id,
  formal_evidence_cutoff: formal.evidence_cutoff };

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

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
  snapshot_id: 'operations-fixture',
});
const bundleManifest = {
  schema_version: '1.0.0',
  frontend_reader_range: '>=1.0.0 <2.0.0',
  bundle_id: 'a'.repeat(64),
  title: 'Strategy Operations Fixture',
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

const runtimeOperation = {
  strategy_id: 'qqq_rotation',
  model_version_id: 'qqqi_qqq_tqqq_v4_3',
  status: 'target_pending_execution',
  evaluation_changed: true,
  as_of: '2026-07-31',
  latest_completed_session: '2026-07-31',
  decision_cadence: 'Every completed US market session',
  next_decision_policy: 'Evaluate at close; target applies to the next eligible open.',
  state_label: 'Defensive → Transition',
  decision_reason: 'QQQ repair with easing volatility',
  allocations: [
    { asset: 'QQQ', current: 0, target: 0.5, delta: 0.5 },
    { asset: 'QQQI', current: 1, target: 0.5, delta: -0.5 },
    { asset: 'TQQQ', current: 0, target: 0, delta: 0 },
  ],
  turnover: 1,
  estimated_cost: 0.001,
  data_freshness: 'current',
  factor_freshness: 'current',
  delivery_status: 'sent',
  source_label: 'Governed QQQ signal ledger',
  source_href: 'https://github.com/liuh886/alpha_engine/issues/9001',
  note: 'Target is awaiting next-open execution evidence.',
  factor_evidence: [
    {
      factor_id: 'strategy.qqq.vix_close',
      factor_version: '1.0',
      implementation_hash: 'd'.repeat(64),
      display_name: 'VIX close',
      information_family: 'volatility',
      value: 15.99,
      reference: { normal: 18, stress: 22 },
      state: 'calm',
      effect: 'veto',
      reason_code: 'vix_easing_supports_release',
      observed_at: '2026-07-31',
    },
    {
      factor_id: 'strategy.qqq.qqq_vs_ma20',
      factor_version: '1.0',
      implementation_hash: 'e'.repeat(64),
      display_name: 'QQQ distance to SMA20',
      information_family: 'trend',
      value: 0.01,
      reference: 0,
      state: 'at_or_above',
      effect: 'veto',
      reason_code: 'price_repair_supports_release',
      observed_at: '2026-07-31',
    },
  ],
  source_identity: {
    ...formalIdentity,
    ledger_fingerprint: 'fixture-fingerprint',
    signal_sha256: 'b'.repeat(64),
    factor_catalog_implementation_hash: 'f'.repeat(64),
    workflow_run_id: '12345',
    commit_sha: 'c'.repeat(40),
    github_issue_number: 9001,
  },
};

const operations = {
  schema_version: '2.2.0',
  generated_at: '2026-08-02T00:03:00Z',
  research_only: true,
  trade_ready: false,
  records: [
    {
      strategy_id: 'qqq_rotation',
      model_version_id: 'qqqi_qqq_tqqq_v4_3',
      status: 'blocked',
      as_of: null,
      latest_completed_session: null,
      decision_cadence: 'Every completed US market session',
      next_decision_policy: 'Evaluate at close; target applies to the next eligible open.',
      state_label: 'Runtime current operations',
      read_state: 'protected',
      decision_reason: 'Current holdings and signals are delivered from the runtime access plane.',
      allocations: [],
      turnover: null,
      estimated_cost: null,
      data_freshness: 'unknown',
      factor_freshness: 'blocked',
      delivery_status: 'not available',
      source_label: 'Runtime current operations',
      source_href: null,
      note: 'Current holdings, targets, drivers and decision-ledger provenance are never included in the public static bundle.',
      factor_evidence: [],
      source_identity: {
        ...formalIdentity,
        ledger_fingerprint: null,
        signal_sha256: null,
        factor_catalog_implementation_hash: null,
        workflow_run_id: null,
        commit_sha: null,
        github_issue_number: null,
      },
    },
  ],
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
  await page.route('**/data/strategy-operations/snapshots.json', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(operations) });
  });
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function installProMembership(page: Page, options: { failFirst?: boolean; hangFirst?: boolean; mismatched?: boolean; stale?: boolean } = {}): Promise<void> {
  await page.route('**/admin/shared/account-shell.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.addInitScript(({ fullSnapshot, options }) => {
    let calls = 0;
    const snapshot = { loading: false, isPro: true, user: { id: 'pro-fixture' } };
    (window as any).HaoAccount = {
      getState: () => snapshot,
      open: () => undefined,
      subscribe: (listener: (value: typeof snapshot) => void) => {
        listener(snapshot);
        return () => undefined;
      },
      getClient: async () => ({
        from: (table: string) => {
          if (table === 'product_access_policies') {
            return {
              select: () => ({
                eq: async () => ({
                  data: [{
                    product_code: 'alpha_engine',
                    resource_type: 'strategy',
                    resource_id: 'qqq_rotation',
                    required_tier: 'pro',
                    updated_at: '2026-08-12T00:00:00Z',
                  }],
                  error: null,
                }),
              }),
            };
          }
          return {
            select: () => {
              const query: any = {
                eq: () => query,
                maybeSingle: async () => {
                  calls += 1;
                  if (options.hangFirst && calls === 1) return new Promise(() => {});
                  if (options.failFirst && calls === 1) return { data: null, error: { message: 'Temporary read failure' } };
                  return table === 'strategy_operation_snapshots' ? {
                      data: {
                        strategy_id: 'qqq_rotation',
                        model_version_id: 'qqqi_qqq_tqqq_v4_3',
                        snapshot: fullSnapshot,
                      },
                      error: null,
                    }
                  : { data: null, error: null };
                },
              };
              return query;
            },
          };
        },
      }),
    };
  }, { fullSnapshot: {
    ...runtimeOperation,
    ...(options.mismatched ? { source_identity: { ...runtimeOperation.source_identity, formal_bundle_id: 'b'.repeat(64) } } : {}),
    ...(options.stale ? { data_freshness: 'stale', factor_freshness: 'stale', state_detail: 'degraded_delayed',
      staleness: { as_of: '2026-07-31', expected_cutoff: '2026-08-03', sessions_behind: 1, stale: true },
      decision_schedule: { signal_date: '2026-07-31', completed_through: '2026-08-03', cadence_sessions: 10,
        sessions_until_due: 9, state: 'within_cadence', execution_pending: true } } : {}),
  }, options });
}

test('overview brief explains the last evaluation and retains its actual dates', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mockBundle(page);
  await installProMembership(page);
  await page.goto('/#/app');
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  const row = brief.getByRole('article', { name: 'QQQR v4.3 daily observation' });
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toBeVisible();
  await expect(row.getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(row.getByText('Observed 2026-07-31 · target dated 2026-07-31', { exact: false })).toBeVisible();
  await row.getByText('Decision evidence', { exact: true }).click();
  await expect(row.getByText('VIX close: calm · veto · observed 2026-07-31')).toBeVisible();
  expect(errors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('daily-research-brief.png'), fullPage: true });
});

test('overview brief separates read retry from data recovery', async ({ page }) => {
  await mockBundle(page);
  await installProMembership(page, { failFirst: true, stale: true });
  await page.goto('/#/app');
  const row = page.getByRole('region', { name: 'Daily research brief' }).getByRole('article', { name: 'QQQR v4.3 daily observation' });
  await row.getByRole('button', { name: 'Retry reading observations' }).click();
  await expect(row.getByText('Stale', { exact: true })).toBeVisible();
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toHaveCount(0);
  await row.getByText('Recovery steps', { exact: true }).click();
  await expect(row.getByRole('link', { name: 'Open data refresh workflow' })).toHaveAttribute('href', /formal-backtest-refresh.yml$/);
  await row.getByRole('link', { name: 'Open model monitoring' }).click();
  await expect(page).toHaveURL(/#\/model-operations$/);
  await assertNoHorizontalOverflow(page);
});

test('strategy current operations are authorized by runtime policy and hydrated from the runtime store', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const githubApiRequests: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (request.url().startsWith('https://api.github.com/')) githubApiRequests.push(request.url());
  });
  await mockBundle(page);
  await installProMembership(page);

  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await expect(page.getByRole('main').getByRole('heading', { name: 'QQQR v4.3', exact: true, level: 1 })).toBeVisible();

  const now = page.getByRole('region', { name: 'Current decision state' });
  await expect(now).toBeVisible();
  await expect(now.getByText('Defensive → Transition', { exact: true })).toBeVisible();
  await expect(now.getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(now.getByText('QQQI', { exact: true })).toBeVisible();
  await expect(now.getByText('QQQ', { exact: true })).toBeVisible();
  await expect(now.getByText('VIX close', { exact: true })).toBeVisible();
  await expect(now.getByText('15.99', { exact: true })).toBeVisible();
  await expect(now.getByText('calm', { exact: true })).toBeVisible();
  await expect(now.getByText('vix_easing_supports_release', { exact: false })).toBeVisible();
  await expect(page.getByText('New target', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Source record' })).toHaveAttribute('href', 'https://github.com/liuh886/alpha_engine/issues/9001');

  const evidenceTabs = page.getByRole('tablist', { name: 'Formal backtest evidence views' });
  await expect(evidenceTabs.getByRole('tab', { name: 'Performance', exact: true })).toBeVisible();
  await expect(evidenceTabs.getByRole('tab', { name: 'Risk & robustness', exact: true })).toBeVisible();
  await expect(page.getByText('Runtime current operations', { exact: true })).toHaveCount(0);
  expect(githubApiRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({
    path: `test-results/static-artifact/strategy-operations-${testInfo.project.name}.png`,
    fullPage: true,
  });
});

test('current operations recover from a failed read without reloading formal evidence', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await mockBundle(page);
  await installProMembership(page, { failFirst: true });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  const reader = page.getByRole('region', { name: 'Current operations reader' });
  await expect(reader.getByText('QQQR v4.3: current operations could not be verified.')).toBeVisible();
  await expect(page.getByText('Read unavailable', { exact: true })).toBeVisible();
  await expect(page.getByRole('tablist', { name: 'Formal backtest evidence views' })).toBeVisible();
  await expect(page.getByText('QQQ repair with easing volatility', { exact: true })).toHaveCount(0);
  await reader.getByRole('button', { name: 'Retry operations' }).click();
  await expect(page.getByRole('region', { name: 'Current decision state' }).getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(reader.getByRole('button', { name: 'Refresh operations' })).toBeEnabled();
  expect(errors).toEqual([]);
  await assertNoHorizontalOverflow(page);
});

test('a different formal identity cannot supply current allocations', async ({ page }) => {
  await mockBundle(page);
  await installProMembership(page, { mismatched: true });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await expect(page.getByRole('button', { name: 'Retry operations' })).toBeEnabled();
  await expect(page.getByText('QQQ repair with easing volatility', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Protected current operations are unavailable.', { exact: false })).toBeVisible();
});

test('a stalled runtime read times out and allows an explicit retry', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.clock.install();
  await mockBundle(page);
  await installProMembership(page, { hangFirst: true });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  const reader = page.getByRole('region', { name: 'Current operations reader' });
  await expect(reader.getByRole('button', { name: 'Reading operations' })).toBeDisabled();
  // Ensure the public identity has arrived before advancing the runtime deadline.
  await expect(page.getByText('Protected current operations are unavailable.', { exact: false })).toBeVisible();
  await page.clock.fastForward(15_000);
  await expect(reader.getByText('Operations reading timed out.', { exact: false })).toBeVisible();
  await reader.getByRole('button', { name: 'Retry operations' }).click();
  await expect(page.getByRole('region', { name: 'Current decision state' }).getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(reader.getByRole('button', { name: 'Refresh operations' })).toBeEnabled();
  expect(errors).toEqual([]);
});

test('stale observations require attention while cadence and execution stay explicit', async ({ page }) => {
  await mockBundle(page);
  await installProMembership(page, { stale: true });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await expect(page.getByRole('button', { name: 'Refresh operations' })).toBeEnabled();
  await expect(page.getByText('Next evaluation in 9 exchange sessions;', { exact: false })).toBeVisible();
  await expect(page.getByText('Execution evidence is still pending;', { exact: false })).toBeVisible();
  await page.goto('/#/strategies');
  // This fixture publishes only QQQ: four missing strategies must leave QQQ
  // readable while the reader offers recovery for their independent failures.
  await expect(page.getByRole('button', { name: 'Retry operations' })).toBeEnabled();
  await page.getByLabel('Signal filter', { exact: true }).selectOption('attention');
  const row = page.getByTestId('fleet-qqqi_qqq_tqqq_v4_3');
  await expect(row).toBeVisible();
  await expect(row.getByRole('button', { name: /^(Stale|Inspect signal for .*: Stale)$/ }).filter({ visible: true })).toHaveCount(1);
  await assertNoHorizontalOverflow(page);
});
