import { createClient } from "npm:@supabase/supabase-js@2";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6";
import { createPublishHandler } from "./handler.ts";

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

function getAdminClient() {
  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRole = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceRole) throw new Error("Supabase runtime credentials are unavailable");
  return createClient(supabaseUrl, serviceRole, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

const handler = createPublishHandler({
  verifyPublisher: verifyGitHubPublisher,
  getAdminClient,
});

Deno.serve(handler);
