/**
 * API utility with 401 handling and auth header injection.
 * Wraps fetch to detect authentication failures and redirect to login.
 *
 * For new code, prefer the typed `apiClient` from './api-client' which
 * returns parsed, typed payloads and throws `ApiError` on failure.
 * The raw `apiFetch` below is kept for backward compatibility and for
 * callers that need the raw Response object (e.g. SSE streaming).
 */

// Re-export typed API layer so callers can migrate incrementally:
//   import { apiClient }          from '@/lib/api-client'; // new
//   import { ApiError }           from '@/lib/api';        // new (types only)
//   import { apiFetch }           from '@/lib/api';        // legacy
//
// Note: apiClient is NOT re-exported here to avoid a circular dependency
// (api-client imports apiFetch from this file). Import it directly:
//   import { apiClient } from '@/lib/api-client';
export { ApiError } from './api-types';
export type {
  Ok,
  OkWithData,
  HealthResponse,
  DataStatusResponse,
  ModelVersion,
  ModelListResponse,
  ModelDetailResponse,
  ModelHealthCheck,
  ModelPromoteResponse,
  BacktestRun,
  BacktestListResponse,
  BacktestCurveResponse,
  BacktestCompareResponse,
  BacktestAttributionResponse,
  BacktestLedgerResponse,
  AlphaDecompositionResponse,
  Job,
  JobListResponse,
  JobDetailResponse,
  JobSubmitResponse,
  Report,
  ReportListResponse,
  ReportDetailResponse,
  Arena,
  ArenaListResponse,
  LeaderboardRow,
  ArenaLeaderboardResponse,
  FactorRecord,
  FactorRegistryStats,
  FactorICReport,
  FactorTopResponse,
  FactorDecayPoint,
  FactorDecayResponse,
  FactorRegistryListResponse,
  FactorRegistryDetailResponse,
  FactorScanReport,
  FactorAttributionSummary,
  FactorAttributionEntry,
  FactorAttributionResponse,
  RollingAttributionResponse,
  FactorExistsResponse,
  DecayReport,
  DecayFactorReport,
  PortfolioCheckResponse,
  PortfolioConfigResponse,
  StockDecision,
  StockDecisionResponse,
  StockFactor,
  StockFactorsResponse,
  WatchlistSignalItem,
  WatchlistSummaryResponse,
  SignalHistoryEntry,
  SignalHistoryResponse,
  SignalGrade,
  SignalGradeResponse,
  SignalMarker,
  SignalMarkersResponse,
  DailySignalPoint,
  DailySignalSeriesResponse,
  GradePerformance,
  StockRankingEntry,
  StockRankingResponse,
  DataFreshnessResponse,
  DataFreshness,
  PortfolioAnalysisResponse,
  StrategyCompileResponse,
  StrategyListResponse,
  StrategyContentResponse,
  StrategyPlugin,
  StrategyPluginsResponse,
  NLCompileResponse,
  WorkflowSubmitResponse,
  WorkflowStatusEntry,
  ResearchRunSubmitResponse,
  ResearchRunSummary,
  ResearchRunsListResponse,
  ResearchRunDetailResponse,
  ResearchStepsResponse,
  WalkForwardSubmitResponse,
  WalkForwardResultResponse,
  AgentChatResponse,
  EvidenceBundleResponse,
  WatchlistResponse,
  NameMapResponse,
  InstrumentsResponse,
  AddSymbolsResponse,
  RemoveSymbolsResponse,
  SystemPathsResponse,
  SystemDocResponse,
  ThoughtStreamResponse,
  PanicResponse,
  FeaturesResponse,
  CompletenessResponse,
  SnapshotResponse,
  QualityResponse,
  IntegrityResponse,
  StockDataResponse,
  ToolCapabilitiesResponse,
  ToolChatResponse,
} from './api-types';

let onUnauthorized: (() => void) | null = null;
let getAuthHeader: (() => string | null) | null = null;

/** Register a callback for 401 responses (e.g. show login modal). */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

/** Register a function that returns the current auth header. */
export function setAuthHeaderProvider(provider: (() => string | null) | null) {
  getAuthHeader = provider;
}

/**
 * Fetch wrapper that handles 401 responses and injects auth headers.
 * Usage: const data = await apiFetch('/api/data').then(r => r.json())
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);

  // Inject auth header if available
  if (!headers.has('Authorization') && getAuthHeader) {
    const auth = getAuthHeader();
    if (auth) {
      headers.set('Authorization', auth);
    }
  }

  const resp = await fetch(input, { ...init, headers });
  if (resp.status === 401) {
    if (onUnauthorized) {
      onUnauthorized();
    } else {
      // Handler not yet registered (e.g. during StrictMode cleanup) —
      // log only; do NOT reload as that causes infinite refresh loops.
      console.warn('[api] 401 Unauthorized — no handler registered');
    }
  }
  return resp;
}
