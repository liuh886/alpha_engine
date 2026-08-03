import { describe, expect, it } from 'vitest';
import manifestFixture from '../../../tests/fixtures/model_run_bundle_v2/manifest.json';
import summaryFixture from '../../../tests/fixtures/model_run_bundle_v2/summary.json';
import {
  canonicalJson,
  parseCanonicalMetricV2,
  parseModelRunBundleV2Manifest,
  sha256Text,
  verifyModelRunBundleId,
} from './model-run-bundle-v2';

describe('Model Run Bundle v2', () => {
  it('parses the Python fixture and verifies cross-language identities', async () => {
    const manifest = parseModelRunBundleV2Manifest(manifestFixture);
    const summaryText = canonicalJson(summaryFixture);
    expect(manifest.publication_channel).toBe('preview');
    expect(manifest.publication_status).toBe('ci_validated_preview');
    expect(manifest.research_only).toBe(true);
    expect(manifest.trade_ready).toBe(false);
    expect(await verifyModelRunBundleId(manifest)).toBe(true);
    expect(await sha256Text(summaryText)).toBe(manifest.sections[0].sha256);
    expect(new TextEncoder().encode(summaryText).byteLength).toBe(manifest.sections[0].byte_size);
  });

  it('parses available and unavailable canonical metrics distinctly', () => {
    const available = parseCanonicalMetricV2(summaryFixture.metrics[0]);
    const unavailable = parseCanonicalMetricV2(summaryFixture.metrics[1]);
    expect(available.value).toBe(0.18);
    expect(available.unavailable_reason).toBeNull();
    expect(unavailable.value).toBeNull();
    expect(unavailable.availability_status).toBe('not_retained');
    expect(unavailable.unavailable_reason).toContain('did not retain');
  });

  it('fails closed on weakened boundaries and fabricated files', () => {
    expect(() => parseModelRunBundleV2Manifest({ ...manifestFixture, trade_ready: true })).toThrow('research boundary');
    const sections = structuredClone(manifestFixture.sections) as Array<Record<string, unknown>>;
    sections[1] = {
      ...sections[1],
      path: 'performance.json',
      sha256: '0'.repeat(64),
      byte_size: 2,
      media_type: 'application/json',
    };
    expect(() => parseModelRunBundleV2Manifest({ ...manifestFixture, sections })).toThrow('cannot declare a file');
  });

  it('uses deterministic key ordering for canonical JSON', () => {
    expect(canonicalJson({ b: 2, a: { d: 4, c: 3 } })).toBe('{"a":{"c":3,"d":4},"b":2}\n');
  });
});
