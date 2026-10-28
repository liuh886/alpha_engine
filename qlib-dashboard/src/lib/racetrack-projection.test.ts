/// <reference types="node" />
import { createHash, webcrypto } from 'node:crypto';
import { TextEncoder } from 'node:util';
import { racetrackFixture } from '../../e2e/fixtures/racetrack';
import { contiguousSegments, displayWindow, parseRaceManifest, parseRaceScoreboard, ProjectionClient } from './racetrack-projection';

beforeEach(() => { vi.stubGlobal('crypto', webcrypto); vi.stubGlobal('TextEncoder', TextEncoder); });
afterEach(() => vi.unstubAllGlobals());

function transport(f = racetrackFixture()) {
  return vi.fn(async (url: RequestInfo | URL) => {
    const path = String(url).replace(`/__racetrack/${f.manifest.market}/`, '');
    const value = path === 'manifest.json' ? JSON.stringify(f.manifest) : f.files[path];
    return new Response(value ?? '', { status: value ? 200 : 404 });
  });
}
test('reads only manifest and scoreboard first, verifies a detail on demand, caches by vintage', async () => {
  const fixture = racetrackFixture(); const fetcher = transport(fixture); const client = new ProjectionClient(fetcher);
  const signal = new AbortController().signal;
  const projection = await client.load('us', signal);
  expect(fetcher).toHaveBeenCalledTimes(2);
  const detail = await client.runner(projection, projection.scoreboard.entries[0], signal);
  expect(detail.thesis).toContain('Synthetic thesis'); expect(detail.model_weights[0].weight).toBe(.7);
  expect(fetcher).toHaveBeenCalledTimes(3);
  await client.runner(projection, projection.scoreboard.entries[0], signal);
  expect(fetcher).toHaveBeenCalledTimes(3);
  client.clear(); await client.load('us', signal); expect(fetcher).toHaveBeenCalledTimes(5);
});
test('default browser fetch keeps its required global receiver', async () => {
  const mock = transport();
  vi.stubGlobal('fetch', function(this: unknown, ...args: Parameters<typeof fetch>) {
    expect(this).toBe(globalThis);
    return mock(args[0]);
  });
  await expect(new ProjectionClient().load('us', new AbortController().signal)).resolves.toHaveProperty('scoreboard');
});

test('admitted runners with undocumented logic retain their verified thesis and model weights', async () => {
  const fixture = racetrackFixture();
  const entry = fixture.scoreboard.entries[0];
  const ref = fixture.manifest.artifacts[fixture.manifest.runner_details[entry.runner_id]];
  const detail = JSON.parse(fixture.files[ref.path]);
  detail.selection_logic = ''; detail.rebalance_logic = '';
  fixture.files[ref.path] = JSON.stringify(detail);
  ref.size_bytes = Buffer.byteLength(fixture.files[ref.path]);
  ref.sha256 = createHash('sha256').update(fixture.files[ref.path]).digest('hex');
  const client = new ProjectionClient(transport(fixture));
  const signal = new AbortController().signal;
  const projection = await client.load('us', signal);
  await expect(client.runner(projection, projection.scoreboard.entries[0], signal)).resolves.toMatchObject({
    thesis: detail.thesis, selection_logic: '', rebalance_logic: '', model_weights: detail.model_weights,
  });
});
test('rejects altered bytes and does not cache an unverified artifact', async () => {
  const fixture = racetrackFixture(); const fetcher = transport(fixture); const client = new ProjectionClient(fetcher);
  const path = fixture.manifest.artifacts.scoreboard_latest.path; const raw = fixture.files[path];
  fixture.files[path] = raw + ' ';
  await expect(client.load('us', new AbortController().signal)).rejects.toThrow('hash/size');
  fixture.files[path] = raw;
  await expect(client.load('us', new AbortController().signal)).resolves.toHaveProperty('scoreboard');
});
test.each(['market', 'version', 'escape', 'personal', 'unsafe_size', 'trade_ready'])('rejects unsafe manifest: %s', damage => {
  const m: any = structuredClone(racetrackFixture().manifest);
  if (damage === 'market') m.pool_id = 'cn_selected_equities_v3';
  if (damage === 'version') m.pipeline_version = 'future';
  if (damage === 'escape') m.artifacts.scoreboard_latest.path = '../secret.json';
  if (damage === 'personal') m.account_id = 'private';
  if (damage === 'unsafe_size') m.artifacts.scoreboard_latest.size_bytes = 1e12;
  if (damage === 'trade_ready') m.trade_ready = true;
  expect(() => parseRaceManifest(m, 'us')).toThrow();
});
test.each(['dates', 'length', 'rank', 'metric', 'identity', 'policy'])('rejects mismatched scoreboard: %s', damage => {
  const f = racetrackFixture(); const s: any = structuredClone(f.scoreboard);
  if (damage === 'dates') s.dates[1] = s.dates[0];
  if (damage === 'length') s.benchmarks.macro.pop();
  if (damage === 'rank') s.entries[1].current_rank = 1;
  if (damage === 'metric') s.entries[0].return_1m = NaN;
  if (damage === 'identity') s.season_id = 'other-season';
  if (damage === 'policy') delete s.period_policy;
  expect(() => parseRaceScoreboard(s, parseRaceManifest(f.manifest, 'us'))).toThrow();
});
test('window slicing and rebasing preserve gaps and published rankings', () => {
  const f = racetrackFixture(); const m = parseRaceManifest(f.manifest, 'us');
  const s = parseRaceScoreboard(f.scoreboard, m); const original = JSON.stringify(s.entries);
  s.top_runners_nav[s.entries[0].runner_id][5] = null;
  const display = displayWindow(s, 3);
  expect(display.dates[0]).toBe('2026-08-03');
  expect(display.series[0].values[0]).toBe(1);
  expect(display.series[2].values[3]).toBeNull();
  expect(JSON.stringify(s.entries)).toBe(original);
  expect(contiguousSegments(display.dates, display.series[2].values)).toHaveLength(2);
});
test('baseline-only is valid and null returns never become zero', async () => {
  const f = racetrackFixture('cn', 0); const client = new ProjectionClient(transport(f));
  const result = await client.load('cn', new AbortController().signal);
  expect(result.scoreboard.status).toBe('diagnostic_baseline_only');
  expect(displayWindow(result.scoreboard, 12).series).toHaveLength(2);
});
