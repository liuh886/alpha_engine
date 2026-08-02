# Local Research Bundle Loading

The GitHub Pages/PWA application can open Alpha Engine research outputs without uploading them.

## Supported paths

1. **Directory picker** — Chromium-based browsers can grant reusable read access to the bundle root.
2. **Folder file selection** — browsers that expose directory upload can provide the complete file set without retaining a handle.
3. **ZIP bundle** — stored and deflate-compressed ZIP entries are read directly in the browser.
4. **Published example bundle** — the Pages deployment remains available when no local bundle is open.

## Privacy boundary

- Selected files are read by JavaScript running in the browser.
- The application performs no upload request for bundle contents.
- GitHub Pages receives no selected paths, model outputs, reports or notebooks.
- Only recent-bundle metadata and, where supported, a browser-managed directory handle are stored in IndexedDB.
- The user can revoke folder access through browser site permissions.

## Validation

The root `alpha-engine-bundle.json` is read first. The reader rejects unsupported major versions, absolute or parent-relative paths, missing required indexes, byte-size mismatches and SHA-256 mismatches. Required indexes verify on open. Optional large artifacts verify lazily unless the user requests full verification.

## Reconnect behavior

Reusable directory handles are stored only when the browser supports structured cloning of file-system handles. On a later visit, the application checks the current read permission and requests renewal when necessary. File-set and ZIP sources must be selected again because browser security does not persist their bytes.

## Browser limits

- ZIP64 and encrypted ZIP files are not supported.
- ZIP entries must use stored or deflate compression.
- Very large bundles should remain directory-based so large tables can be read individually.
- The application is read-only; it never rewrites the source bundle.
