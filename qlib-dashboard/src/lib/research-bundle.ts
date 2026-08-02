import { assetUrl } from './runtime-capabilities';

export interface BundleArtifact {
  artifact_id: string;
  kind: string;
  path: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  required: boolean;
}

export interface ResearchBundleManifest {
  schema_version: string;
  frontend_reader_range: string;
  bundle_id: string;
  title: string;
  generated_at: string;
  evidence_cutoff: string | null;
  research_only: true;
  trade_ready: false;
  scope: { markets: string[]; snapshot_id?: string | null; model_count: number };
  warnings: string[];
  blocked_gates: string[];
  promotion_decision: string;
  artifacts: BundleArtifact[];
}

export interface DashboardBundleData {
  generated_at: string | null;
  snapshot_id: string;
  models: unknown[];
}

export interface BundleFileSource {
  readonly label: string;
  read(path: string): Promise<Blob>;
}

export interface OpenedResearchBundle {
  manifest: ResearchBundleManifest;
  dashboard: DashboardBundleData;
  source: BundleFileSource;
  integrity: 'required_verified' | 'all_verified';
}

const BUNDLE_MANIFEST = 'alpha-engine-bundle.json';
let activeBundle: OpenedResearchBundle | null = null;
const listeners = new Set<() => void>();

function safePath(path: string): string {
  const normalized = path.replace(/\\/g, '/').replace(/^\.\//, '');
  if (!normalized || normalized.startsWith('/') || normalized.split('/').includes('..')) {
    throw new Error(`Unsafe bundle path: ${path}`);
  }
  return normalized;
}

function blobFromBytes(bytes: Uint8Array): Blob {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return new Blob([copy.buffer]);
}

function readBlobAsText(blob: Blob): Promise<string> {
  if (typeof blob.text === 'function') return blob.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read bundle text.'));
    reader.readAsText(blob);
  });
}

function readBlobAsArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result);
      else reject(new Error('Unable to read bundle bytes.'));
    };
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read bundle bytes.'));
    reader.readAsArrayBuffer(blob);
  });
}

export function validateBundleManifest(value: unknown): ResearchBundleManifest {
  if (!value || typeof value !== 'object') throw new Error('Bundle manifest is not an object.');
  const manifest = value as Partial<ResearchBundleManifest>;
  const major = String(manifest.schema_version ?? '').split('.')[0];
  if (major !== '1') throw new Error(`Unsupported bundle schema: ${manifest.schema_version ?? 'missing'}`);
  if (manifest.research_only !== true || manifest.trade_ready !== false) throw new Error('Bundle research boundary is missing or invalid.');
  if (!Array.isArray(manifest.artifacts)) throw new Error('Bundle artifact index is missing.');
  for (const artifact of manifest.artifacts) {
    safePath(String(artifact.path));
    if (!/^[a-f0-9]{64}$/.test(String(artifact.sha256))) throw new Error(`Invalid artifact digest: ${artifact.path}`);
  }
  return manifest as ResearchBundleManifest;
}

async function blobJson<T>(blob: Blob): Promise<T> {
  return JSON.parse(await readBlobAsText(blob)) as T;
}

async function sha256(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await readBlobAsArrayBuffer(blob));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function verifyArtifact(source: BundleFileSource, artifact: BundleArtifact): Promise<Blob> {
  const blob = await source.read(safePath(artifact.path));
  if (blob.size !== artifact.byte_size) throw new Error(`Artifact size mismatch: ${artifact.path}`);
  if ((await sha256(blob)) !== artifact.sha256) throw new Error(`Artifact digest mismatch: ${artifact.path}`);
  return blob;
}

export async function openResearchBundle(source: BundleFileSource, options: { verifyAll?: boolean } = {}): Promise<OpenedResearchBundle> {
  const manifest = validateBundleManifest(await blobJson(await source.read(BUNDLE_MANIFEST)));
  const required = manifest.artifacts.filter((artifact) => artifact.required);
  const selected = options.verifyAll ? manifest.artifacts : required;
  await Promise.all(selected.map((artifact) => verifyArtifact(source, artifact)));
  const modelsArtifact = manifest.artifacts.find((artifact) => artifact.kind === 'model_index');
  const staticManifestArtifact = manifest.artifacts.find((artifact) => artifact.kind === 'static_export_manifest');
  if (!modelsArtifact || !staticManifestArtifact) throw new Error('Bundle does not contain required model and export indexes.');
  const [models, staticManifest] = await Promise.all([
    blobJson<unknown[]>(await source.read(modelsArtifact.path)),
    blobJson<Record<string, unknown>>(await source.read(staticManifestArtifact.path)),
  ]);
  if (!Array.isArray(models)) throw new Error('Bundle model index is invalid.');
  return {
    manifest,
    source,
    integrity: options.verifyAll ? 'all_verified' : 'required_verified',
    dashboard: {
      generated_at: manifest.generated_at || null,
      snapshot_id: String(manifest.scope.snapshot_id ?? staticManifest.snapshot_id ?? 'local'),
      models,
    },
  };
}

export class HttpBundleSource implements BundleFileSource {
  readonly label = 'GitHub Pages bundle';
  constructor(private readonly root = 'bundle') {}
  async read(path: string): Promise<Blob> {
    const response = await fetch(assetUrl(`${this.root}/${safePath(path)}`), { cache: 'no-store' });
    if (!response.ok) throw new Error(`Bundle file unavailable: ${path}`);
    return response.blob();
  }
}

export class FileSetBundleSource implements BundleFileSource {
  readonly label: string;
  private readonly files = new Map<string, File>();
  constructor(input: Iterable<File>, label = 'Selected local files') {
    this.label = label;
    const rows = Array.from(input);
    const candidates = rows.map((file) => (file.webkitRelativePath || file.name).replace(/\\/g, '/'));
    const manifestPath = candidates.find((path) => path.endsWith(`/${BUNDLE_MANIFEST}`) || path === BUNDLE_MANIFEST);
    if (!manifestPath) throw new Error('alpha-engine-bundle.json was not found in the selected files.');
    const prefix = manifestPath.slice(0, -BUNDLE_MANIFEST.length);
    rows.forEach((file, index) => {
      const candidate = candidates[index];
      if (candidate.startsWith(prefix)) this.files.set(safePath(candidate.slice(prefix.length)), file);
    });
  }
  async read(path: string): Promise<Blob> {
    const file = this.files.get(safePath(path));
    if (!file) throw new Error(`Selected bundle file is missing: ${path}`);
    return file;
  }
}

interface DirectoryFileHandle { getFile(): Promise<File> }
export interface DirectoryHandleLike {
  name: string;
  getFileHandle(name: string): Promise<DirectoryFileHandle>;
  getDirectoryHandle(name: string): Promise<DirectoryHandleLike>;
  queryPermission?(descriptor?: { mode?: 'read' }): Promise<PermissionState>;
  requestPermission?(descriptor?: { mode?: 'read' }): Promise<PermissionState>;
}

export class DirectoryBundleSource implements BundleFileSource {
  readonly label: string;
  constructor(readonly handle: DirectoryHandleLike) { this.label = handle.name || 'Local results folder'; }
  async read(path: string): Promise<Blob> {
    const parts = safePath(path).split('/');
    let directory = this.handle;
    for (const part of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(part);
    return (await directory.getFileHandle(parts[parts.length - 1])).getFile();
  }
}

function uint16(view: DataView, offset: number): number { return view.getUint16(offset, true); }
function uint32(view: DataView, offset: number): number { return view.getUint32(offset, true); }

async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream === 'undefined') throw new Error('ZIP deflate is not supported by this browser.');
  const stream = blobFromBytes(bytes).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export class ZipBundleSource implements BundleFileSource {
  readonly label: string;
  private constructor(label: string, private readonly entries: Map<string, Blob>) { this.label = label; }

  static async fromFile(file: File): Promise<ZipBundleSource> {
    const bytes = new Uint8Array(await readBlobAsArrayBuffer(file));
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let eocd = -1;
    for (let index = bytes.length - 22; index >= Math.max(0, bytes.length - 65557); index -= 1) {
      if (uint32(view, index) === 0x06054b50) { eocd = index; break; }
    }
    if (eocd < 0) throw new Error('ZIP end-of-central-directory record was not found.');
    const entryCount = uint16(view, eocd + 10);
    let cursor = uint32(view, eocd + 16);
    const rawEntries: Array<{ name: string; method: number; size: number; compressedSize: number; localOffset: number }> = [];
    const decoder = new TextDecoder();
    for (let index = 0; index < entryCount; index += 1) {
      if (uint32(view, cursor) !== 0x02014b50) throw new Error('Invalid ZIP central directory.');
      const method = uint16(view, cursor + 10);
      const compressedSize = uint32(view, cursor + 20);
      const size = uint32(view, cursor + 24);
      const nameLength = uint16(view, cursor + 28);
      const extraLength = uint16(view, cursor + 30);
      const commentLength = uint16(view, cursor + 32);
      const localOffset = uint32(view, cursor + 42);
      const name = decoder.decode(bytes.slice(cursor + 46, cursor + 46 + nameLength));
      if (!name.endsWith('/')) rawEntries.push({ name, method, size, compressedSize, localOffset });
      cursor += 46 + nameLength + extraLength + commentLength;
    }
    const manifestEntry = rawEntries.find((entry) => entry.name.endsWith(`/${BUNDLE_MANIFEST}`) || entry.name === BUNDLE_MANIFEST);
    if (!manifestEntry) throw new Error('ZIP does not contain alpha-engine-bundle.json.');
    const prefix = manifestEntry.name.slice(0, -BUNDLE_MANIFEST.length);
    const entries = new Map<string, Blob>();
    for (const entry of rawEntries) {
      if (!entry.name.startsWith(prefix)) continue;
      const local = entry.localOffset;
      if (uint32(view, local) !== 0x04034b50) throw new Error(`Invalid ZIP local header: ${entry.name}`);
      const nameLength = uint16(view, local + 26);
      const extraLength = uint16(view, local + 28);
      const start = local + 30 + nameLength + extraLength;
      const compressed = bytes.slice(start, start + entry.compressedSize);
      const content = entry.method === 0 ? compressed : entry.method === 8 ? await inflateRaw(compressed) : null;
      if (!content) throw new Error(`Unsupported ZIP compression method ${entry.method}.`);
      if (content.byteLength !== entry.size) throw new Error(`ZIP entry size mismatch: ${entry.name}`);
      entries.set(safePath(entry.name.slice(prefix.length)), blobFromBytes(content));
    }
    return new ZipBundleSource(file.name, entries);
  }

  async read(path: string): Promise<Blob> {
    const blob = this.entries.get(safePath(path));
    if (!blob) throw new Error(`ZIP bundle file is missing: ${path}`);
    return blob;
  }
}

export function getActiveResearchBundle(): OpenedResearchBundle | null { return activeBundle; }
export function setActiveResearchBundle(bundle: OpenedResearchBundle | null): void {
  activeBundle = bundle;
  listeners.forEach((listener) => listener());
}
export function subscribeResearchBundle(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export async function loadStaticResearchBundle(): Promise<OpenedResearchBundle> {
  return openResearchBundle(new HttpBundleSource());
}
