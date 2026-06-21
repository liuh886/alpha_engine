export const artifactUrl = {
  dashboardDb: "/api/artifacts/dashboard-db",
  thoughtStream: "/api/artifacts/thought-stream",
  arenas: "/api/artifacts/arenas",
  reports: "/api/artifacts/reports",
  models: "/api/artifacts/models",
  dataStatus: "/api/artifacts/data-status",
  dataQuality: "/api/artifacts/data-quality",
  arenaLeaderboard: (arenaId: string) => `/api/artifacts/arena-leaderboard/${encodeURIComponent(arenaId)}`,
};
