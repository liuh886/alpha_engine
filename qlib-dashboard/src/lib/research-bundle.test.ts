import { describe, expect, it } from 'vitest';
import {
  FileSetBundleSource,
  openResearchBundle,
  validateBundleManifest,
  type ResearchBundleManifest,
} from './research-bundle';

async function digest(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const value = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function testFile(text: string, name: string, relativePath: string): File {
  const file = new File([text], name);
  Object.defineProperties(file, {
    webkitRelativePath: { value: relativePath },
    text: { value: async () => text },
    arrayBuffer: {
      value: async () => {
        const bytes = new TextEncoder().encode(text);
        const copy = new Uint8Array(bytes.byteLength);
        copy.set(bytes);
        return copy.buffer;
      },
    },
  });
  return file;
}

async function files(tamperModels = false): Promise<File[]> {
  const models = '[{"id":"run-1","market":"us"}]';
  const exportManifest = '{"snapshot_id":"snapshot-1"}';
  const manifest: ResearchBundleManifest = {
    schema_version: '1.0.0',
    frontend_reader_range: '>=1.0.0 <2.0.0',
    bundle_id: 'a'.repeat(64),
    title: 'Fixture bundle',
    generated_at: '2026-08-02T00:00:00Z',
    evidence_cutoff: '2026-07-31',
    research_only: true,
    trade_ready: false,
    scope: { markets: ['us'], snapshot_id: 'snapshot-1', model_count: 1 },
    warnings: [],
    blocked_gates: [],
    promotion_decision: 'research_candidate',
    artifacts: [
      {
        artifact_id: '1'.repeat(16),
        kind: 'model_index',
        path: 'data/models.json',
        media_type: 'application/json',
        byte_size: new Blob([models]).size,
        sha256: await digest(models),
        required: true,
      },
      {
        artifact_id: '2'.repeat(16),
        kind: 'static_export_manifest',
        path: 'data/manifest.json',
        media_type: 'application/json',
        byte_size: new Blob([exportManifest]).size,
        sha256: await digest(exportManifest),
        required: true,
      },
    ],
  };

  return [
    testFile(JSON.stringify(manifest), 'alpha-engine-bundle.json', 'bundle/alpha-engine-bundle.json'),
    testFile(tamperModels ? '[]' : models, 'models.json', 'bundle/data/models.json'),
    testFile(exportManifest, 'manifest.json', 'bundle/data/manifest.json'),
  ];
}

describe('research bundle reader', () => {
  it('opens a selected file set and verifies required indexes', async () => {
    const bundle = await openResearchBundle(new FileSetBundleSource(await files()));
    expect(bundle.manifest.title).toBe('Fixture bundle');
    expect(bundle.dashboard.snapshot_id).toBe('snapshot-1');
    expect(bundle.dashboard.models).toHaveLength(1);
    expect(bundle.integrity).toBe('required_verified');
  });

  it('rejects a digest mismatch', async () => {
    await expect(openResearchBundle(new FileSetBundleSource(await files(true)))).rejects.toThrow('size mismatch');
  });

  it('rejects unsupported major versions and traversal paths', () => {
    expect(() => validateBundleManifest({ schema_version: '2.0.0', research_only: true, trade_ready: false, artifacts: [] })).toThrow('Unsupported');
    expect(() => validateBundleManifest({
      schema_version: '1.0.0', research_only: true, trade_ready: false,
      artifacts: [{ path: '../secret', sha256: 'a'.repeat(64) }],
    })).toThrow('Unsafe bundle path');
  });
});
