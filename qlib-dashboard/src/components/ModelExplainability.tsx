// TODO: ModelExplainability is currently a stub.
// Planned: SHAP feature importance chart + per-prediction waterfall breakdown.
// Tracked in: https://github.com/liuh886/alpha_engine/issues (create issue when ready to implement)

export function ModelExplainability() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
      <span className="text-4xl">🔬</span>
      <p className="text-sm font-medium">Model Explainability</p>
      <p className="text-xs text-muted-foreground/60 max-w-xs text-center">
        SHAP feature importance and per-prediction waterfall charts coming soon.
      </p>
    </div>
  );
}
