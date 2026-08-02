import { useOutletContext } from 'react-router-dom';
import { ArtifactHome } from '@/components/ArtifactHome';
import { useGlobalStore } from '@/store/globalStore';
import type { ModelData } from '@/lib/data-parser';

interface AppContext {
  models: ModelData[];
}

export function ArtifactStudioHomePage() {
  const { models } = useOutletContext<AppContext>();
  const generatedAt = useGlobalStore((state) => state.dataGeneratedAt);

  return (
    <ArtifactHome
      models={models}
      generatedAt={generatedAt}
      latestModel={models[0] ?? null}
    />
  );
}
