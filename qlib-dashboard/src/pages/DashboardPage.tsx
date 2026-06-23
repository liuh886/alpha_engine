import { Dashboard } from '@/components/Dashboard';
import { useOutletContext } from 'react-router-dom';
import type { ModelData } from '@/lib/data-parser';

export function DashboardPage() {
  const { models, selectedModelId } = useOutletContext<{ models: ModelData[], selectedModelId: string }>();
  const selectedModel = models.find(m => m.id === selectedModelId) || models[0];

  return (
    <Dashboard 
      data={selectedModel?.backtest} 
      params={{ ...selectedModel?.params, id: selectedModel?.run_id || selectedModel?.id }}
    />
  );
}
