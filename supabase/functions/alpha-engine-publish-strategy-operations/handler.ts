export const AUTHORIZED_ACTIVE_STRATEGIES: Record<string, string> = {
  byd: "byd_v1_3_recovery_event_low_vol_confirmation_v1",
  cn_27: "cn_27_v1_3",
  qqq_rotation: "qqqi_qqq_tqqq_v4_3",
  us_x: "us_x1_3",
};

export interface StrategyOperationsDocument {
  schema_version?: unknown;
  research_only?: unknown;
  trade_ready?: unknown;
  records?: unknown;
}

export function json(body: unknown, status = 200): Response {
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

export async function fingerprint(record: Record<string, unknown>): Promise<string> {
  const ledger = record.source_identity;
  if (ledger && typeof ledger === "object" && !Array.isArray(ledger)) {
    const value = (ledger as Record<string, unknown>).ledger_fingerprint;
    if (typeof value === "string" && value.length > 0) return value;
  }
  const bytes = new TextEncoder().encode(JSON.stringify(record));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, "0")).join("");
}

export interface PublishHandlerDeps {
  verifyPublisher?: (req: Request) => Promise<void>;
  getAdminClient?: () => any;
}

export function createPublishHandler(deps: PublishHandlerDeps = {}) {
  return async function handlePublishRequest(req: Request): Promise<Response> {
    if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

    try {
      if (deps.verifyPublisher) {
        await deps.verifyPublisher(req);
      }
      const document = await req.json() as StrategyOperationsDocument;
      if (document.schema_version !== "2.2.0") throw new Error("unsupported Strategy Operations schema");
      if (document.research_only !== true || document.trade_ready !== false) throw new Error("invalid research/trade boundary");
      if (!Array.isArray(document.records) || document.records.length === 0) throw new Error("strategy operations records are required");

      const expectedCount = Object.keys(AUTHORIZED_ACTIVE_STRATEGIES).length;
      if (document.records.length !== expectedCount) {
        throw new Error(`exact ${expectedCount} active strategy records required; received ${document.records.length}`);
      }

      const strategyIds = new Set<string>();
      const modelVersionIds = new Set<string>();
      const rows = [];
      for (const raw of document.records) {
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("invalid strategy operation record");
        const record = raw as Record<string, unknown>;
        assertString(record.strategy_id, "strategy_id");
        assertString(record.model_version_id, "model_version_id");

        const expectedModel = AUTHORIZED_ACTIVE_STRATEGIES[record.strategy_id];
        if (!expectedModel) {
          throw new Error(`unauthorized strategy_id: ${record.strategy_id}`);
        }
        if (record.model_version_id !== expectedModel) {
          throw new Error(`model_version_id mismatch for ${record.strategy_id}: expected ${expectedModel}, received ${record.model_version_id}`);
        }

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

      for (const expectedId of Object.keys(AUTHORIZED_ACTIVE_STRATEGIES)) {
        if (!strategyIds.has(expectedId)) {
          throw new Error(`missing authorized active strategy: ${expectedId}`);
        }
      }

      if (!deps.getAdminClient) {
        throw new Error("Supabase admin client resolver is unavailable");
      }
      const admin = deps.getAdminClient();

      const { data: policies, error: policyError } = await admin
        .from("product_access_policies")
        .select("resource_id,required_tier")
        .eq("product_code", "alpha_engine")
        .eq("resource_type", "strategy")
        .in("resource_id", [...strategyIds]);
      if (policyError) throw policyError;
      const declared = new Set((policies ?? []).map((row: any) => String(row.resource_id)));
      const missing = [...strategyIds].filter((strategyId) => !declared.has(strategyId));
      if (missing.length) throw new Error(`runtime access policy missing for: ${missing.join(", ")}`);
      const unsafe = (policies ?? []).filter((row: any) => !["pro", "owner"].includes(row.required_tier));
      if (unsafe.length) {
        throw new Error(`current operations require protected tiers: ${unsafe.map((row: any) => row.resource_id).join(", ")}`);
      }

      const { error: upsertError } = await admin
        .from("strategy_operation_snapshots")
        .upsert(rows, { onConflict: "strategy_id" });
      if (upsertError) throw upsertError;

      // Retired rows are denied by the restrictive RLS allowlist, not deleted.
      // Production history must not be pruned as a side effect of publishing.

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
  };
}
