import { apiClient } from "./api-client";
import type {
  AddSymbolsResponse,
  ArenaLeaderboardResponse,
  ArenaListResponse,
  CompletenessResponse,
  DashboardArtifactResponse,
  DataStatusResponse,
  EvidenceBundleResponse,
  JobDetailResponse,
  JobSubmitResponse,
  ModelDeleteResponse,
  ModelListResponse,
  ModelPromoteResponse,
  NLCompileResponse,
  RemoveSymbolsResponse,
  StockRankingResponse,
  WatchlistResponse,
  WorkflowStatusEntry,
  WorkflowSubmitResponse,
} from "./api-types";

interface TrainingInput {
  market: string;
  model_type: string;
  tag: string;
  snapshot_id: string;
}

interface SymbolsInput {
  symbols: string[];
  market: string;
}

export const releaseApi = {
  getDataStatus(signal?: AbortSignal) {
    return apiClient.get<DataStatusResponse>("/api/data/status", { signal, init: { cache: "no-store" } });
  },
  getWatchlist(signal?: AbortSignal) {
    return apiClient.get<WatchlistResponse>("/api/data/watchlist", { signal, init: { cache: "no-store" } });
  },
  addSymbols(input: SymbolsInput) {
    return apiClient.post<AddSymbolsResponse>("/api/data/instruments/add", input);
  },
  removeSymbols(input: SymbolsInput) {
    return apiClient.post<RemoveSymbolsResponse>("/api/data/instruments/remove", input);
  },
  submitDataUpdate(full: boolean, market: "us" | "cn" | "hk") {
    return apiClient.post<JobSubmitResponse>("/api/data/update", {
      full,
      market,
      lookback_days: full ? 3650 : 30,
    });
  },
  getJob(jobId: string) {
    return apiClient.get<JobDetailResponse>(`/api/jobs/${encodeURIComponent(jobId)}`, {
      init: { cache: "no-store" },
    });
  },
  getCompleteness(market: string, feature: string) {
    return apiClient.get<CompletenessResponse>("/api/data/completeness", {
      params: { market, feature },
      init: { cache: "no-store" },
    });
  },
  submitTraining(input: TrainingInput) {
    const { snapshot_id, ...workflow } = input;
    return apiClient.post<WorkflowSubmitResponse>("/api/workflow/train", {
      ...workflow,
      details: { snapshot_id },
    });
  },
  getWorkflow(workflowId: string) {
    return apiClient.get<WorkflowStatusEntry[]>("/api/workflow/status", {
      params: { workflow_id: workflowId, limit: 1 },
    });
  },
  getDashboardArtifact(signal?: AbortSignal) {
    return apiClient.get<DashboardArtifactResponse>("/api/artifacts/dashboard-db", {
      signal,
      init: { cache: "no-store" },
    });
  },
  listModels(market?: string, signal?: AbortSignal) {
    return apiClient.get<ModelListResponse>("/api/models", {
      signal,
      params: { market: market && market !== "all" ? market : undefined },
    });
  },
  promoteModel(versionId: string, stage: string) {
    return apiClient.post<ModelPromoteResponse>("/api/models/promote", {
      artifact_id: versionId,
      stage,
    });
  },
  deleteModel(versionId: string) {
    return apiClient.post<ModelDeleteResponse>("/api/models/delete", { artifact_id: versionId });
  },
  getModelEvidence(modelId: string) {
    return apiClient.get<EvidenceBundleResponse>(`/api/evidence/model/${encodeURIComponent(modelId)}`);
  },
  listArenas(signal?: AbortSignal) {
    return apiClient.get<ArenaListResponse>("/api/arena/list", { signal });
  },
  getLeaderboard(arenaId: string, signal?: AbortSignal) {
    return apiClient.get<ArenaLeaderboardResponse>("/api/arena/leaderboard", {
      signal,
      params: { arena_id: arenaId },
    });
  },
  getStockRanking(params: {
    market: string;
    sort_by: string;
    sort_grade: string;
    run_id?: string;
  }) {
    return apiClient.get<StockRankingResponse>("/api/stock-analysis/ranking", {
      params: { ...params, step_size: 10, forward_days: 10, limit: 50 },
      init: { cache: "no-store" },
    });
  },
  compileStrategy(text: string, market: string) {
    return apiClient.post<NLCompileResponse>("/api/strategy/compile", { text, market });
  },
};
