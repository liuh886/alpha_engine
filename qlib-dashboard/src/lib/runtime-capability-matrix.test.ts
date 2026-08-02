import { describe, expect, it } from 'vitest';
import { RUNTIME_CAPABILITY_MATRIX, hasCapability } from './runtime-capability-matrix';

describe('runtime capability matrix', () => {
  it('keeps static and local modes strictly read only', () => {
    for (const mode of ['static_artifact', 'local_artifact'] as const) {
      expect(hasCapability(mode, 'authentication')).toBe(false);
      expect(hasCapability(mode, 'apiReads')).toBe(false);
      expect(hasCapability(mode, 'jobs')).toBe(false);
      expect(hasCapability(mode, 'dataRefresh')).toBe(false);
      expect(hasCapability(mode, 'modelMutation')).toBe(false);
      expect(hasCapability(mode, 'systemOperations')).toBe(false);
      expect(hasCapability(mode, 'offlineShell')).toBe(true);
    }
  });

  it('keeps local inputs available in every product mode', () => {
    for (const mode of Object.keys(RUNTIME_CAPABILITY_MATRIX) as Array<keyof typeof RUNTIME_CAPABILITY_MATRIX>) {
      expect(hasCapability(mode, 'localDirectory')).toBe(true);
      expect(hasCapability(mode, 'zipBundle')).toBe(true);
      expect(hasCapability(mode, 'recentBundleMetadata')).toBe(true);
    }
  });

  it('scopes operational capabilities to connected research', () => {
    expect(hasCapability('connected_research', 'authentication')).toBe(true);
    expect(hasCapability('connected_research', 'apiReads')).toBe(true);
    expect(hasCapability('connected_research', 'jobs')).toBe(true);
    expect(hasCapability('connected_research', 'dataRefresh')).toBe(true);
    expect(hasCapability('connected_research', 'modelMutation')).toBe(true);
    expect(hasCapability('connected_research', 'systemOperations')).toBe(true);
  });
});
