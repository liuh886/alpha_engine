import { Badge } from "@/components/ui/badge";
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

export function ModelSpec({ params }: { params: Record<string, any> }) {
  const [isOpen, setIsOpen] = useState(false);
  const meta = params?.meta || {};
  const strategyProfile = meta.strategy_profile || {};
  const workflowSnapshot = meta.workflow_snapshot || {};
  const label = meta.label;
  const features = meta.features || [];
  const dataRange = meta.data_range || {};
  const segments = meta.segments || {};
  const modelClass = meta.model_class || params.model_class || params["model.class"];
  const modelKwargs = meta.model_kwargs || {};
  const modelProfile = strategyProfile.model || {};
  const featurePack = modelProfile.feature_pack || meta.feature_pack;
  const extraFeatures = modelProfile.extra_features || meta.extra_features || [];

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
            {strategyProfile?.strategy && (
              <div>
                <span className="font-medium">Strategy:</span>{" "}
                {strategyProfile.strategy.buy_rule} | {strategyProfile.strategy.sell_rule}
              </div>
            )}
            {strategyProfile?.strategy?.backtest_window && (
              <div>
                <span className="font-medium">Backtest Window:</span>{" "}
                {strategyProfile.strategy.backtest_window.join(" → ")}
              </div>
            )}
            {strategyProfile?.strategy?.capital !== undefined && (
              <div>
                <span className="font-medium">Capital:</span>{" "}
                {strategyProfile.strategy.capital}
              </div>
            )}
            {strategyProfile?.strategy?.costs_bps !== undefined && (
              <div>
                <span className="font-medium">Costs (bps):</span>{" "}
                {strategyProfile.strategy.costs_bps}
              </div>
            )}
            {workflowSnapshot?.port_analysis_config?.strategy?.kwargs && (
              <div>
                <span className="font-medium">Strategy Params:</span>{" "}
                {Object.entries(workflowSnapshot.port_analysis_config.strategy.kwargs)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")}
              </div>
            )}
            {workflowSnapshot?.port_analysis_config?.backtest && (
              <div>
                <span className="font-medium">Backtest (cfg):</span>{" "}
                {workflowSnapshot.port_analysis_config.backtest.start_time} →{" "}
                {workflowSnapshot.port_analysis_config.backtest.end_time}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
