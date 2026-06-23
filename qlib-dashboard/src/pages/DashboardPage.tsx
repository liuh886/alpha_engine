import { Dashboard } from '@/components/Dashboard';
import { useOutletContext } from 'react-router-dom';
import type { ModelData } from '@/lib/data-parser';

export function DashboardPage() {
  const { models, selectedModelId } = useOutletContext<{ models: ModelData[], selectedModelId: string }>();
  const selectedModel = models.find(m => m.id === selectedModelId) || models[0];

  if (!selectedModel || !selectedModel.backtest) {
    return (
      <div className="flex flex-col items-center justify-center py-16 border-2 border-dashed rounded-lg bg-muted/30 max-w-[1400px] mx-auto mt-10">
        <p className="text-muted-foreground text-sm">No dashboard data available. Please select a valid model.</p>
      </div>
    );
  }

  return (
    <Dashboard 
      data={selectedModel.backtest} 
      params={{ ...selectedModel.params, id: selectedModel.run_id || selectedModel.id }}
    />
  );
}
