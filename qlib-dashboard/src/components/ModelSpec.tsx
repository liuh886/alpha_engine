import { Badge } from "@/components/ui/badge";
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ModelParams } from "@/lib/types";

export function ModelSpec({ params }: { params: ModelParams }) {
  const [isOpen, setIsOpen] = useState(false);
  const meta = (params?.meta || {}) as Record<string, unknown>;
  const strategyProfile = (meta.strategy_profile || {}) as Record<string, unknown>;
  const spStrategy = (strategyProfile.strategy || {}) as Record<string, unknown>;
  const workflowSnapshot = (meta.workflow_snapshot || {}) as Record<string, unknown>;
  const wsPortConfig = (workflowSnapshot.port_analysis_config || {}) as Record<string, unknown>;
  const wsStrategy = (wsPortConfig.strategy || {}) as Record<string, unknown>;
  const wsBacktest = (wsPortConfig.backtest || {}) as Record<string, unknown>;
  const label = meta.label as string | string[] | undefined;
  const features = (meta.features || []) as string[];
  const dataRange = (meta.data_range || {}) as Record<string, string>;
  const segments = (meta.segments || {}) as Record<string, string[]>;
  const modelClass = (meta.model_class || params.model_class || params["model.class"]) as string | undefined;
  const modelKwargs = (meta.model_kwargs || {}) as Record<string, unknown>;
  const modelProfile = (strategyProfile.model || {}) as Record<string, unknown>;
  const featurePack = (modelProfile.feature_pack || meta.feature_pack) as string | undefined;
  const extraFeatures = (modelProfile.extra_features || meta.extra_features || []) as string[];

  const featurePreview = Array.isArray(features) ? features.slice(0, 10) : [];
  const featureRemainder =
    Array.isArray(features) && features.length > 10 ? features.length - 10 : 0;

  const paramGuide: Record<string, string> = {
    learning_rate: "Step size for boosting updates.",
    num_leaves: "Number of leaves per tree.",
    max_depth: "Max depth per tree.",
    lambda_l1: "L1 regularization strength.",
    lambda_l2: "L2 regularization strength.",
    subsample: "Row sampling rate per tree.",
    colsample_bytree: "Feature sampling rate per tree.",
    early_stopping_rounds: "Stop if validation does not improve.",
  };

  if (!label && (!features || features.length === 0)) {
    return null;
  }

  return (
    <div className="rounded-lg border bg-muted/30">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <span className="text-sm font-semibold">Model Spec</span>
          {!isOpen && modelClass && <Badge variant="outline" className="ml-2 scale-90">{modelClass}</Badge>}
        </div>
        {!isOpen && dataRange.start_time && (
           <div className="text-[10px] text-muted-foreground mr-2">
             {dataRange.start_time} → {dataRange.end_time}
           </div>
        )}
      </button>

      {isOpen && (
        <div className="p-4 pt-0 space-y-4 border-t bg-background/50">
          <div className="flex items-center justify-between mt-4">
            <div className="text-xs font-medium text-muted-foreground">Configuration Details</div>
            {modelClass && <Badge variant="outline">{modelClass}</Badge>}
          </div>

          <div className="grid gap-3 text-xs">
            {label && (
              <div>
                <span className="font-medium">Label:</span>{" "}
                {Array.isArray(label) ? label.join(" | ") : label}
              </div>
            )}
            {Array.isArray(features) && features.length > 0 && (
              <div>
                <span className="font-medium">Features ({features.length}):</span>{" "}
                {featurePreview.join(", ")}
                {featureRemainder > 0 && ` (+${featureRemainder} more)`}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {featurePack && <Badge>Pack: {featurePack}</Badge>}
              {Array.isArray(extraFeatures) && extraFeatures.length > 0 && (
                <Badge variant="secondary">Extra: {extraFeatures.length}</Badge>
              )}
              {dataRange.start_time && dataRange.end_time && (
                <Badge variant="outline">
                  {dataRange.start_time} → {dataRange.end_time}
                </Badge>
              )}
            </div>
          </div>

          <div className="grid gap-3 text-xs">
            {(segments?.train || segments?.valid || segments?.test) && (
              <div className="grid gap-1">
                {segments?.train && (
                  <div>
                    <span className="font-medium">Train:</span> {segments.train.join(" → ")}
                  </div>
                )}
                {segments?.valid && (
                  <div>
                    <span className="font-medium">Valid:</span> {segments.valid.join(" → ")}
                  </div>
                )}
                {segments?.test && (
                  <div>
                    <span className="font-medium">Test:</span> {segments.test.join(" → ")}
                  </div>
                )}
              </div>
            )}

            {modelKwargs && Object.keys(modelKwargs).length > 0 && (
              <div className="grid gap-2">
                <div className="font-medium">Model Params</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(modelKwargs).map(([k, v]) => (
                    <Badge key={k} variant="secondary">{`${k}=${v}`}</Badge>
                  ))}
                </div>
                <div>
                  <span className="font-medium">Param Guide:</span>{" "}
                  {Object.entries(modelKwargs)
                    .map(([k, v]) => {
                      const help = paramGuide[k] || "See model docs.";
                      return `${k}=${v} (${help})`;
                    })
                    .join(" | ")}
                </div>
              </div>
            )}
          </div>

          <div className="grid gap-2 text-xs">
            {spStrategy && Object.keys(spStrategy).length > 0 && (
              <div>
                <span className="font-medium">Strategy:</span>{" "}
                {String(spStrategy.buy_rule || '')} | {String(spStrategy.sell_rule || '')}
              </div>
            )}
            {spStrategy?.backtest_window != null && (
              <div>
                <span className="font-medium">Backtest Window:</span>{" "}
                {Array.isArray(spStrategy.backtest_window) ? (spStrategy.backtest_window as string[]).join(" → ") : String(spStrategy.backtest_window)}
              </div>
            )}
            {spStrategy?.capital !== undefined && (
              <div>
                <span className="font-medium">Capital:</span>{" "}
                {String(spStrategy.capital)}
              </div>
            )}
            {spStrategy?.costs_bps !== undefined && (
              <div>
                <span className="font-medium">Costs (bps):</span>{" "}
                {String(spStrategy.costs_bps)}
              </div>
            )}
            {wsStrategy?.kwargs != null && (
              <div>
                <span className="font-medium">Strategy Params:</span>{" "}
                {Object.entries(wsStrategy.kwargs as Record<string, unknown>)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")}
              </div>
            )}
            {wsBacktest && Object.keys(wsBacktest).length > 0 && (
              <div>
                <span className="font-medium">Backtest (cfg):</span>{" "}
                {String(wsBacktest.start_time || '')} →{" "}
                {String(wsBacktest.end_time || '')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
