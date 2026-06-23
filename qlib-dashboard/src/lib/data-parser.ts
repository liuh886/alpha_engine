import { normalizeModelRegistryEntry } from "./model-normalizer";
import type { ModelVersion } from "./api-types";

// Maintain backward compatible type alias for hooks expecting ModelData
export type ModelData = ModelVersion;
export type BacktestData = ModelVersion["backtest"];

export function parseQlibData(json: any): ModelData[] {
  if (!json || !json.models) return [];
  return json.models.map(normalizeModelRegistryEntry);
}
