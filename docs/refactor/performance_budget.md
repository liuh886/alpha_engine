# Performance Budget

This document outlines the performance budgets for Alpha Engine's frontend.

## 1. Bundle Size Budget

To ensure the Dashboard loads quickly even over slow network conditions, the frontend bundle must adhere to the following budgets:

- **Max Total JS Size (gzip)**: `< 450KB`
- **Current Footprint** (as of vNext refactor): `~402KB gzip` (well within budget)

The build pipeline relies on `vite-plugin-singlefile` to inline assets, producing a single HTML file. The maximum raw size limit should not exceed `~1.5MB`, which compresses to the gzip target above.

## 2. Interaction Budget

- **Time to Interactive (TTI)**: `< 2s` on modern devices.
- **Route Transitions**: `< 100ms` for lazy-loaded routes via `React.lazy`.
- **API Polling Intervals**:
  - Global jobs/status updates: `10s` default (see `useJobs`).
  - Active polling should self-terminate or be cleaned up properly on component unmount or when transitioning states to prevent memory leaks and unnecessary network load.

## 3. Enforcement

- During CI (`npm run build`), Vite will emit size warnings if chunks exceed limits.
- The single-file build must be kept lean. If size exceeds the budget, large dependencies (e.g., heavy charting libraries or mapping tools) must be lazy-loaded or audited.
- UI empty states and loading boundaries must use the `<Placeholder>` component to ensure instant perceived feedback without blocking main thread rendering.
