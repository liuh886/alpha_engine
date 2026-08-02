import type { RuntimeMode } from './runtime-capabilities';

export type ProductCapability =
  | 'authentication'
  | 'publishedBundle'
  | 'localDirectory'
  | 'zipBundle'
  | 'apiReads'
  | 'jobs'
  | 'dataRefresh'
  | 'modelMutation'
  | 'systemOperations'
  | 'offlineShell'
  | 'recentBundleMetadata'
  | 'directoryHandlePersistence';

const READ_ONLY_ARTIFACT_CAPABILITIES: Record<ProductCapability, boolean> = {
  authentication: false,
  publishedBundle: true,
  localDirectory: true,
  zipBundle: true,
  apiReads: false,
  jobs: false,
  dataRefresh: false,
  modelMutation: false,
  systemOperations: false,
  offlineShell: true,
  recentBundleMetadata: true,
  directoryHandlePersistence: true,
};

export const RUNTIME_CAPABILITY_MATRIX: Record<RuntimeMode, Record<ProductCapability, boolean>> = {
  static_artifact: { ...READ_ONLY_ARTIFACT_CAPABILITIES },
  local_artifact: { ...READ_ONLY_ARTIFACT_CAPABILITIES },
};

export function hasCapability(mode: RuntimeMode, capability: ProductCapability): boolean {
  return RUNTIME_CAPABILITY_MATRIX[mode][capability];
}
