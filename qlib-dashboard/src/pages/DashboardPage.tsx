import { TrueDashboard } from '@/components/TrueDashboard';
import { useOutletContext } from 'react-router-dom';
import type { ModelData } from '@/lib/data-parser';

export function DashboardPage() {
  const { models, selectedModelId } = useOutletContext<{ models: ModelData[], selectedModelId: string }>();
  const selectedModel = models.find(m => m.id === selectedModelId) || models[0];

  return (
    <TrueDashboard 
      model={selectedModel} 
      report={selectedModel?.backtest?.report || []} 
      positions={selectedModel?.backtest?.positions || []} 
    />
  );
}
