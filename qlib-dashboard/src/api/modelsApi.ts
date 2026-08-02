import {
  getActiveResearchBundle,
  loadStaticResearchBundle,
  setActiveResearchBundle,
} from '@/lib/research-bundle';

async function getArtifactDashboardDb(): Promise<any> {
  let bundle = getActiveResearchBundle();
  if (!bundle) {
    bundle = await loadStaticResearchBundle();
    setActiveResearchBundle(bundle);
  }
  return bundle.dashboard;
}

/**
 * Artifact-only model reader retained under the existing module name while the
 * remaining legacy API directory is retired. It performs no HTTP requests and
 * exposes no mutation methods.
 */
export const modelsApi = {
  getDashboardDb: getArtifactDashboardDb,
};
