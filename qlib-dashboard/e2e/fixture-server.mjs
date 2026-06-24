import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const port = Number(process.env.PORT || 43173);
const root = fileURLToPath(new URL("../dist/", import.meta.url));
const fixturesDir = fileURLToPath(new URL("../../fixtures/contract/", import.meta.url));
const expectedAuth = `Basic ${Buffer.from("release-user:release-pass").toString("base64")}`;

// Load contract fixtures (single source of truth for E2E, demo mode, and tests)
const identity = JSON.parse(await readFile(join(fixturesDir, "identity.json"), "utf8"));
const dashboardArtifact = JSON.parse(await readFile(join(fixturesDir, "dashboard_artifact.json"), "utf8"));
const modelVersionsResponse = JSON.parse(await readFile(join(fixturesDir, "model_versions.json"), "utf8"));
const modelVersions = modelVersionsResponse.versions || modelVersionsResponse;

const { snapshot_id: snapshotId, workflow_id: workflowId, run_id: runId, model_id: modelId } = identity;

function json(response, status, payload) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(payload));
}

async function readJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
}

async function handleApi(request, response, url) {
  if (url.pathname === "/api/system/me") {
    return request.headers.authorization === expectedAuth
      ? json(response, 200, { ok: true, username: "release-user" })
      : json(response, 401, { detail: "Invalid credentials" });
  }
  if (url.pathname === "/artifacts/dashboard.json" || url.pathname === "/api/artifacts/dashboard-db") {
    return json(response, 200, dashboardArtifact);
  }
  if (url.pathname === "/api/data/status") return json(response, 200, {
    ok: true,
    data: {
      latest_calendar_date: "2026-06-20",
      latest_calendar_day: "2026-06-20",
      dashboard_generated_at: "2026-06-20T08:00:00Z",
      latest_snapshot_id: snapshotId,
      quality_status: "ok",
      quality_warnings: [],
      symbols_configured: 1,
      symbols_updated: 1,
      symbols_failed: 0,
      symbols_stale: 0,
    },
  });
  if (url.pathname === "/api/data/watchlist") return json(response, 200, {
    ok: true,
    watchlist: { cn: [{ symbol: "600519", name: "Kweichow Moutai" }], us: [], hk: [] },
  });
  if (url.pathname === "/api/data/name-map") return json(response, 200, {
    ok: true,
    name_map: { "600519": "Kweichow Moutai" },
  });
  if (url.pathname === "/api/jobs") return json(response, 200, { ok: true, jobs: [] });
  if (url.pathname === "/api/models" && request.method === "GET") {
    const market = url.searchParams.get("market");
    const versions = market ? modelVersions.filter((model) => model.market === market) : modelVersions;
    return json(response, 200, { ok: true, schema_version: "v1", versions });
  }
  if (url.pathname === "/api/workflow/train" && request.method === "POST") {
    const body = await readJson(request);
    if (body?.details?.snapshot_id !== snapshotId) {
      return json(response, 422, { detail: "Explicit snapshot identity is required" });
    }
    return json(response, 200, { ok: true, workflow_id: workflowId, message: "started" });
  }
  if (url.pathname === "/api/workflow/status") return json(response, 200, [{
    workflow_id: workflowId,
    name: "Pipeline Run: cn",
    market: "CN",
    status: "SUCCESS",
    details: { snapshot_id: snapshotId, run_id: runId },
  }]);
  if (url.pathname === `/api/evidence/model/${modelId}`) return json(response, 200, {
    ok: true,
    bundle: {
      subject_type: "model",
      subject_id: modelId,
      generated_at: "2026-06-20T08:01:00Z",
      sources: [{ name: "model_registry", status: "found" }],
      warnings: [],
      decision: "STAGING",
      completeness_score: 1,
    },
  });
  if (url.pathname === "/api/arena/list") return json(response, 200, { ok: true, arenas: [] });
  return json(response, 404, { detail: `No fixture for ${request.method} ${url.pathname}` });
}

async function handleStatic(response, pathname) {
  const requested = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const safePath = normalize(requested).replace(/^(\.\.[/\\])+/, "");
  const path = join(root, safePath);
  try {
    const body = await readFile(path);
    const type = extname(path) === ".html" ? "text/html; charset=utf-8" : "application/octet-stream";
    response.writeHead(200, { "Content-Type": type });
    response.end(body);
  } catch {
    const body = await readFile(join(root, "index.html"));
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(body);
  }
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host}`);
    if (url.pathname.startsWith("/api/")) await handleApi(request, response, url);
    else if (url.pathname === "/artifacts/dashboard.json") json(response, 200, dashboardArtifact);
    else await handleStatic(response, url.pathname);
  } catch (error) {
    json(response, 500, { detail: error instanceof Error ? error.message : String(error) });
  }
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`fixture backend listening on http://127.0.0.1:${port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
