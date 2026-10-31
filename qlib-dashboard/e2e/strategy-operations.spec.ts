import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { parseRdiResearch } from '../src/lib/rdi-research';
import { rdiInteractionFixture } from './rdi-fixture';

test.use({ serviceWorkers: 'block' });

const rdiSourceCount = rdiInteractionFixture.event_families.length;
const rdiIntegrationCount = rdiInteractionFixture.event_families.filter(row => row.readiness === 'not_integrated').length;
const rdiFourteen = rdiInteractionFixture.historical_comparison.find(row => row.horizon_sessions === 14)!;
const rdiSeven = rdiInteractionFixture.historical_comparison.find(row => row.horizon_sessions === 7)!;
const rdiTwentyEight = rdiInteractionFixture.historical_comparison.find(row => row.horizon_sessions === 28)!;
const frequency = (value: number) => (value * 100).toFixed(2) + '%';
const fixtureCount = (value: number) => 'n=' + value.toLocaleString('en-US');

test('RDI workspace compares horizons, filters sources and retries independently', async ({ page }, testInfo) => {
  let reads = 0, snapshotReads = 0, healthReads = 0;
  page.on('request', request => {
    if (request.url().includes('/data/strategy-operations/snapshots.json')) snapshotReads++;
    if (request.url().includes('/data/strategy-operations/system-health.json')) healthReads++;
  });
  await page.route('**/data/strategy-operations/rdi-research.json', async route => {
    reads++;
    if (reads === 1) await route.fulfill({ status: 503, body: 'unavailable' });
    else await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rdiInteractionFixture) });
  });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/system');
  const section = page.getByRole('region', { name: 'Risk density · RDI' });
  await expect(section.getByRole('alert')).toContainText('could not be verified');
  const refresh = page.getByRole('button', { name: 'Refresh status', exact: true });
  await expect(refresh).toBeEnabled();
  await expect.poll(() => fixtureCalls(page)).toBe(1);
  const beforeRetry = { snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) };
  const windowYBeforeJump = await page.evaluate(() => window.scrollY);
  await page.getByRole('button', { name: 'RDI research', exact: true }).click();
  await expect(page).toHaveURL(/#\/system$/);
  await expect(section.getByRole('heading', { name: 'Risk density · RDI', exact: true })).toBeFocused();
  expect(await page.evaluate(() => window.scrollY)).toBe(windowYBeforeJump);
  const topbar = page.locator('.research-topbar');
  await expect(topbar).toBeInViewport();
  expect(await topbar.evaluate(element => element.getBoundingClientRect().top)).toBeGreaterThanOrEqual(0);
  await section.getByRole('button', { name: 'Retry RDI', exact: true }).click();
  await expect(section.getByRole('heading', { name: 'Risk assessment unavailable' })).toBeVisible();
  await expect(section.getByText(rdiInteractionFixture.reviewed_price_cutoff, { exact: true })).toBeVisible();
  expect({ snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) }).toEqual(beforeRetry);
  await section.getByRole('heading', { name: 'Risk assessment unavailable' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(tmpdir(), `alpha-engine-rdi-${testInfo.project.name}.png`) });
  const selected = section.getByRole('group', { name: '14-session details' });
  await expect(selected.getByText(frequency(rdiFourteen.drawdown_loss_frequency), { exact: true })).toBeVisible();
  await expect(selected.getByText(frequency(rdiFourteen.other_loss_frequency), { exact: true })).toBeVisible();
  const difference = (rdiFourteen.drawdown_loss_frequency - rdiFourteen.other_loss_frequency) * 100;
  await expect(selected.getByText(`${difference > 0 ? '+' : ''}${difference.toFixed(2)} pp`, { exact: true })).toBeVisible();
  await expect(selected.getByText(fixtureCount(rdiFourteen.drawdown_observations), { exact: true })).toBeVisible();
  await expect(selected.getByText(fixtureCount(rdiFourteen.other_observations), { exact: true })).toBeVisible();
  await expect(section.getByRole('meter')).toHaveCount(rdiInteractionFixture.historical_comparison.length * 2);
  for (const bar of await section.getByRole('meter').all()) {
    await expect(bar).toHaveAttribute('aria-valuemin', '0');
    await expect(bar).toHaveAttribute('aria-valuemax', '100');
  }
  await section.getByRole('button', { name: '14 trading sessions', exact: true }).focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await expect(section.getByRole('group', { name: '28-session details' })).toBeVisible();
  await section.getByRole('button', { name: '7 trading sessions', exact: true }).click();
  await expect(section.getByRole('group', { name: '7-session details' }).getByText(frequency(rdiSeven.drawdown_loss_frequency), { exact: true })).toBeVisible();
  await section.getByText('View exact historical values', { exact: true }).click();
  await expect(section.getByRole('table').getByRole('rowheader', { name: '28 sessions' })).toBeVisible();
  await expect(section.getByText(/not a current loss probability/)).toBeVisible();
  await section.locator('summary').filter({ hasText: 'Data coverage and sources' }).click();
  await section.getByRole('button', { name: 'Needs integration', exact: true }).click();
  await expect(section.getByText(`Showing ${rdiIntegrationCount} of ${rdiSourceCount} source families`, { exact: true })).toBeVisible();
  await expect(section.getByText('Historical coverage unverified', { exact: true })).toHaveCount(rdiIntegrationCount);
  await section.getByRole('button', { name: 'All sources', exact: true }).click();
  await expect(section.getByText(`Showing ${rdiSourceCount} of ${rdiSourceCount} source families`, { exact: true })).toBeVisible();
  await section.getByText('Evidence provenance', { exact: true }).click();
  await expect(section.getByRole('link', { name: 'Research protocol and limitations' })).toHaveAttribute('href', /\/blob\/[a-f0-9]{40}\//);
  await expect(section.getByText('None admitted', { exact: true })).toBeVisible();
  expect(reads).toBe(2);
  expect({ snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) }).toEqual(beforeRetry);
  await refresh.click();
  await expect.poll(() => reads).toBe(3);
  await expect(section.getByRole('heading', { name: 'Historical price comparison', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('RDI workspace retains context and keyboard focus through refresh recovery', async ({ page }) => {
  let reads = 0, snapshotReads = 0, healthReads = 0;
  let releasePendingRead: (() => void) | null = null;
  const releaseRead = async () => {
    await expect.poll(() => Boolean(releasePendingRead)).toBe(true);
    const release = releasePendingRead!;
    releasePendingRead = null;
    release();
  };
  page.on('request', request => {
    if (request.url().includes('/data/strategy-operations/snapshots.json')) snapshotReads++;
    if (request.url().includes('/data/strategy-operations/system-health.json')) healthReads++;
  });
  await page.route('**/data/strategy-operations/rdi-research.json', async route => {
    const read = ++reads;
    if ([2, 3, 6].includes(read)) await new Promise<void>(resolve => { releasePendingRead = resolve; });
    if (read === 1 || read === 5) await route.fulfill({ status: 503, body: 'unavailable' });
    else if (read === 4) await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ...rdiInteractionFixture, status: 'evidence_mismatch', historical_comparison: [],
    }) });
    else await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rdiInteractionFixture) });
  });
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/system');
  const section = page.getByRole('region', { name: 'Risk density · RDI' });
  const localRead = section.locator('header').getByRole('button');
  const globalRefresh = page.getByRole('button', { name: 'Refresh status', exact: true });
  await expect(section.getByRole('alert')).toContainText('could not be verified');
  await expect(globalRefresh).toBeEnabled();
  await expect.poll(() => fixtureCalls(page)).toBe(1);
  const otherReads = { snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) };
  const originalButton = await localRead.elementHandle();
  await localRead.focus();
  await page.keyboard.press('Enter');
  await expect(localRead).toHaveText('Reading RDI…');
  await expect(localRead).toHaveAttribute('aria-disabled', 'true');
  await expect(localRead).toBeFocused();
  await page.keyboard.press('Enter');
  await releaseRead();
  await expect(localRead).toHaveText('Refresh RDI');
  await expect(localRead).toBeFocused();
  expect(await originalButton!.evaluate(element => element.isConnected && element === document.activeElement)).toBe(true);
  expect(reads).toBe(2);
  expect({ snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) }).toEqual(otherReads);

  await section.getByRole('button', { name: '28 trading sessions', exact: true }).click();
  const exactSummary = section.getByText('View exact historical values', { exact: true });
  await exactSummary.focus();
  await page.keyboard.press('Enter');
  await expect(section.getByRole('table')).toBeVisible();
  await section.locator('summary').filter({ hasText: 'Data coverage and sources' }).click();
  await section.getByRole('button', { name: 'Needs integration', exact: true }).click();
  await section.getByText('Evidence provenance', { exact: true }).click();
  await expect(section.getByText(`Showing ${rdiIntegrationCount} of ${rdiSourceCount} source families`, { exact: true })).toBeVisible();
  const expectContext = async () => {
    await expect(section.getByRole('button', { name: '28 trading sessions', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(section.getByRole('group', { name: '28-session details' })).toBeVisible();
    await expect(section.getByRole('button', { name: 'Needs integration', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(section.getByText(`Showing ${rdiIntegrationCount} of ${rdiSourceCount} source families`, { exact: true })).toBeVisible();
    await expect(section.locator('details')).toHaveCount(3);
    for (const details of await section.locator('details').all()) await expect(details).toHaveJSProperty('open', true);
    await expect(section.getByRole('table')).toBeVisible();
    await expect(section.getByRole('link', { name: 'Research protocol and limitations' })).toBeVisible();
  };
  await expectContext();
  await globalRefresh.click();
  await expect(localRead).toHaveText('Reading RDI…');
  await expect(section.getByRole('meter')).toHaveCount(0);
  await expect(section.getByRole('table')).toHaveCount(0);
  await releaseRead();
  await expect(localRead).toHaveText('Refresh RDI');
  await expect(globalRefresh).toBeEnabled();
  await expectContext();
  const afterParentRefresh = { snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) };

  await localRead.click();
  await expect(section.getByRole('alert')).toContainText('Source evidence has changed');
  await expect(localRead).toHaveText('Retry RDI');
  await expect(section.getByRole('meter')).toHaveCount(0);
  await expect(section.getByRole('table')).toHaveCount(0);
  await expect(section.getByText(frequency(rdiTwentyEight.drawdown_loss_frequency), { exact: true })).toHaveCount(0);
  await expect(localRead).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(section.getByRole('alert')).toContainText('could not be verified');
  await expect(section.getByRole('meter')).toHaveCount(0);
  await expect(localRead).toHaveText('Retry RDI');
  await expect(localRead).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(localRead).toHaveText('Reading RDI…');
  const title = section.getByRole('heading', { name: 'Risk density · RDI', exact: true });
  await title.focus();
  await releaseRead();
  await expect(localRead).toHaveText('Refresh RDI');
  await expect(title).toBeFocused();
  expect(await originalButton!.evaluate(element => element.isConnected)).toBe(true);
  await expectContext();
  expect(reads).toBe(6);
  expect({ snapshotReads, healthReads, runtimeReads: await fixtureCalls(page) }).toEqual(afterParentRefresh);
});

test('RDI published state keeps optional evidence scoped while Overview remains readable', async ({ page }) => {
  // No RDI route mock: accept the shipped optional asset's actual contract state.
  const published = await (async () => {
    try {
      const response = await page.request.get('/data/strategy-operations/rdi-research.json', { timeout: 5_000 });
      return response.ok() ? parseRdiResearch(await response.json()) : null;
    } catch {
      return null;
    }
  })();
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/system');
  const section = page.getByRole('region', { name: 'Risk density · RDI' });
  if (published?.status === 'not_validated') {
    await expect(section.getByRole('heading', { name: 'Historical price comparison', exact: true })).toBeVisible();
    await expect(section.getByRole('meter')).toHaveCount(published.historical_comparison.length * 2);
    await expect(section.getByText('Descriptive control · not an RDI forecast', { exact: true })).toBeVisible();
    await expect(section.getByText(/No RDI score or forecast is published/)).toBeVisible();
  } else {
    if (published?.status === 'evidence_mismatch') {
      await expect(section.getByRole('heading', { name: 'Historical comparison withheld', exact: true })).toBeVisible();
      await expect(section.getByRole('alert')).toContainText('Source evidence has changed');
    } else {
      await expect(section.getByRole('heading', { name: 'Reviewed evidence unavailable', exact: true })).toBeVisible();
      await expect(section.getByRole('alert')).toContainText('could not be verified');
    }
    await expect(section.getByRole('meter')).toHaveCount(0);
    await expect(section.getByRole('table')).toHaveCount(0);
    await expect(section.getByRole('group', { name: 'Historical comparison horizon' })).toHaveCount(0);
    await expect(section.getByRole('heading', { name: 'Historical price comparison', exact: true })).toHaveCount(0);
  }
  await openConsoleView(page, 'app');
  await expect(page.getByRole('region', { name: 'Daily research brief' })).toBeVisible();
});

// Bind current-state fixtures to the exact formal catalog shipped by this build.
// Signal dates below intentionally differ from formal historical cutoffs.
const formalRecords = JSON.parse(readFileSync(new URL('../dist/data/formal-model-runs/catalog.json', import.meta.url), 'utf8')).records;
const formal = formalRecords.find((row: { model_version_id: string }) => row.model_version_id === 'qqqi_qqq_tqqq_v4_3');
const formalIdentity = { formal_bundle_id: formal.canonical_bundle_id ?? formal.bundle_id, formal_run_id: formal.run_id,
  formal_evidence_cutoff: formal.evidence_cutoff };
const publishedFleet = JSON.parse(readFileSync(new URL('../dist/data/strategy-operations/snapshots.json', import.meta.url), 'utf8'));
const fleetCount = publishedFleet.records.length;
// Runtime rows bind to this build's verified canonical source, while public
// projections keep their own display hashes. Bad-identity fixtures below still
// reject mismatches; none of these mocks substitutes for real access tests.
const healthyFleet = { ...publishedFleet, records: publishedFleet.records.map((row: any) => {
  const identity = formalRecords.find((record: any) => record.model_version_id === row.model_version_id);
  if (!identity) throw new Error(`Missing formal fixture identity: ${row.model_version_id}`);
  return { ...row, source_identity: { ...row.source_identity,
    formal_bundle_id: identity.canonical_bundle_id ?? identity.bundle_id, formal_run_id: identity.run_id,
    formal_evidence_cutoff: identity.evidence_cutoff } };
}) };

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

async function mockOperations(page: Page, fullFleet = false) {
  await page.route('**/data/strategy-operations/snapshots.json', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fullFleet ? healthyFleet : operations) });
  });
}

async function assertNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
}

async function installProMembership(page: Page, options: {
  failFirst?: boolean; hangFirst?: boolean; mismatched?: boolean; stale?: boolean; manualFirst?: boolean;
  fullFleet?: boolean; partialPolicies?: boolean; failPolicyFirst?: boolean; badStrategy?: string;
} = {}): Promise<void> {
  await page.route('**/admin/shared/account-shell.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.addInitScript(({ fullSnapshot, fleetSnapshots, options }) => {
    let calls = 0;
    let aborts = 0;
    let policyReads = 0;
    let selectedIds: string[] = [];
    let snapshot = { loading: false, isPro: true, user: { id: 'pro-fixture' } };
    const listeners = new Set<(value: typeof snapshot) => void>();
    let releaseFirstRead: (() => void) | undefined;
    (window as any).__operationsFixture = {
      calls: () => calls,
      aborts: () => aborts,
      policyReads: () => policyReads,
      selectedIds: () => selectedIds,
      setPro: (isPro: boolean) => {
        snapshot = { ...snapshot, isPro, user: { id: isPro ? 'pro-fixture' : 'free-fixture' } };
        listeners.forEach(listener => listener(snapshot));
      },
      release: () => releaseFirstRead?.(),
    };
    (window as any).HaoAccount = {
      getState: () => snapshot,
      open: () => undefined,
      subscribe: (listener: (value: typeof snapshot) => void) => {
        listeners.add(listener);
        listener(snapshot);
        return () => { listeners.delete(listener); };
      },
      getClient: async () => ({
        from: (table: string) => {
          if (table === 'product_access_policies') {
            return {
              select: () => ({
                eq: async () => {
                  policyReads++;
                  if (options.failPolicyFirst && policyReads === 1) return { data: null, error: { message: 'Temporary policy failure' } };
                  const ids = options.fullFleet && !options.partialPolicies
                    ? fleetSnapshots.map(row => row.strategy_id) : ['qqq_rotation'];
                  return { data: ids.map(id => ({
                    product_code: 'alpha_engine',
                    resource_type: 'strategy',
                    resource_id: id,
                    required_tier: id === 'qqq_rotation' ? 'pro' : 'public',
                    updated_at: '2026-08-12T00:00:00Z',
                  })), error: null };
                },
              }),
            };
          }
          return {
            select: () => {
              let selected: string[] = [];
              let signal: AbortSignal;
              const read = async () => {
                calls += 1;
                const records = (options.fullFleet ? fleetSnapshots : [fullSnapshot])
                  .filter(record => selected.includes(record.strategy_id))
                  .map(record => ({ strategy_id: record.strategy_id, model_version_id: record.model_version_id,
                    snapshot: options.badStrategy === record.strategy_id
                      ? { ...record, source_identity: { ...record.source_identity, formal_bundle_id: 'b'.repeat(64) } } : record }));
                if (options.manualFirst && calls === 1) return new Promise(resolve => {
                  releaseFirstRead = () => resolve({ data: records, error: null });
                });
                if (options.hangFirst && calls === 1) return new Promise(resolve => {
                  signal.addEventListener('abort', () => {
                    aborts++;
                    resolve({ data: null, error: { message: 'aborted' } });
                  }, { once: true });
                });
                if (options.failFirst && calls === 1) return { data: null, error: { message: 'Temporary read failure' } };
                return { data: table === 'strategy_operation_snapshots' ? records : [], error: null };
              };
              const query: any = {
                in: (_column: string, ids: string[]) => { selected = ids; selectedIds = ids; return query; },
                abortSignal: (value: AbortSignal) => { signal = value; return query; },
                then: (fulfilled: any, rejected: any) => read().then(fulfilled, rejected),
              };
              return query;
            },
          };
        },
      }),
    };
  }, { fleetSnapshots: publishedFleet.records.map((row: any) => {
    // Public protected shells may retain an older formal identity. A synthetic
    // healthy runtime fixture must bind to the catalog shipped in this build;
    // the explicit badStrategy/mismatched branches still exercise rejection.
    const identity = formalRecords.find((record: any) => record.model_version_id === row.model_version_id);
    if (!identity) throw new Error(`Missing formal fixture identity: ${row.model_version_id}`);
    return ({
    ...runtimeOperation, strategy_id: row.strategy_id, model_version_id: row.model_version_id,
    decision_reason: `Batch fixture: ${row.strategy_id} verified`, factor_evidence: [], factor_freshness: 'unknown',
    source_identity: { ...runtimeOperation.source_identity,
      formal_bundle_id: identity.canonical_bundle_id ?? identity.bundle_id, formal_run_id: identity.run_id,
      formal_evidence_cutoff: identity.evidence_cutoff, ledger_fingerprint: `fixture-${row.strategy_id}` },
  }); }), fullSnapshot: {
    ...runtimeOperation,
    ...(options.mismatched ? { source_identity: { ...runtimeOperation.source_identity, formal_bundle_id: 'b'.repeat(64) } } : {}),
    ...(options.stale ? { data_freshness: 'stale', factor_freshness: 'stale', state_detail: 'degraded_delayed',
      staleness: { as_of: '2026-07-31', expected_cutoff: '2026-08-03', sessions_behind: 1, stale: true },
      decision_schedule: { signal_date: '2026-07-31', completed_through: '2026-08-03', cadence_sessions: 10,
        sessions_until_due: 9, state: 'within_cadence', execution_pending: true } } : {}),
  }, options });
}

test('the authorized fleet shares one read across overview and status', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await mockOperations(page, true);
  await installProMembership(page, { fullFleet: true });
  await page.goto('/#/app');
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  await expect(brief.getByRole('article')).toHaveCount(Math.min(3, fleetCount));
  await expect(brief.getByText('Changed at last evaluation', { exact: true })).toHaveCount(Math.min(3, fleetCount));
  expect(await fixtureCalls(page)).toBe(1);
  await openConsoleView(page, 'system');
  const current = page.getByRole('region', { name: 'Current strategy observations' });
  await expect(current.getByText('Changed at last evaluation', { exact: true })).toHaveCount(fleetCount);
  expect(await fixtureCalls(page)).toBe(1);
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await expect.poll(() => fixtureCalls(page)).toBe(2);
  await expect(current.getByText('Changed at last evaluation', { exact: true })).toHaveCount(fleetCount);
  await openConsoleView(page, 'app');
  expect(await fixtureCalls(page)).toBe(2);
  await assertNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('batch-overview.png') });
});

test('an explicitly mismatched public shell is blocked before runtime reads', async ({ page }) => {
  const cn = healthyFleet.records.find((row: any) => row.strategy_id === 'cn_27');
  const mismatched = { ...healthyFleet, records: healthyFleet.records.map((row: any) => row === cn
    ? { ...row, source_identity: { ...row.source_identity, formal_bundle_id: 'b'.repeat(64) } } : row) };
  await page.route('**/data/strategy-operations/snapshots.json', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(mismatched),
  }));
  await installProMembership(page, { fullFleet: true });
  await page.goto('/#/app');
  const row = page.getByTestId('fleet-cn_27_v1_3');
  const blocked = row.getByRole('button', { name: /^(Blocked|Inspect signal for CN_27 V1.3: Blocked)$/ }).first();
  await expect(blocked).toBeVisible();
  await expect(page.getByRole('region', { name: 'Daily research brief' })).toContainText('1 need attention');
  await blocked.click();
  await expect(page.getByRole('dialog').getByText('Operations formal bundle identity mismatch', { exact: true })).toBeVisible();
  await expect.poll(() => fixtureCalls(page)).toBe(1);
  expect(await page.evaluate(() => (window as any).__operationsFixture.selectedIds())).not.toContain('cn_27');
});

test('one invalid runtime row leaves independent observations readable', async ({ page }, testInfo) => {
  await mockOperations(page, true);
  await installProMembership(page, { fullFleet: true, badStrategy: 'us_x' });
  await page.goto('/#/system');
  const current = page.getByRole('region', { name: 'Current strategy observations' });
  await expect(current.getByText('Changed at last evaluation', { exact: true })).toHaveCount(fleetCount - 1);
  await expect(current.getByRole('article').filter({ hasText: 'US x1.3' }).getByText('Read unavailable', { exact: true })).toBeVisible();
  await expect(current.getByText('Batch fixture: us_x verified', { exact: true })).toHaveCount(0);
  expect(await fixtureCalls(page)).toBe(1);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('batch-one-rejected.png') });
});

test('a pro account does not request strategies with undeclared access policies', async ({ page }) => {
  await mockOperations(page, true);
  await installProMembership(page, { fullFleet: true, partialPolicies: true });
  await page.goto('/#/app');
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  await expect(brief.getByText('Changed at last evaluation', { exact: true })).toHaveCount(1);
  await expect(brief.getByText('Access required', { exact: true })).toHaveCount(Math.min(2, fleetCount - 1));
  expect(await fixtureCalls(page)).toBe(1);
  expect(await page.evaluate(() => (window as any).__operationsFixture.selectedIds())).toEqual(['qqq_rotation']);
  await expect(brief.getByText('Batch fixture: us_x verified', { exact: true })).toHaveCount(0);
});

test('failed access policies recover through operations retry without repeating healthy policy reads', async ({ page }) => {
  await mockOperations(page, true);
  await installProMembership(page, { fullFleet: true, failPolicyFirst: true });
  await page.goto('/#/app');
  const reader = page.getByRole('region', { name: 'Current operations reader' });
  await expect(reader.getByText('Strategy access policies could not be verified.', { exact: false })).toBeVisible();
  expect(await fixtureCalls(page)).toBe(0);
  await reader.getByRole('button', { name: 'Retry operations', exact: true }).click();
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  await expect(brief.getByText('Changed at last evaluation', { exact: true })).toHaveCount(Math.min(3, fleetCount));
  expect(await fixtureCalls(page)).toBe(1);
  expect(await page.evaluate(() => (window as any).__operationsFixture.policyReads())).toBe(2);
  await reader.getByRole('button', { name: 'Refresh operations', exact: true }).click();
  await expect.poll(() => fixtureCalls(page)).toBe(2);
  expect(await page.evaluate(() => (window as any).__operationsFixture.policyReads())).toBe(2);
});

test('overview brief explains the last evaluation and retains its actual dates', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/app');
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  const row = brief.getByRole('article', { name: 'QQQR v4.3 daily observation' });
  await expect(brief.getByRole('article')).toHaveCount(3);
  await expect(page.getByRole('region', { name: 'Formal strategy fleet' }).getByRole('article')).toHaveCount(4);
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toBeVisible();
  await expect(row.getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(row.getByText('Observed 2026-07-31 · target dated 2026-07-31', { exact: false })).toBeVisible();
  await page.getByRole('heading', { name: 'What are the strategies doing now?', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('daily-research-brief-first-viewport.png') });
  await row.getByText('Decision evidence', { exact: true }).click();
  await expect(row.getByText('VIX close: calm · veto · observed 2026-07-31')).toBeVisible();
  expect(errors).toEqual([]);
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('daily-research-brief.png'), fullPage: true });
});

test('overview brief separates read retry from data recovery', async ({ page }) => {
  await mockOperations(page);
  await installProMembership(page, { failFirst: true, stale: true });
  await page.goto('/#/app');
  const row = page.getByRole('region', { name: 'Daily research brief' }).getByRole('article', { name: 'QQQR v4.3 daily observation' });
  await row.getByRole('button', { name: 'Retry reading observations' }).click();
  await expect(row.getByText('Stale', { exact: true })).toBeVisible();
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toHaveCount(0);
  await row.getByText('Recovery steps', { exact: true }).click();
  await expect(row.getByRole('link', { name: 'Open data refresh workflow' })).toHaveAttribute('href', /formal-backtest-refresh.yml$/);
  await row.getByRole('link', { name: 'Open operating status' }).click();
  await expect(page).toHaveURL(/#\/system$/);
  await assertNoHorizontalOverflow(page);
});

test('strategy current operations are authorized by runtime policy and hydrated from the runtime store', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const githubApiRequests: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('request', (request) => {
    if (request.url().startsWith('https://api.github.com/')) githubApiRequests.push(request.url());
  });
  await mockOperations(page);
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
    path: testInfo.outputPath('strategy-operations.png'),
    fullPage: true,
  });
});

test('current operations recover from a failed read without reloading formal evidence', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await mockOperations(page);
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
  await mockOperations(page);
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
  await mockOperations(page);
  await installProMembership(page, { hangFirst: true });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  const reader = page.getByRole('region', { name: 'Current operations reader' });
  await expect(reader.getByRole('button', { name: 'Reading operations' })).toBeDisabled();
  // Ensure the public identity has arrived before advancing the runtime deadline.
  await expect(page.getByText('Protected current operations are unavailable.', { exact: false })).toBeVisible();
  await page.clock.fastForward(15_000);
  await expect(reader.getByText('Operations reading timed out.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__operationsFixture.aborts())).toBe(1);
  await reader.getByRole('button', { name: 'Retry operations' }).click();
  await expect(page.getByRole('region', { name: 'Current decision state' }).getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(reader.getByRole('button', { name: 'Refresh operations' })).toBeEnabled();
  expect(errors).toEqual([]);
});

test('stale observations require attention while cadence and execution stay explicit', async ({ page }) => {
  await mockOperations(page);
  await installProMembership(page, { stale: true });
  await page.goto('/#/strategies/qqqi_qqq_tqqq_v4_3');
  await expect(page.getByRole('button', { name: 'Refresh operations' })).toBeEnabled();
  await expect(page.getByText('Next evaluation in 9 exchange sessions;', { exact: false })).toBeVisible();
  await expect(page.getByText('Execution evidence is still pending;', { exact: false })).toBeVisible();
  await page.goto('/#/app');
  // This fixture publishes only QQQ: four missing strategies must leave QQQ
  // readable while the reader offers recovery for their independent failures.
  await expect(page.getByRole('button', { name: 'Retry operations' })).toBeEnabled();
  await page.getByLabel('Signal filter', { exact: true }).selectOption('attention');
  const row = page.getByTestId('fleet-qqqi_qqq_tqqq_v4_3');
  await expect(row).toBeVisible();
  await expect(row.getByRole('button', { name: /^(Stale|Inspect signal for .*: Stale)$/ }).filter({ visible: true })).toHaveCount(1);
  await assertNoHorizontalOverflow(page);
});

test('operating status reads the same verified current observation as the daily brief', async ({ page }) => {
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/system');
  await expect(page.getByRole('heading', { name: 'Operating Status', exact: true })).toBeVisible();
  const row = page.getByRole('region', { name: 'Current strategy observations' }).getByRole('article').filter({ hasText: 'QQQR v4.3' });
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toBeVisible();
  await expect(row.getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(row.getByText('Observed 2026-07-31', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toBeVisible();
});


async function openConsoleView(page: Page, path: 'app' | 'system') {
  const mobile = (page.viewportSize()?.width ?? 1280) < 768;
  const navigation = page.getByRole('navigation', { name: mobile ? 'Primary' : 'Strategy console navigation', exact: true });
  await navigation.locator(`a[href="#/${path}"]`).click();
  await expect(page.getByRole('main').getByRole('heading', {
    name: path === 'app' ? 'What are the strategies doing now?' : 'Operating Status', level: 1, exact: true,
  })).toBeVisible();
}

const fixtureCalls = (page: Page) => page.evaluate(() => (window as any).__operationsFixture.calls() as number);

test('navigation reuses one verified read and manual refresh remains read-only', async ({ page }) => {
  let snapshotReads = 0, catalogReads = 0, healthReads = 0;
  page.on('request', request => {
    if (request.url().includes('/data/strategy-operations/snapshots.json')) snapshotReads++;
    if (request.url().includes('/data/formal-model-runs/catalog.json')) catalogReads++;
    if (request.url().includes('/data/strategy-operations/system-health.json')) healthReads++;
  });
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/app');
  await expect(page.getByRole('region', { name: 'Daily research brief' }).getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect.poll(() => fixtureCalls(page)).toBe(1);
  const initialCatalogReads = catalogReads;
  await openConsoleView(page, 'system');
  await page.getByRole('region', { name: 'Current strategy observations' }).getByRole('link', { name: 'QQQR v4.3', exact: true }).click();
  await expect(page.getByRole('main').getByRole('heading', { name: 'QQQR v4.3', level: 1, exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Current operations reader' }).getByText('published operations could not be verified.', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Current decision state' }).getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await openConsoleView(page, 'app');
  expect(await fixtureCalls(page)).toBe(1);
  expect(snapshotReads).toBe(1);
  expect(healthReads).toBe(1);
  await page.getByRole('button', { name: 'Retry operations', exact: true }).click();
  await expect.poll(() => fixtureCalls(page)).toBe(2);
  await expect(page.getByRole('button', { name: 'Retry operations', exact: true })).toBeEnabled();
  expect(snapshotReads).toBe(2);
  expect(catalogReads).toBe(initialCatalogReads);
});

test('returning to the visible tab refreshes operations without reloading formal evidence', async ({ page }) => {
  let catalogReads = 0;
  page.on('request', request => { if (request.url().includes('/data/formal-model-runs/catalog.json')) catalogReads++; });
  await mockOperations(page);
  await installProMembership(page);
  await page.goto('/#/system');
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  expect(await fixtureCalls(page)).toBe(1);
  const initialCatalogReads = catalogReads;
  await page.evaluate(async () => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
  });
  expect(await fixtureCalls(page)).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect.poll(() => fixtureCalls(page)).toBe(2);
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  expect(catalogReads).toBe(initialCatalogReads);
});

test('a late authorized response cannot reappear after an account downgrade across views', async ({ page }) => {
  await mockOperations(page);
  await installProMembership(page, { manualFirst: true });
  await page.goto('/#/app');
  await expect.poll(() => fixtureCalls(page)).toBe(1);
  await page.evaluate(() => (window as any).__operationsFixture.setPro(false));
  const brief = page.getByRole('region', { name: 'Daily research brief' });
  await expect(brief.getByRole('article', { name: 'QQQR v4.3 daily observation' }).getByText('Access required', { exact: true })).toBeVisible();
  await openConsoleView(page, 'system');
  await page.evaluate(() => (window as any).__operationsFixture.release());
  await expect(page.getByRole('region', { name: 'Current strategy observations' }).getByRole('article').filter({ hasText: 'QQQR v4.3' }).getByText('Access required', { exact: true })).toBeVisible();
  await page.getByRole('region', { name: 'Current strategy observations' }).getByRole('link', { name: 'QQQR v4.3', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Current holdings and live signals are protected', exact: true })).toBeVisible();
  await expect(page.getByText('QQQ repair with easing volatility', { exact: true })).toHaveCount(0);
  await page.evaluate(() => (window as any).__operationsFixture.setPro(true));
  await expect(page.getByRole('region', { name: 'Current decision state' }).getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  expect(await fixtureCalls(page)).toBe(2);
});


test('a failed publication refresh keeps the prior observation dated until a verified retry', async ({ page }) => {
  await page.clock.install();
  await installProMembership(page);
  let publicationReads = 0;
  await page.route('**/data/strategy-operations/snapshots.json', async route => {
    publicationReads++;
    if (publicationReads === 2) return new Promise(() => {});
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(operations) });
  });
  await page.goto('/#/app');
  const row = page.getByRole('region', { name: 'Daily research brief' }).getByRole('article', { name: 'QQQR v4.3 daily observation' });
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Retry operations', exact: true }).click();
  await expect(row.getByText('Previous verified read', { exact: true })).toBeVisible();
  await expect(row.getByText('QQQ repair with easing volatility', { exact: true })).toBeVisible();
  await expect(row.getByText('Observed 2026-07-31 · target dated 2026-07-31', { exact: false })).toBeVisible();
  await page.clock.fastForward(15_000);
  await expect(page.getByText('Operations reading timed out.', { exact: false })).toBeVisible();
  await expect(row.getByText('Previous verified read', { exact: true })).toBeVisible();
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toHaveCount(0);
  await page.getByRole('region', { name: 'Current operations reader' }).getByRole('button', { name: 'Retry operations', exact: true }).click();
  await expect(row.getByText('Changed at last evaluation', { exact: true })).toBeVisible();
  expect(await fixtureCalls(page)).toBe(2);
});
