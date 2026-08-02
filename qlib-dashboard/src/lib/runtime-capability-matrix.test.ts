import { describe, expect, it } from 'vitest';
import { RUNTIME_CAPABILITY_MATRIX, hasCapability } from './runtime-capability-matrix';

describe('runtime capability matrix', () => {
  it('contains only published and local artifact modes', () => {
    expect(Object.keys(RUNTIME_CAPABILITY_MATRIX).sort()).toEqual([
      'local_artifact',
      'static_artifact',
    ]);
  });

  it('keeps every browser mode strictly read only', () => {
    for (const mode of Object.keys(RUNTIME_CAPABILITY_MATRIX) as Array<keyof typeof RUNTIME_CAPABILITY_MATRIX>) {
      expect(hasCapability(mode, 'authentication')).toBe(false);
      expect(hasCapability(mode, 'apiReads')).toBe(false);
      expect(hasCapability(mode, 'jobs')).toBe(false);
      expect(hasCapability(mode, 'dataRefresh')).toBe(false);
      expect(hasCapability(mode, 'modelMutation')).toBe(false);
      expect(hasCapability(mode, 'systemOperations')).toBe(false);
      expect(hasCapability(mode, 'offlineShell')).toBe(true);
    }
  });

  it('keeps local inputs available in every browser mode', () => {
    for (const mode of Object.keys(RUNTIME_CAPABILITY_MATRIX) as Array<keyof typeof RUNTIME_CAPABILITY_MATRIX>) {
      expect(hasCapability(mode, 'publishedBundle')).toBe(true);
      expect(hasCapability(mode, 'localDirectory')).toBe(true);
      expect(hasCapability(mode, 'zipBundle')).toBe(true);
      expect(hasCapability(mode, 'recentBundleMetadata')).toBe(true);
      expect(hasCapability(mode, 'directoryHandlePersistence')).toBe(true);
    }
  });
});
