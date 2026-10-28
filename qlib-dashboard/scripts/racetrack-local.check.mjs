import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, relative } from 'node:path';
import { once } from 'node:events';
import { createRacetrackHandler } from './racetrack-local.mjs';
import { racetrackFixture } from '../e2e/fixtures/racetrack.ts';

async function withServer(run) {
  const root = await mkdtemp(join(tmpdir(), 'alpha-racetrack-'));
  const fixture = racetrackFixture();
  const marketRoot = join(root, 'us');
  await mkdir(marketRoot, { recursive: true });
  for (const [path, raw] of Object.entries(fixture.files)) {
    await mkdir(resolve(marketRoot, path, '..'), { recursive: true });
    await writeFile(join(marketRoot, path), raw);
  }
  const manifest = JSON.stringify(fixture.manifest);
  await writeFile(join(marketRoot, 'manifest.json'), manifest);
  await writeFile(join(marketRoot, 'versions', fixture.manifest.release_id, 'manifest.json'), manifest);
  const handler = createRacetrackHandler(root);
  const server = createServer((req, res) => handler(req, res, () => { res.writeHead(404); res.end(); }));
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  try { await run({ root, marketRoot, fixture, base: `http://127.0.0.1:${server.address().port}` }); }
  finally {
    server.closeAllConnections(); server.close(); await once(server, 'close');
    assert.match(relative(resolve(tmpdir()), resolve(root)), /^alpha-racetrack-[^/\\]+$/);
    await rm(root, { recursive: true, force: true });
  }
}
test('serves only published manifest and hash-verified artifact bytes', () => withServer(async ({ fixture, base }) => {
  const response = await fetch(`${base}/__racetrack/us/manifest.json`);
  assert.equal(response.status, 200); assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('access-control-allow-origin'), null);
  const artifact = fixture.manifest.artifacts.scoreboard_latest;
  assert.equal(await (await fetch(`${base}/__racetrack/us/${artifact.path}`)).text(), fixture.files[artifact.path]);
  assert.equal((await fetch(`${base}/__racetrack/cn/manifest.json`)).status, 404);
}));
test('refuses cross-origin reads, non-GET and arbitrary resource paths', () => withServer(async ({ base }) => {
  assert.equal((await fetch(`${base}/__racetrack/us/manifest.json`, { headers: { Origin: 'https://untrusted.example' } })).status, 403);
  assert.equal((await fetch(`${base}/__racetrack/us/manifest.json`, { method: 'POST' })).status, 403);
  assert.equal((await fetch(`${base}/__racetrack/us/configs/private.json`)).status, 404);
}));
test('pinned old vintage stays readable after the current pointer changes', () => withServer(async ({ fixture, marketRoot, base }) => {
  await writeFile(join(marketRoot, 'manifest.json'), JSON.stringify({ ...fixture.manifest, release_id: 'f'.repeat(64) }));
  const path = fixture.manifest.artifacts.scoreboard_latest.path;
  assert.equal((await fetch(`${base}/__racetrack/us/${path}`)).status, 200);
  assert.equal((await fetch(`${base}/__racetrack/us/manifest.json`)).status, 422);
}));
test('tampered content and symlink escapes fail closed', () => withServer(async ({ fixture, root, marketRoot, base }) => {
  const path = fixture.manifest.artifacts.scoreboard_latest.path;
  await writeFile(join(marketRoot, path), '{}');
  assert.equal((await fetch(`${base}/__racetrack/us/${path}`)).status, 422);
  await rm(join(marketRoot, path));
  const outside = join(root, 'outside.json'); await writeFile(outside, fixture.files[path]);
  try { await symlink(outside, join(marketRoot, path)); }
  catch (error) { if (error.code === 'EPERM') return; throw error; }
  assert.equal((await fetch(`${base}/__racetrack/us/${path}`)).status, 422);
}));
test('non-loopback clients are refused before filesystem access', async () => {
  let status;
  await createRacetrackHandler('/not-readable')({ url: '/__racetrack/us/manifest.json', method: 'GET',
    headers: { host: 'localhost:1234' }, socket: { remoteAddress: '203.0.113.1' } }, {
    writeHead(code) { status = code; }, end() {},
  }, () => assert.fail('must not fall through'));
  assert.equal(status, 403);
});
