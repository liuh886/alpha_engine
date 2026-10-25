import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadSecurityEvidence } from '../src/lib/security-evidence';
import { loadFormalRuns } from '../src/lib/governed-run';
import { boundSecurityEvents } from '../src/lib/security-evidence';

afterEach(() => vi.unstubAllGlobals());
function publicFetch() {
  vi.stubGlobal('fetch', async (url: string) => {
    try { return new Response(await readFile(path.resolve('public', url.replace(/^\.?\//, '')), 'utf8')); }
    catch { return new Response('not found', { status: 404 }); }
  });
}
describe('published instrument history', () => {
  it('loads hash-verified prices and exact current formal events in both markets', async () => {
    publicFetch();
    const { runs, errors } = await loadFormalRuns();
    expect(errors).toEqual([]);
    for (const [market, requested] of [['us', 'QQQ'], ['cn', 'BYD'], ['cn', '000300']] as const) {
      const evidence = await loadSecurityEvidence(market, requested);
      expect(evidence.bars.length).toBeGreaterThan(100);
      expect(evidence.events.some(event => event.model_id === 'cn_x1_2')).toBe(false);
      if (requested === '000300') expect(boundSecurityEvents(evidence, runs)).toEqual([]);
      else expect(boundSecurityEvents(evidence, runs).length).toBeGreaterThan(0);
    }
  });
  it('fails closed on a tampered symbol payload', async () => {
    publicFetch();
    const original = globalThis.fetch;
    vi.stubGlobal('fetch', async (url: string) => url.endsWith('/symbols/QQQ.json')
      ? new Response((await (await original(url)).text()) + ' ')
      : original(url));
    await expect(loadSecurityEvidence('us', 'QQQ')).rejects.toThrow(/checksum/);
  });
});
