import { TrueDashboard } from '@/components/TrueDashboard';
import { ModelData } from '@/lib/data-parser';

export function DashboardPage({ model, report, positions }: { model?: ModelData | null, report?: any, positions?: any }) {
  return (
    <TrueDashboard 
      model={model} 
      report={report} 
      positions={positions} 
    />
  );
}
