import { afterEach, describe, expect, it, vi } from 'vitest';
import manifestFixture from '../../../tests/fixtures/model_run_bundle_v2/manifest.json';
import summaryFixture from '../../../tests/fixtures/model_run_bundle_v2/summary.json';
import { loadFormalRuns } from './governed-run';
import { canonicalJson, sha256Text } from './model-run-bundle-v2';

async function formalAssets(summarySizeDelta = 0) {
  const manifest = {
    ...structuredClone(manifestFixture),
    publication_channel: 'formal',
    publication_status: 'accepted_formal_baseline',
  };
  manifest.sections[0].byte_size! += summarySizeDelta;
  const identity = { ...manifest } as Record<string, unknown>;
  delete identity.bundle_id;
  manifest.bundle_id = await sha256Text(canonicalJson(identity));
  const manifestText = canonicalJson(manifest);
  const catalog = {
    schema_version: '2.0.0', channel: 'formal', generated_at: manifest.generated_at,
    research_only: true, trade_ready: false,
    records: [{
      model_family_id: manifest.model_family_id, model_version_id: manifest.model_version_id,
      model_kind: manifest.model_kind, run_id: manifest.run_id, bundle_id: manifest.bundle_id,
      publication_status: manifest.publication_status, evidence_cutoff: manifest.evidence_cutoff,
      manifest_path: 'fixture/manifest.json', manifest_sha256: await sha256Text(manifestText),
    }],
  };
  const assets = new Map([
    ['/data/formal-model-runs/fixture/manifest.json', manifestText],
    ['/data/formal-model-runs/fixture/summary.json', canonicalJson(summaryFixture)],
  ]);
  const fetcher = vi.fn(async (url: string) => {
    const body = url === '/data/formal-model-runs/catalog.json' ? JSON.stringify(catalog) : assets.get(url);
    return new Response(body ?? '', { status: body === undefined ? 404 : 200 });
  });
  vi.stubGlobal('fetch', fetcher);
  return { catalog, manifest, assets, fetcher };
}

afterEach(() => vi.unstubAllGlobals());

describe('formal-only console reader', () => {
  it('loads the accepted summary while keeping unavailable required evidence explicit', async () => {
    const { manifest, fetcher } = await formalAssets();
    const result = await loadFormalRuns();
    expect(result.errors).toEqual([]);
    expect(result.runs).toHaveLength(1);
    expect(result.runs[0]).toMatchObject({
      channel: 'formal', publicationStatus: 'accepted_formal_baseline',
      bundleId: manifest.bundle_id, evidenceStatus: 'blocked', summary: summaryFixture,
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls.every(([url]) => url.startsWith('/data/formal-model-runs/'))).toBe(true);
  });

  it.each(['preview', 'local'])('rejects a %s catalog without falling back to another reader', async channel => {
    const { catalog, fetcher } = await formalAssets();
    catalog.channel = channel;
    const result = await loadFormalRuns();
    expect(result.runs).toEqual([]);
    expect(result.errors[0]).toContain('catalog contract is invalid');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('rejects nonaccepted publication and weakened research boundaries', async () => {
    const { catalog } = await formalAssets();
    catalog.records[0].publication_status = 'ci_validated_preview';
    expect((await loadFormalRuns()).errors[0]).toContain('Non-formal record');
    catalog.trade_ready = true;
    expect((await loadFormalRuns()).errors[0]).toContain('research boundary');
  });

  it.each(['manifest', 'summary'])('rejects corrupted %s bytes', async section => {
    const { assets } = await formalAssets();
    const path = `/data/formal-model-runs/fixture/${section}.json`;
    assets.set(path, `${assets.get(path)} `);
    const result = await loadFormalRuns();
    expect(result.runs).toEqual([]);
    expect(result.errors[0]).toMatch(/mismatch/);
  });

  it('requires the declared summary size as well as its digest', async () => {
    await formalAssets(1);
    const result = await loadFormalRuns();
    expect(result.runs).toEqual([]);
    expect(result.errors[0]).toContain('summary integrity mismatch');
  });

  it('keeps a failed formal request unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    const result = await loadFormalRuns();
    expect(result.runs).toEqual([]);
    expect(result.errors[0]).toContain('(503)');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
