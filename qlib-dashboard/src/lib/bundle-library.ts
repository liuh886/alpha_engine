import type { DirectoryHandleLike, ResearchBundleManifest } from './research-bundle';

export interface RecentBundleRecord {
  bundleId: string;
  title: string;
  generatedAt: string;
  evidenceCutoff: string | null;
  sourceLabel: string;
  openedAt: string;
  directoryHandle?: DirectoryHandleLike;
}

const DB_NAME = 'alpha-engine-artifact-library';
const STORE_NAME = 'bundles';
const DB_VERSION = 1;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: 'bundleId' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Unable to open bundle library.'));
  });
}

async function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, mode);
      const request = action(tx.objectStore(STORE_NAME));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error('Bundle library operation failed.'));
    });
  } finally {
    db.close();
  }
}

export async function rememberBundle(
  manifest: ResearchBundleManifest,
  sourceLabel: string,
  directoryHandle?: DirectoryHandleLike,
): Promise<void> {
  const record: RecentBundleRecord = {
    bundleId: manifest.bundle_id,
    title: manifest.title,
    generatedAt: manifest.generated_at,
    evidenceCutoff: manifest.evidence_cutoff,
    sourceLabel,
    openedAt: new Date().toISOString(),
    ...(directoryHandle ? { directoryHandle } : {}),
  };
  await transaction('readwrite', (store) => store.put(record));
}

export async function listRecentBundles(): Promise<RecentBundleRecord[]> {
  const rows = await transaction<RecentBundleRecord[]>('readonly', (store) => store.getAll());
  return rows.sort((a, b) => b.openedAt.localeCompare(a.openedAt));
}

export async function forgetBundle(bundleId: string): Promise<void> {
  await transaction('readwrite', (store) => store.delete(bundleId));
}
