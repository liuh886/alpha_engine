import { useOutletContext } from 'react-router-dom';
import { ArtifactHome } from '@/components/ArtifactHome';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';
import { useGlobalStore } from '@/store/globalStore';
import type { ModelData } from '@/lib/data-parser';
import { HomePage } from './HomePage';

interface AppContext {
  models: ModelData[];
}

export function ArtifactStudioHomePage() {
  const { models } = useOutletContext<AppContext>();
  const generatedAt = useGlobalStore((state) => state.dataGeneratedAt);

  if (runtimeCapabilities.backendApi) {
    return <HomePage />;
  }

  return (
    <ArtifactHome
      models={models}
      generatedAt={generatedAt}
      latestModel={models[0] ?? null}
    />
  );
}
