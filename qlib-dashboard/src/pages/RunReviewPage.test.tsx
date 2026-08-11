import { describe, expect, it } from 'vitest';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { usesStructuredBundleReview } from './RunReviewPage';

function run(channel: GovernedRunSummary['channel'], evidenceStatus: GovernedRunSummary['evidenceStatus']) {
  return { channel, evidenceStatus } as GovernedRunSummary;
}

describe('usesStructuredBundleReview', () => {
  it('uses the structured holdings and trade review for complete preview bundles', () => {
    expect(usesStructuredBundleReview(run('preview', 'complete'))).toBe(true);
  });

  it('keeps partial preview and local evidence in the capability review', () => {
    expect(usesStructuredBundleReview(run('preview', 'partial'))).toBe(false);
    expect(usesStructuredBundleReview(run('local', 'complete'))).toBe(false);
  });

  it('continues to use the structured review for formal bundles', () => {
    expect(usesStructuredBundleReview(run('formal', 'complete'))).toBe(true);
  });
});
