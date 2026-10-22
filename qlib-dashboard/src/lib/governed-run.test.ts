import { afterEach, describe, expect, it, vi } from 'vitest';
import manifestFixture from '../../../tests/fixtures/model_run_bundle_v2/manifest.json';
import summaryFixture from '../../../tests/fixtures/model_run_bundle_v2/summary.json';
import { loadFormalRuns, loadRunSection } from './governed-run';
import { canonicalJson, sha256Text } from './model-run-bundle-v2';

async function formalAssets(summarySizeDelta = 0, performanceText?: string) {
  const manifest = {
    ...structuredClone(manifestFixture),
    publication_channel: 'formal',
    publication_status: 'accepted_formal_baseline',
  };
  manifest.sections[0].byte_size! += summarySizeDelta;
  if (performanceText !== undefined) {
    Object.assign(manifest.sections.find(section => section.section_id === 'performance')!, {
      availability_status: 'available', reason: null, path: 'performance.json',
      sha256: await sha256Text(performanceText), byte_size: new TextEncoder().encode(performanceText).byteLength,
      media_type: 'application/json',
    });
  }
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
  if (performanceText !== undefined) assets.set('/data/formal-model-runs/fixture/performance.json', performanceText);
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

async function sectionFixture(text = canonicalJson({ report: [{ date: '2026-07-31', account: 100 }] })) {
  const fixture = await formalAssets(0, text);
  const { runs, errors } = await loadFormalRuns();
  expect(errors).toEqual([]);
  fixture.fetcher.mockClear();
  return { ...fixture, run: runs[0], text };
}

describe('verified formal section reuse', () => {
  it('shares concurrent and repeated reads while isolating consumer mutations', async () => {
    const { run, fetcher } = await sectionFixture();
    const [first, second] = await Promise.all([loadRunSection(run, 'performance'), loadRunSection(run, 'performance')]);
    expect(first).toEqual(second);
    (first as { report: { account: number }[] }).report[0].account = -1;
    expect(second).toEqual({ report: [{ date: '2026-07-31', account: 100 }] });
    expect(await loadRunSection(run, 'performance')).toEqual(second);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each(['request', 'hash', 'size', 'json'])('retries after a failed %s verification', async failure => {
    const { run, fetcher } = await sectionFixture(failure === 'json' ? 'invalid json' : undefined);
    const section = run.manifest!.sections.find(candidate => candidate.section_id === 'performance')!;
    if (failure === 'request') fetcher.mockResolvedValueOnce(new Response('', { status: 503 }));
    if (failure === 'hash') fetcher.mockResolvedValueOnce(new Response('{}'));
    if (failure === 'size') section.byte_size! += 1;
    await expect(loadRunSection(run, 'performance')).rejects.toThrow();
    // The same declared identity must retry rather than replay a cached rejection.
    if (failure === 'request' || failure === 'hash') {
      expect(await loadRunSection(run, 'performance')).toEqual({ report: [{ date: '2026-07-31', account: 100 }] });
      expect(fetcher).toHaveBeenCalledTimes(2);
      await loadRunSection(run, 'performance');
      expect(fetcher).toHaveBeenCalledTimes(2);
    } else {
      await expect(loadRunSection(run, 'performance')).rejects.toThrow();
      expect(fetcher).toHaveBeenCalledTimes(2);
    }
  });

  it('keeps a fresh catalog run independent even when its bundle is unchanged', async () => {
    const { run, fetcher } = await sectionFixture();
    await loadRunSection(run, 'performance');
    const { runs } = await loadFormalRuns();
    fetcher.mockClear();
    await loadRunSection(runs[0], 'performance');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each(['bundleId', 'manifestSha256', 'manifestPath', 'evidenceCutoff'] as const)(
    'does not reuse bytes after %s changes', async field => {
      const { run, fetcher } = await sectionFixture();
      await loadRunSection(run, 'performance');
      run[field] = field === 'manifestPath' ? 'fixture/updated-manifest.json' : field === 'evidenceCutoff' ? '2026-08-01' : 'b'.repeat(64);
      await loadRunSection(run, 'performance');
      expect(fetcher).toHaveBeenCalledTimes(2);
    },
  );

  it('requires new section bytes and still rejects an unavailable or unsafe declaration', async () => {
    const { run, fetcher, assets } = await sectionFixture();
    await loadRunSection(run, 'performance');
    const section = run.manifest!.sections.find(candidate => candidate.section_id === 'performance')!;
    const updated = canonicalJson({ report: [{ date: '2026-07-31', account: 110 }] });
    section.sha256 = await sha256Text(updated);
    section.byte_size = new TextEncoder().encode(updated).byteLength;
    assets.set('/data/formal-model-runs/fixture/performance.json', updated);
    expect(await loadRunSection(run, 'performance')).toEqual(JSON.parse(updated));
    section.availability_status = 'blocked_by_source';
    section.reason = 'source unavailable';
    await expect(loadRunSection(run, 'performance')).rejects.toThrow('source unavailable');
    section.availability_status = 'available';
    section.path = '../performance.json';
    await expect(loadRunSection(run, 'performance')).rejects.toThrow('Unsafe');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('does not let an older failed read evict a newer verified identity', async () => {
    const { run, fetcher } = await sectionFixture();
    let rejectOlder!: (error: Error) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>((_, reject) => { rejectOlder = reject; }));
    const older = expect(loadRunSection(run, 'performance')).rejects.toThrow('older request failed');
    run.manifestSha256 = 'b'.repeat(64);
    await loadRunSection(run, 'performance');
    rejectOlder(new Error('older request failed'));
    await older;
    await loadRunSection(run, 'performance');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
