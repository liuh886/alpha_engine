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

export const RUNTIME_CAPABILITY_MATRIX: Record<RuntimeMode, Record<ProductCapability, boolean>> = {
  static_artifact: {
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
  },
  local_artifact: {
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
  },
  connected_research: {
    authentication: true,
    publishedBundle: true,
    localDirectory: true,
    zipBundle: true,
    apiReads: true,
    jobs: true,
    dataRefresh: true,
    modelMutation: true,
    systemOperations: true,
    offlineShell: false,
    recentBundleMetadata: true,
    directoryHandlePersistence: true,
  },
};

export function hasCapability(mode: RuntimeMode, capability: ProductCapability): boolean {
  return RUNTIME_CAPABILITY_MATRIX[mode][capability];
}
