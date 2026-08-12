import { createClient } from "npm:@supabase/supabase-js@2";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6";

const GITHUB_ISSUER = "https://token.actions.githubusercontent.com";
const GITHUB_JWKS = createRemoteJWKSet(
  new URL("https://token.actions.githubusercontent.com/.well-known/jwks"),
);
const EXPECTED_AUDIENCE = "alpha-engine-supabase";
const EXPECTED_REPOSITORY = "liuh886/alpha_engine";
const EXPECTED_REPOSITORY_ID = "1275788222";
const EXPECTED_OWNER_ID = "7567311";
const EXPECTED_REF = "refs/heads/main";
const EXPECTED_WORKFLOW_PREFIX = `${EXPECTED_REPOSITORY}/.github/workflows/`;
const EXPECTED_WORKFLOW_SUFFIX = `@${EXPECTED_REF}`;

interface StrategyOperationsDocument {
  schema_version?: unknown;
  research_only?: unknown;
  trade_ready?: unknown;
  records?: unknown;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function assertString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
}

async function verifyGitHubPublisher(req: Request): Promise<void> {
  const authorization = req.headers.get("authorization") ?? "";
  if (!authorization.startsWith("Bearer ")) throw new Error("missing GitHub OIDC bearer token");
  const token = authorization.slice("Bearer ".length);
  const { payload } = await jwtVerify(token, GITHUB_JWKS, {
    issuer: GITHUB_ISSUER,
    audience: EXPECTED_AUDIENCE,
  });

  if (payload.repository !== EXPECTED_REPOSITORY) throw new Error("untrusted repository");
  if (String(payload.repository_id ?? "") !== EXPECTED_REPOSITORY_ID) throw new Error("untrusted repository id");
  if (String(payload.repository_owner_id ?? "") !== EXPECTED_OWNER_ID) throw new Error("untrusted repository owner id");
  if (payload.ref !== EXPECTED_REF) throw new Error("publisher must run from main");
  if (payload.ref_type !== "branch") throw new Error("publisher ref must be a branch");

  const workflowRef = String(payload.workflow_ref ?? "");
  if (!workflowRef.startsWith(EXPECTED_WORKFLOW_PREFIX) || !workflowRef.endsWith(EXPECTED_WORKFLOW_SUFFIX)) {
    throw new Error("publisher workflow is not sourced from main");
  }
}

async function fingerprint(record: Record<string, unknown>): Promise<string> {
  const ledger = record.source_identity;
  if (ledger && typeof ledger === "object" && !Array.isArray(ledger)) {
    const value = (ledger as Record<string, unknown>).ledger_fingerprint;
    if (typeof value === "string" && value.length > 0) return value;
  }
  const bytes = new TextEncoder().encode(JSON.stringify(record));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  try {
    await verifyGitHubPublisher(req);
    const document = await req.json() as StrategyOperationsDocument;
    if (document.schema_version !== "2.2.0") throw new Error("unsupported Strategy Operations schema");
    if (document.research_only !== true || document.trade_ready !== false) throw new Error("invalid research/trade boundary");
    if (!Array.isArray(document.records) || document.records.length === 0) throw new Error("strategy operations records are required");

    const strategyIds = new Set<string>();
    const modelVersionIds = new Set<string>();
    const rows = [];
    for (const raw of document.records) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("invalid strategy operation record");
      const record = raw as Record<string, unknown>;
      assertString(record.strategy_id, "strategy_id");
      assertString(record.model_version_id, "model_version_id");
      if (strategyIds.has(record.strategy_id)) throw new Error(`duplicate strategy_id: ${record.strategy_id}`);
      if (modelVersionIds.has(record.model_version_id)) throw new Error(`duplicate model_version_id: ${record.model_version_id}`);
      strategyIds.add(record.strategy_id);
      modelVersionIds.add(record.model_version_id);
      rows.push({
        strategy_id: record.strategy_id,
        model_version_id: record.model_version_id,
        source_fingerprint: await fingerprint(record),
        snapshot: { ...record, research_only: true, trade_ready: false },
        updated_at: new Date().toISOString(),
      });
    }

    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceRole = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    if (!supabaseUrl || !serviceRole) throw new Error("Supabase runtime credentials are unavailable");
    const admin = createClient(supabaseUrl, serviceRole, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    const { data: policies, error: policyError } = await admin
      .from("product_access_policies")
      .select("resource_id")
      .eq("product_code", "alpha_engine")
      .eq("resource_type", "strategy")
      .in("resource_id", [...strategyIds]);
    if (policyError) throw policyError;
    const declared = new Set((policies ?? []).map((row) => String(row.resource_id)));
    const missing = [...strategyIds].filter((strategyId) => !declared.has(strategyId));
    if (missing.length) throw new Error(`runtime access policy missing for: ${missing.join(", ")}`);

    const { error: upsertError } = await admin
      .from("strategy_operation_snapshots")
      .upsert(rows, { onConflict: "strategy_id" });
    if (upsertError) throw upsertError;

    return json({
      status: "published",
      strategy_count: rows.length,
      strategy_ids: rows.map((row) => row.strategy_id).sort(),
      research_only: true,
      trade_ready: false,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const authFailure = /OIDC|token|repository|publisher|workflow|main|ref/i.test(message);
    return json({ error: message }, authFailure ? 401 : 400);
  }
});
