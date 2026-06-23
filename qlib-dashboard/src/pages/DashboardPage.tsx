import { TrueDashboard } from '@/components/TrueDashboard';
import { useModels } from '@/hooks/useModels';

export function DashboardPage() {
  const { models, selectedModelId } = useModels();
  const selectedModel = models.find(m => m.id === selectedModelId) || models[0];

  return (
    <TrueDashboard 
      model={selectedModel} 
      report={selectedModel?.backtest?.report} 
      positions={selectedModel?.backtest?.positions} 
    />
  );
}
