import test from "node:test";
import assert from "node:assert";
import {
  AUTHORIZED_ACTIVE_STRATEGIES,
  RETIRED_ALLOWLIST_STRATEGY_IDS,
  createPublishHandler,
} from "../supabase/functions/alpha-engine-publish-strategy-operations/handler.ts";

function createMockAdmin(options: {
  policies?: Array<{ resource_id: string; required_tier?: string }>;
  policyError?: Error | null;
  upsertError?: Error | null;
  pruneError?: Error | null;
} = {}) {
  const calls: {
    selectPolicies: string[][];
    upsertRows: any[];
    deleteIn: string[][];
  } = {
    selectPolicies: [],
    upsertRows: [],
    deleteIn: [],
  };

  const admin = {
    calls,
    from(table: string) {
      if (table === "product_access_policies") {
        return {
          select(_cols: string) {
            return {
              eq(_col1: string, _val1: string) {
                return {
                  eq(_col2: string, _val2: string) {
                    return {
                      in(_col3: string, ids: string[]) {
                        calls.selectPolicies.push(ids);
                        if (options.policyError) {
                          return Promise.resolve({ data: null, error: options.policyError });
                        }
                        const data = options.policies ?? ids.map((id) => ({ resource_id: id, required_tier: "pro" }));
                        return Promise.resolve({ data, error: null });
                      },
                    };
                  },
                };
              },
            };
          },
        };
      }
      if (table === "strategy_operation_snapshots") {
        return {
          upsert(rows: any[], _opts?: any) {
            calls.upsertRows.push(...rows);
            if (options.upsertError) {
              return Promise.resolve({ error: options.upsertError });
            }
            return Promise.resolve({ error: null });
          },
          delete() {
            return {
              in(_col: string, ids: string[]) {
                calls.deleteIn.push(ids);
                if (options.pruneError) {
                  return Promise.resolve({ error: options.pruneError });
                }
                return Promise.resolve({ error: null });
              },
            };
          },
        };
      }
      throw new Error(`Unexpected table: ${table}`);
    },
  };
  return admin;
}

function makeValidPayload() {
  return {
    schema_version: "2.2.0",
    research_only: true,
    trade_ready: false,
    records: Object.entries(AUTHORIZED_ACTIVE_STRATEGIES).map(([sid, mvid]) => ({
      strategy_id: sid,
      model_version_id: mvid,
      source_identity: { formal_bundle_id: `bundle_${sid}`, ledger_fingerprint: `fp_${sid}` },
      status: "active",
    })),
  };
}

function makeRequest(body: unknown, method = "POST"): Request {
  return new Request("http://localhost/functions/v1/alpha-engine-publish-strategy-operations", {
    method,
    headers: { "Content-Type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

for (const tier of ["public", "authenticated", undefined, "unknown"]) {
  test(`rejects unsafe current-operations tier ${tier} before ANY write`, async () => {
    const admin = createMockAdmin({ policies: Object.keys(AUTHORIZED_ACTIVE_STRATEGIES)
      .map((id) => ({ resource_id: id, required_tier: tier })) });
    const handler = createPublishHandler({ verifyPublisher: async () => {}, getAdminClient: () => admin });
    const response = await handler(makeRequest(makeValidPayload()));
    assert.strictEqual(response.status, 400);
    assert.match((await response.json()).error, /require protected tiers/);
    assert.strictEqual(admin.calls.upsertRows.length, 0);
    assert.strictEqual(admin.calls.deleteIn.length, 0);
  });
}

test("preserves Owner-only publication policy", async () => {
  const admin = createMockAdmin({ policies: Object.keys(AUTHORIZED_ACTIVE_STRATEGIES)
    .map((id) => ({ resource_id: id, required_tier: "owner" })) });
  const handler = createPublishHandler({ verifyPublisher: async () => {}, getAdminClient: () => admin });
  assert.strictEqual((await handler(makeRequest(makeValidPayload()))).status, 200);
  assert.strictEqual(admin.calls.upsertRows.length, 4);
});

test("rejects partial records (missing strategy) with HTTP 400 and performs ZERO DB writes", async () => {
  const admin = createMockAdmin();
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const payload = makeValidPayload();
  // Remove 'byd' to simulate partial 3-strategy emission
  payload.records = payload.records.filter((r) => r.strategy_id !== "byd");

  const res = await handler(makeRequest(payload));
  assert.strictEqual(res.status, 400);
  const data = await res.json();
  assert.match(data.error, /exact 4 active strategy records required; received 3/);

  // Must perform ZERO DB calls
  assert.strictEqual(admin.calls.upsertRows.length, 0);
  assert.strictEqual(admin.calls.deleteIn.length, 0);
});

test("rejects surplus records (extra strategy) with HTTP 400 and performs ZERO DB writes", async () => {
  const admin = createMockAdmin();
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const payload = makeValidPayload();
  payload.records.push({
    strategy_id: "extra_strategy",
    model_version_id: "extra_v1",
    source_identity: { formal_bundle_id: "b", ledger_fingerprint: "f" },
    status: "active",
  });

  const res = await handler(makeRequest(payload));
  assert.strictEqual(res.status, 400);
  const data = await res.json();
  assert.match(data.error, /exact 4 active strategy records required; received 5/);
  assert.strictEqual(admin.calls.upsertRows.length, 0);
  assert.strictEqual(admin.calls.deleteIn.length, 0);
});

test("rejects mismatched model_version_id with HTTP 400 and performs ZERO DB writes", async () => {
  const admin = createMockAdmin();
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const payload = makeValidPayload();
  const cn27 = payload.records.find((r) => r.strategy_id === "cn_27")!;
  cn27.model_version_id = "cn_x1_2"; // Attempt to publish stale retired model version

  const res = await handler(makeRequest(payload));
  assert.strictEqual(res.status, 400);
  const data = await res.json();
  assert.match(data.error, /model_version_id mismatch for cn_27/);
  assert.strictEqual(admin.calls.upsertRows.length, 0);
  assert.strictEqual(admin.calls.deleteIn.length, 0);
});

test("rejects unauthorized strategy_id with HTTP 400 and performs ZERO DB writes", async () => {
  const admin = createMockAdmin();
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const payload = makeValidPayload();
  payload.records[0].strategy_id = "unknown_strategy";

  const res = await handler(makeRequest(payload));
  assert.strictEqual(res.status, 400);
  const data = await res.json();
  assert.match(data.error, /unauthorized strategy_id: unknown_strategy/);
  assert.strictEqual(admin.calls.upsertRows.length, 0);
  assert.strictEqual(admin.calls.deleteIn.length, 0);
});

test("rejects publisher verification failure with HTTP 401 and performs ZERO DB writes", async () => {
  const admin = createMockAdmin();
  const handler = createPublishHandler({
    verifyPublisher: async () => {
      throw new Error("untrusted repository");
    },
    getAdminClient: () => admin,
  });

  const res = await handler(makeRequest(makeValidPayload()));
  assert.strictEqual(res.status, 401);
  const data = await res.json();
  assert.strictEqual(data.error, "untrusted repository");
  assert.strictEqual(admin.calls.upsertRows.length, 0);
  assert.strictEqual(admin.calls.deleteIn.length, 0);
});

test("accepts valid 4-strategy payload, upserts 4 rows, and prunes ONLY allowlisted retired identities", async () => {
  const admin = createMockAdmin();
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const res = await handler(makeRequest(makeValidPayload()));
  assert.strictEqual(res.status, 200);
  const data = await res.json();
  assert.strictEqual(data.status, "published");
  assert.strictEqual(data.strategy_count, 4);
  assert.deepStrictEqual(data.strategy_ids, ["byd", "cn_27", "qqq_rotation", "us_x"]);

  // Verify upserted rows
  assert.strictEqual(admin.calls.upsertRows.length, 4);
  const upsertedIds = admin.calls.upsertRows.map((r) => r.strategy_id).sort();
  assert.deepStrictEqual(upsertedIds, ["byd", "cn_27", "qqq_rotation", "us_x"]);

  // Verify prune called ONLY with allowlisted retired strategy IDs
  assert.strictEqual(admin.calls.deleteIn.length, 1);
  assert.deepStrictEqual(admin.calls.deleteIn[0], [...RETIRED_ALLOWLIST_STRATEGY_IDS]);
  assert.deepStrictEqual(admin.calls.deleteIn[0], ["cn_x"]);
});

test("simulated upsert failure halts execution and NEVER calls delete prune", async () => {
  const admin = createMockAdmin({ upsertError: new Error("DB connection lost during upsert") });
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const res = await handler(makeRequest(makeValidPayload()));
  assert.strictEqual(res.status, 400);
  const data = await res.json();
  assert.strictEqual(data.error, "DB connection lost during upsert");

  // Verify delete prune was NEVER invoked
  assert.strictEqual(admin.calls.deleteIn.length, 0);
});

test("simulated prune failure returns HTTP 400", async () => {
  const admin = createMockAdmin({ pruneError: new Error("DB lock timeout during prune") });
  const handler = createPublishHandler({
    verifyPublisher: async () => {},
    getAdminClient: () => admin,
  });

  const res = await handler(makeRequest(makeValidPayload()));
  assert.strictEqual(res.status, 400);
  const data = await res.json();
  assert.strictEqual(data.error, "DB lock timeout during prune");
});
