import { readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const paths = {
  html: 'index.html', config: 'public/membership-config.js', app: 'src/App.tsx',
  membership: 'src/hooks/useAlphaMembership.ts', access: 'src/hooks/useAccessControl.tsx',
  rules: 'src/lib/model-access.ts', reader: 'src/hooks/useStrategyOperations.ts',
  operations: 'src/lib/strategy-operations.ts', brief: 'src/components/DailyResearchBrief.tsx',
  detail: 'src/pages/StrategyDetailPage.tsx', registry: '../configs/strategies/registry.json',
  migration: '../supabase/migrations/20260812022634_alpha_engine_strategy_access_policies.sql',
  splitRls: '../supabase/migrations/20260812031512_split_alpha_engine_strategy_access_rls.sql',
};
const content = Object.fromEntries(await Promise.all(Object.entries(paths).map(async ([key, path]) => [key, await readFile(resolve(root, path), 'utf8')])));
function requireText(key, values) {
  for (const value of values) if (!content[key].includes(value)) throw new Error(key + ' missing access contract: ' + value);
}
requireText('html', ['https://liuh886.github.io/admin/shared/account-shell.js?v=7', './membership-config.js']);
requireText('config', ["productCode: 'alpha_engine'", "entitlementCode: 'alpha_engine.pro'", "mountSelectors: ['[data-account-slot]']", 'billingEnabled: false']);
requireText('app', ['AccessControlProvider', 'data-account-slot']);
requireText('membership', ['app_metadata', "alpha_engine_role === 'owner'", 'snapshot.isPro === true', 'getClient']);
requireText('access', ["from('product_access_policies')", 'mergeAccessPolicies', 'canAccessTier', 'resolveRequiredTier']);
requireText('rules', ["resourceType === 'strategy' ? 'owner' : 'public'"]);
requireText('reader', ['access.canAccess', "access.requiredTier('strategy', snapshot.strategyId)", 'assertStrategyOperationRun', 'loadRuntimeStrategyOperations', 'controller.signal']);
requireText('brief', ['access.canAccess', "access.requiredTier('strategy', snapshot.strategyId)"]);
requireText('detail', ['access.canAccess', "access.requiredTier('strategy', snapshot.strategyId)", 'liveLocked', 'FormalBacktestReview']);
for (const [key, source] of Object.entries(content)) {
  if (['migration', 'splitRls'].includes(key)) continue;
  if (source.includes('current_operations_access') || source.includes('currentOperationsAccess')) throw new Error(key + ' declares a second access authority');
  for (const secret of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) if (secret.test(source)) throw new Error(key + ' exposes forbidden material');
}
if (content.html.includes('product-referral') || content.access.includes('.upsert(')) throw new Error('The personal console must not include referral or policy-write features.');
for (const value of ["array['strategy'::text, 'module'::text]", "p.resource_type = 'strategy'", 'p.resource_id = strategy_operation_snapshots.strategy_id']) {
  if (!content.migration.toLowerCase().includes(value.toLowerCase())) throw new Error('Missing server-side strategy policy: ' + value);
}
for (const value of ['Public strategy current operations', 'Authenticated strategy current operations', 'to anon, authenticated', 'to authenticated', "p.required_tier = 'public'", "p.required_tier = 'authenticated'", "p.required_tier = 'pro'", "p.required_tier = 'owner'", "e.entitlement_code = 'alpha_engine.pro'"]) {
  if (!content.splitRls.toLowerCase().includes(value.toLowerCase())) throw new Error('Missing strategy RLS boundary: ' + value);
}
if (content.splitRls.includes('grant select on public.entitlements to anon')) throw new Error('Anonymous reads must not expose entitlements.');
console.log('Read-only strategy access verified: server policies, protected current evidence and public formal history.');
