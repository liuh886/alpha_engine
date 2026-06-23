import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const port = Number(process.env.PORT || 43173);
const root = fileURLToPath(new URL("../dist/", import.meta.url));
const expectedAuth = `Basic ${Buffer.from("release-user:release-pass").toString("base64")}`;
const snapshotId = "snapshot-cn-20260620";
const workflowId = "workflow.run.cn";
const runId = "run-release-42";
const modelId = "artifact-release-42";

const report = (start, end) => ({
  columns: ["account", "return", "bench"],
  index: [start, end],
  data: [[1, 0, 0], [1.12, 0.12, 0.05]],
});

const dashboardArtifact = {
  generated_at: "2026-06-20T08:00:00Z",
  models: [
    {
      id: modelId,
      run_id: runId,
      name: "Release Candidate 42",
      market: "cn",
      date: "2026-06-20",
      params: { model_path: "/fixtures/release-42.pkl", data_snapshot_id: snapshotId },
      data: {
        indicators: {
          total_return: 0.12,
          annual_return: 0.18,
          sharpe: 1.42,
          information_ratio: 0.91,
          max_drawdown: -0.08,
          annual_volatility: 0.16,
        },
        report_normal: report("2026-01-02T00:00:00", "2026-06-19T00:00:00"),
        positions_normal: [
          { date: "2026-06-19", instrument: "SH600000", weight: 0.05 }
        ],
      },
    },
    {
      id: "artifact-baseline-01",
      run_id: "run-baseline-01",
      name: "Baseline Comparator",
      market: "cn",
      date: "2026-06-19",
      params: { model_path: "/fixtures/baseline.pkl", data_snapshot_id: snapshotId },
      data: {
        indicators: {
          total_return: 0.08,
          annual_return: 0.11,
          sharpe: 0.88,
          information_ratio: 0.54,
          max_drawdown: -0.11,
          annual_volatility: 0.18,
        },
        report_normal: report("2026-01-02T00:00:00", "2026-06-19T00:00:00"),
        positions_normal: [],
      },
    },
  ],
};

const modelVersions = [
  {
    id: modelId,
    tag: "release-candidate-42",
    name: "Release Candidate 42",
    market: "cn",
    model_type: "lgbm",
    run_id: runId,
    snapshot_id: snapshotId,
    evidence_id: modelId,
    created_at: "2026-06-20T07:55:00Z",
    description: "Stage: STAGING",
    params: { data_snapshot_id: snapshotId },
    metrics: { sharpe: 1.42, annualized_return: 0.18, max_drawdown: -0.08 },
  },
  {
    id: "artifact-baseline-01",
    tag: "baseline-comparator",
    name: "Baseline Comparator",
    market: "cn",
    model_type: "lgbm",
    run_id: "run-baseline-01",
    snapshot_id: snapshotId,
    evidence_id: "artifact-baseline-01",
    created_at: "2026-06-19T07:55:00Z",
    description: "Stage: STAGING",
    params: { data_snapshot_id: snapshotId },
    metrics: { sharpe: 0.88, annualized_return: 0.11, max_drawdown: -0.11 },
  },
];

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
