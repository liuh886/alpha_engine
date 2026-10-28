// Read already-published projections on the operator's machine. Never executes
// Python, refreshes data, copies projections into public/, or accepts file paths.
import { readFile, realpath, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';

const MAX_BYTES = 8 * 1024 * 1024;
const hashPattern = /^[a-f0-9]{64}$/;
const pools = { us: 'us_selected_equities_v2', cn: 'cn_selected_equities_v3' };
const loopback = address => ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address);

async function containedRead(root, path, limit = MAX_BYTES) {
  const base = await realpath(root);
  const target = await realpath(resolve(base, path));
  const rel = relative(base, target);
  if (isAbsolute(rel) || rel.startsWith('..') || (await stat(target)).size > limit) throw new Error('Invalid projection path or size');
  return readFile(target);
}

function manifestFrom(bytes, market, version) {
  const manifest = JSON.parse(bytes.toString('utf8'));
  const supported = manifest.schema_version === '1.0' && manifest.pipeline_version === '1.1.0'
    || manifest.schema_version === '2.0' && manifest.pipeline_version === '2.0.0';
  if (!supported
      || manifest.market !== market || manifest.pool_id !== pools[market]
      || manifest.research_only !== true || manifest.trade_ready !== false
      || !hashPattern.test(manifest.release_id) || (version && manifest.release_id !== version)
      || !manifest.artifacts?.scoreboard_latest) throw new Error('Invalid projection identity');
  for (const artifact of Object.values(manifest.artifacts)) {
    if (typeof artifact.path !== 'string' || !artifact.path.startsWith(`versions/${manifest.release_id}/`)
        || !/^versions\/[a-f0-9]{64}\/(scoreboard_latest\.json|archive\/scoreboard_\d{4}-\d{2}-\d{2}\.json|runners\/[a-f0-9]{64}\.json)$/.test(artifact.path)
        || !hashPattern.test(artifact.sha256) || !Number.isSafeInteger(artifact.size_bytes)
        || artifact.size_bytes < 0 || artifact.size_bytes > MAX_BYTES) throw new Error('Invalid projection artifact');
  }
  if (manifest.schema_version === '2.0') {
    if (market !== 'us' || !manifest.local_evidence || !Object.keys(manifest.local_evidence).length
        || Object.keys(manifest.local_evidence).length !== manifest.runner_count) throw new Error('Missing first-season Q evidence');
    for (const ref of Object.values(manifest.local_evidence)) {
      if (typeof ref.path !== 'string' || !ref.path.startsWith(`versions/${manifest.release_id}/evidence/`)
          || !/^versions\/[a-f0-9]{64}\/evidence\/[a-f0-9]{64}\.jsonl$/.test(ref.path)
          || !hashPattern.test(ref.sha256) || !hashPattern.test(ref.tip_hash)
          || !Number.isSafeInteger(ref.size_bytes) || ref.size_bytes <= 0 || ref.size_bytes > MAX_BYTES
          || !Number.isSafeInteger(ref.event_count) || ref.event_count <= 0) throw new Error('Invalid local Q evidence');
    }
  }
  return manifest;
}

export function createRacetrackHandler(projectionRoot) {
  return async (request, response, next) => {
    if (!request.url?.startsWith('/__racetrack/')) return next();
    const reply = (status, body) => {
      response.removeHeader?.('Access-Control-Allow-Origin');
      response.removeHeader?.('Access-Control-Allow-Credentials');
      response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      response.end(body);
    };
    const host = request.headers.host ?? '';
    if (request.method !== 'GET' || !loopback(request.socket.remoteAddress)
        || !/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host)
        || request.headers['sec-fetch-site'] === 'cross-site'
        || (request.headers.origin && request.headers.origin !== `http://${host}`
          && request.headers.origin !== `https://${host}`)) {
      return reply(403, '{"error":"Local operator access required"}');
    }
    const match = request.url.match(/^\/__racetrack\/(us|cn)\/(manifest\.json|versions\/[a-f0-9]{64}\/(?:scoreboard_latest\.json|archive\/scoreboard_\d{4}-\d{2}-\d{2}\.json|runners\/[a-f0-9]{64}\.json))$/);
    if (!match) return reply(404, '{"error":"Unknown projection resource"}');
    const [, market, path] = match;
    const root = resolve(projectionRoot, market);
    try {
      const base = await realpath(projectionRoot);
      const marketRoot = await realpath(root);
      const rel = relative(base, marketRoot);
      if (isAbsolute(rel) || rel.startsWith('..')) throw new Error('Market root escapes the publication boundary');
      const version = path === 'manifest.json' ? undefined : path.split('/')[1];
      const manifestPath = version ? `versions/${version}/manifest.json` : 'manifest.json';
      const bytes = await containedRead(root, manifestPath, 512 * 1024);
      const manifest = manifestFrom(bytes, market, version);
      // Verify retained private Q evidence without exposing an evidence route.
      for (const ref of Object.values(manifest.local_evidence ?? {})) {
        const raw = await containedRead(root, ref.path);
        if (raw.byteLength !== ref.size_bytes || createHash('sha256').update(raw).digest('hex') !== ref.sha256) {
          throw new Error('Retained Q evidence hash/size mismatch');
        }
      }
      if (!version) return reply(200, bytes);
      const artifact = Object.values(manifest.artifacts).find(item => item.path === path);
      if (!artifact) throw new Error('Resource is not declared in the immutable manifest');
      const content = await containedRead(root, path);
      if (content.byteLength !== artifact.size_bytes
          || createHash('sha256').update(content).digest('hex') !== artifact.sha256) throw new Error('Artifact integrity mismatch');
      return reply(200, content);
    } catch (error) {
      return reply(error.code === 'ENOENT' ? 404 : 422,
        JSON.stringify({ error: error.code === 'ENOENT' ? 'Projection has not been published locally' : 'Projection verification failed' }));
    }
  };
}

export function racetrackLocalProjection() {
  const root = fileURLToPath(new URL('../../data/racetrack/projections/', import.meta.url));
  const install = server => { server.middlewares.use(createRacetrackHandler(root)); };
  return { name: 'racetrack-local-projection', configureServer: install, configurePreviewServer: install };
}
