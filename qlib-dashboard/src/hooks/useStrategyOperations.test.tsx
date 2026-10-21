import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStrategyOperations } from './useStrategyOperations';
import { useAccessControl } from './useAccessControl';
import { useAlphaMembership } from './useAlphaMembership';
import { loadRuntimeStrategyOperation, loadStrategyOperations, parseStrategyOperationsSnapshot } from '@/lib/strategy-operations';
import type { GovernedRunSummary } from '@/lib/governed-run';

vi.mock('./useAccessControl', () => ({ useAccessControl: vi.fn() }));
vi.mock('./useAlphaMembership', () => ({ useAlphaMembership: vi.fn() }));
vi.mock('@/lib/strategy-operations', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/strategy-operations')>(),
  loadStrategyOperations: vi.fn(), loadRuntimeStrategyOperation: vi.fn(),
}));

const run = { key: 'cn-run', channel: 'formal', modelVersionId: 'cn_x1_2', title: 'CN x1.2', modelFamilyId: 'cn_ranker',
  bundleId: 'a'.repeat(64), runId: 'formal-run', evidenceCutoff: '2026-10-14' } as GovernedRunSummary;
const runs = [run];
const shell = parseStrategyOperationsSnapshot({ model_version_id: run.modelVersionId, strategy_id: 'cn_x',
  status: 'blocked', data_freshness: 'unknown', factor_freshness: 'blocked', decision_cadence: 'Every 10 sessions',
  next_decision_policy: 'Next eligible open', state_label: 'Runtime current operations', decision_reason: 'Protected current operations',
  delivery_status: 'not available', source_label: 'Runtime current operations', note: 'Protected', allocations: [], factor_evidence: [],
  source_identity: { formal_bundle_id: run.bundleId, formal_run_id: run.runId, formal_evidence_cutoff: run.evidenceCutoff } });
const live = { ...shell, status: 'current_no_change' as const, dataFreshness: 'current' as const,
  factorFreshness: 'unknown' as const, stateLabel: 'Verified state',
  sourceIdentity: { ...shell.sourceIdentity, ledgerFingerprint: 'verified-ledger' }, allocations: [{ asset: 'PRIVATE', current: 1, target: 1, delta: 0 }] };

describe('current operations recovery', () => {
  const getClient = vi.fn();
  const requiredTier = vi.fn<ReturnType<typeof useAccessControl>['requiredTier']>(() => 'pro');
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAlphaMembership).mockReturnValue({ loading: false, signedIn: true, isPro: true, isOwner: false,
      userId: 'user-a', entitlements: [], getClient, openAccount: vi.fn() });
    vi.mocked(useAccessControl).mockReturnValue({ policyLoading: false, tier: 'pro', requiredTier,
      canAccess: () => true } as unknown as ReturnType<typeof useAccessControl>);
    vi.mocked(loadStrategyOperations).mockImplementation(async (selected) => new Map(selected.map((item) => [item.modelVersionId, shell])));
    vi.mocked(loadRuntimeStrategyOperation).mockResolvedValue(live);
    getClient.mockResolvedValue({});
  });
  afterEach(() => vi.useRealTimers());

  it('settles client failure and recovers with a read-only retry', async () => {
    getClient.mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(shell);
    expect(result.current.issues).toHaveLength(1);
    act(() => result.current.reload());
    expect(result.current.snapshots.size).toBe(0);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live);
    expect(result.current.issues).toEqual([]);
  });

  it('shows the public identity before the runtime request completes', async () => {
    vi.mocked(loadRuntimeStrategyOperation).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)).toEqual(shell));
    expect(result.current.loading).toBe(true);
  });

  it.each(['publication', 'client', 'runtime', 'account', 'policy'])('recovers controls from a stalled %s read and ignores its late result', async (stage) => {
    vi.useFakeTimers();
    let release = () => {};
    if (stage === 'publication') vi.mocked(loadStrategyOperations).mockReturnValueOnce(new Promise((resolve) => {
      release = () => resolve(new Map([[run.modelVersionId, shell]]));
    }));
    if (stage === 'client') getClient.mockReturnValueOnce(new Promise((resolve) => { release = () => resolve({}); }));
    if (stage === 'runtime') vi.mocked(loadRuntimeStrategyOperation).mockReturnValueOnce(new Promise((resolve) => { release = () => resolve(live); }));
    if (stage === 'account') vi.mocked(useAlphaMembership).mockReturnValue({ ...useAlphaMembership(), loading: true });
    if (stage === 'policy') vi.mocked(useAccessControl).mockReturnValue({ ...useAccessControl(), policyLoading: true });
    const { result, unmount } = renderHook(() => useStrategyOperations(runs));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(result.current.loading).toBe(false);
    expect(result.current.issues[result.current.issues.length - 1].message).toContain('timed out');
    expect(result.current.snapshots.get(run.modelVersionId)?.allocations ?? []).toEqual([]);
    const signal = vi.mocked(loadStrategyOperations).mock.calls[0]?.[1];
    if (signal) expect(signal.aborted).toBe(true);
    await act(async () => release());
    expect(result.current.snapshots.get(run.modelVersionId)?.allocations ?? []).toEqual([]);
    if (stage === 'client' || stage === 'publication') expect(loadRuntimeStrategyOperation).not.toHaveBeenCalled();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('retains verified independent records on timeout and succeeds on retry', async () => {
    vi.useFakeTimers();
    const otherRun = { ...run, key: 'us-run', modelVersionId: 'us_x1_3', title: 'US x1.3' };
    const otherShell = { ...shell, modelVersionId: otherRun.modelVersionId, strategyId: 'us_x', readState: 'protected' as const };
    const selected = [run, otherRun];
    vi.mocked(loadStrategyOperations).mockResolvedValue(new Map([[run.modelVersionId, shell], [otherRun.modelVersionId, otherShell]]));
    vi.mocked(loadRuntimeStrategyOperation).mockImplementation(async (_client, strategy) => strategy === 'us_x' ? new Promise(() => {}) : live);
    const { result } = renderHook(() => useStrategyOperations(selected));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(result.current.loading).toBe(false);
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live);
    expect(result.current.issues).toEqual([{ modelVersionId: otherRun.modelVersionId, message: expect.stringContaining('timed out') }]);
    vi.mocked(loadRuntimeStrategyOperation).mockImplementation(async (_client, strategy) => strategy === 'us_x' ? null : live);
    await act(async () => result.current.reload());
    expect(result.current.loading).toBe(false);
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live);
    expect(result.current.issues.map(issue => issue.message).join(' ')).not.toContain('timed out');
  });

  it.each(['missing', 'mismatched', 'rejected'])('keeps protected operations hidden for a %s response', async (failure) => {
    if (failure === 'missing') vi.mocked(loadRuntimeStrategyOperation).mockResolvedValue(null);
    if (failure === 'mismatched') vi.mocked(loadRuntimeStrategyOperation).mockResolvedValue({ ...live,
      sourceIdentity: { ...live.sourceIdentity, formalBundleId: 'b'.repeat(64) } });
    if (failure === 'rejected') vi.mocked(loadRuntimeStrategyOperation).mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)?.allocations).toEqual([]);
    expect(result.current.issues).toEqual([{ modelVersionId: run.modelVersionId, message: 'CN x1.2: current operations could not be verified.' }]);
  });

  it('does not request a protected strategy for an ineligible account', async () => {
    vi.mocked(useAccessControl).mockReturnValue({ policyLoading: false, tier: 'authenticated', requiredTier,
      canAccess: () => false } as unknown as ReturnType<typeof useAccessControl>);
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getClient).not.toHaveBeenCalled();
    expect(loadRuntimeStrategyOperation).not.toHaveBeenCalled();
    expect(result.current.issues).toEqual([]);
  });

  it('labels a failed eligible protected read as unavailable, not a strategy failure', async () => {
    vi.mocked(loadStrategyOperations).mockResolvedValue(new Map([[run.modelVersionId, { ...shell, readState: 'protected' }]]));
    vi.mocked(loadRuntimeStrategyOperation).mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)?.readState).toBe('unavailable');
    expect(result.current.snapshots.get(run.modelVersionId)?.allocations).toEqual([]);
  });

  it('discards a late response when the formal run changes', async () => {
    let resolveOld!: (value: typeof live) => void;
    vi.mocked(loadRuntimeStrategyOperation).mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }));
    const { result, rerender } = renderHook(({ selected }) => useStrategyOperations(selected), { initialProps: { selected: runs } });
    await waitFor(() => expect(loadRuntimeStrategyOperation).toHaveBeenCalledTimes(1));
    const nextRun = { ...run, key: 'cn-new-run', runId: 'formal-new-run', bundleId: 'b'.repeat(64), evidenceCutoff: '2026-10-15' };
    const nextShell = { ...shell, sourceIdentity: { ...shell.sourceIdentity, formalBundleId: nextRun.bundleId,
      formalRunId: nextRun.runId, formalEvidenceCutoff: nextRun.evidenceCutoff } };
    const nextLive = { ...live, stateLabel: 'New verified state', sourceIdentity: nextShell.sourceIdentity };
    vi.mocked(loadStrategyOperations).mockResolvedValue(new Map([[run.modelVersionId, nextShell]]));
    vi.mocked(loadRuntimeStrategyOperation).mockResolvedValue(nextLive);
    rerender({ selected: [nextRun] });
    expect(result.current.snapshots.size).toBe(0);
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => resolveOld(live));
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(nextLive);
  });

  it('keeps an independent strategy readable when another runtime record fails', async () => {
    const otherRun = { ...run, key: 'us-run', modelVersionId: 'us_x1_3', title: 'US x1.3' };
    const otherShell = { ...shell, modelVersionId: otherRun.modelVersionId, strategyId: 'us_x', readState: 'protected' as const };
    vi.mocked(loadStrategyOperations).mockResolvedValue(new Map([[run.modelVersionId, shell], [otherRun.modelVersionId, otherShell]]));
    vi.mocked(loadRuntimeStrategyOperation).mockImplementation(async (_client, strategy) => strategy === 'us_x' ? null : live);
    const selected = [run, otherRun];
    const { result } = renderHook(() => useStrategyOperations(selected));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live);
    expect(result.current.snapshots.get(otherRun.modelVersionId)?.allocations).toEqual([]);
    expect(result.current.issues).toEqual([{ modelVersionId: otherRun.modelVersionId, message: 'US x1.3: current operations could not be verified.' }]);
  });

  it('clears private snapshots when the account changes without reusing the old response', async () => {
    const { result, rerender } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live));
    vi.mocked(useAlphaMembership).mockReturnValue({ ...useAlphaMembership(), userId: 'user-b' });
    vi.mocked(loadRuntimeStrategyOperation).mockReturnValue(new Promise(() => {}));
    rerender();
    expect(result.current.snapshots.size).toBe(0);
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)?.allocations).toEqual([]));
  });

  it('waits for a formal identity before reading operations', async () => {
    const { result, rerender } = renderHook(({ selected }: { selected: GovernedRunSummary[] }) => useStrategyOperations(selected), {
      initialProps: { selected: [] as GovernedRunSummary[] },
    });
    await act(async () => {});
    expect(loadStrategyOperations).not.toHaveBeenCalled();
    rerender({ selected: runs });
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live));
  });


  it('retains dated verified observations when a same-identity publication refresh stalls', async () => {
    const { result, unmount } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live));
    vi.useFakeTimers();
    let release!: () => void;
    vi.mocked(loadStrategyOperations).mockReturnValueOnce(new Promise(resolve => {
      release = () => resolve(new Map([[run.modelVersionId, shell]]));
    }));
    act(() => result.current.reload());
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual({ ...live, readState: 'retained' });
    expect(result.current.previousRead).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(result.current.loading).toBe(false);
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual({ ...live, readState: 'retained' });
    await act(async () => release());
    expect(result.current.snapshots.get(run.modelVersionId)?.readState).toBe('retained');
    await act(async () => result.current.reload());
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live);
    expect(result.current.previousRead).toBe(false);
    unmount();
  });

  it.each(['missing', 'mismatched', 'protected'])('discards prior private values for a %s runtime response', async failure => {
    const protectedShell = { ...shell, readState: 'protected' as const };
    vi.mocked(loadStrategyOperations).mockResolvedValue(new Map([[run.modelVersionId, protectedShell]]));
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live));
    vi.mocked(loadRuntimeStrategyOperation).mockResolvedValue(failure === 'missing' ? null
      : failure === 'protected' ? protectedShell : { ...live, sourceIdentity: { ...live.sourceIdentity, formalBundleId: 'b'.repeat(64) } });
    await act(async () => result.current.reload());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)?.allocations).toEqual([]);
    expect(result.current.snapshots.get(run.modelVersionId)?.readState).toBe('unavailable');
    expect(result.current.previousRead).toBe(false);
  });

  it('does not retain private observations across a changed stable strategy identity', async () => {
    vi.mocked(useAccessControl).mockReturnValue({ ...useAccessControl(),
      canAccess: tier => tier === 'pro' });
    requiredTier.mockImplementation((_resource, id) => id === 'other_strategy' ? 'owner' : 'pro');
    const { result } = renderHook(() => useStrategyOperations(runs));
    await waitFor(() => expect(result.current.snapshots.get(run.modelVersionId)).toEqual(live));
    const replacement = { ...shell, strategyId: 'other_strategy', readState: 'protected' as const };
    vi.mocked(loadStrategyOperations).mockResolvedValue(new Map([[run.modelVersionId, replacement]]));
    await act(async () => result.current.reload());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.snapshots.get(run.modelVersionId)).toEqual(replacement);
    expect(result.current.previousRead).toBe(false);
    expect(loadRuntimeStrategyOperation).toHaveBeenCalledTimes(1);
  });

});
