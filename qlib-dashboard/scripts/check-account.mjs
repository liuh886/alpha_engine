import { access, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const files = {
  config: resolve(root, 'public/membership-config.js'),
  styles: resolve(root, 'public/account-integration.css'),
  app: resolve(root, 'src/App.tsx'),
  accessRules: resolve(root, 'src/lib/model-access.ts'),
  operationsLib: resolve(root, 'src/lib/strategy-operations.ts'),
  membershipHook: resolve(root, 'src/hooks/useAlphaMembership.ts'),
  accessHook: resolve(root, 'src/hooks/useAccessControl.tsx'),
  fleet: resolve(root, 'src/components/StrategyFleet.tsx'),
  gate: resolve(root, 'src/components/AccessGate.tsx'),
  routes: resolve(root, 'src/routes.ts'),
  settings: resolve(root, 'src/pages/AccessSettingsPage.tsx'),
  runs: resolve(root, 'src/pages/RunsPage.tsx'),
  compare: resolve(root, 'src/pages/ComparePage.tsx'),
  registry: resolve(root, '../configs/strategies/registry.json'),
  moduleMigration: resolve(root, '../supabase/migrations/20260809070851_alpha_engine_access_control.sql'),
  strategyMigration: resolve(root, '../supabase/migrations/20260812022634_alpha_engine_strategy_access_policies.sql'),
};
await Promise.all(Object.values(files).map((path) => access(path)));

const content = Object.fromEntries(await Promise.all(Object.entries(files).map(async ([key, path]) => [key, await readFile(path, 'utf8')])));
const html = await readFile(resolve(root, 'index.html'), 'utf8');

for (const reference of [
  'https://liuh886.github.io/admin/shared/account-shell.css?v=5',
  'https://liuh886.github.io/admin/shared/account-upgrade.css?v=1',
  'https://liuh886.github.io/admin/shared/account-shell.js?v=6',
  'https://liuh886.github.io/admin/shared/account-upgrade.js?v=5',
  './account-integration.css',
]) {
  if (!html.includes(reference)) throw new Error(`index.html missing canonical account asset: ${reference}`);
}
if (html.includes('./account-shell/')) throw new Error('AlphaEngine must not ship a duplicated account-shell copy.');

for (const value of [
  'window.HaoAccountConfig',
  "productCode: 'alpha_engine'",
  "entitlementCode: 'alpha_engine.pro'",
  "mountSelectors: ['[data-account-slot]']",
  'billingEnabled: true',
  '正式模型的历史绩效与风险证据公开展示',
  '查看 Pro 模型的当前持仓与目标调仓',
  '查看当前交易信号、驱动因子与下一决策状态',
  'feedbackEnabled: false',
]) {
  if (!content.config.includes(value)) throw new Error(`account config missing: ${value}`);
}
if (/Owner|Guest：|Member：|access levels|configure access/i.test(content.config)) {
  throw new Error('Public account copy must not expose internal access-control roles or configuration rules.');
}
if (/QQQ (family|series|Pro)|QQQ 系列/.test(content.config)) {
  throw new Error('Account and upgrade copy must not bind Pro access to the QQQ model family.');
}
for (const value of ['AccessControlProvider', 'AccessGate', 'accessResourceId', "ownerOnly\n    ? 'owner'"]) {
  if (!content.app.includes(value)) throw new Error(`research shell missing module access boundary: ${value}`);
}
if (content.app.includes('requiredTierForModel')) throw new Error('Historical strategy routes must not use model-family access gates.');
for (const value of [
  "export type AccessTier = 'public' | 'authenticated' | 'pro' | 'owner'",
  "export type AccessResourceType = 'module' | 'strategy'",
  'DEFAULT_ACCESS_POLICIES',
  "resourceId: 'securities'",
  'resolveRequiredTier',
  "resourceType === 'strategy' ? 'owner' : 'public'",
]) {
  if (!content.accessRules.includes(value)) throw new Error(`access policy contract missing: ${value}`);
}
if (content.accessRules.includes("resourceId: 'qqq_rotation'") || content.accessRules.includes("resourceType: 'model'")) {
  throw new Error('Strategy current-operation policy must not be hard-coded in browser defaults.');
}
for (const value of ['app_metadata', "alpha_engine_role === 'owner'", 'snapshot.isPro === true', 'getClient']) {
  if (!content.membershipHook.includes(value)) throw new Error(`membership role integration missing: ${value}`);
}
for (const value of [
  "from('product_access_policies')",
  'membership.isOwner',
  'savePolicy',
  'mergeAccessPolicies',
  "['module', 'strategy'].includes(resourceType)",
]) {
  if (!content.accessHook.includes(value)) throw new Error(`Supabase access-policy integration missing: ${value}`);
}
for (const value of ['is a Pro product', 'requires an active AlphaEngine Pro subscription', 'AlphaEngine Pro is not required']) {
  if (!content.gate.includes(value)) throw new Error(`access gate copy missing: ${value}`);
}
if (!content.routes.includes("path: 'securities'") || !content.routes.includes("accessResourceId: 'securities'")) throw new Error('Security Explorer must use configurable module access.');
if (!content.routes.includes("path: 'settings/access'") || !content.routes.includes('ownerOnly: true')) throw new Error('Access settings must stay Owner-only.');
for (const value of ['ACCESS_TIERS', 'access.savePolicy', 'Strategy current operations', 'Product modules', 'type="strategy"', 'Active model']) {
  if (!content.settings.includes(value)) throw new Error(`Owner settings missing: ${value}`);
}
if (content.settings.includes('Model families') || content.settings.includes('type="model"')) {
  throw new Error('Owner settings must not create a model-family access authority.');
}
for (const value of ["requiredTier('strategy', snapshot.strategyId)", 'Live holdings & signals']) {
  if (!content.fleet.includes(value)) throw new Error(`fleet missing runtime strategy access resolution: ${value}`);
}
for (const [label, source] of [['registry', content.registry], ['operations', content.operationsLib], ['fleet', content.fleet]]) {
  if (source.includes('current_operations_access') || source.includes('currentOperationsAccess')) {
    throw new Error(`${label} must not retain a second current-operations access authority.`);
  }
}
for (const [label, source] of [['runs', content.runs], ['compare', content.compare]]) {
  if (source.includes('requiredTierForModel') || source.includes('useAccessControl')) {
    throw new Error(`${label} must keep retained historical evidence independent of current-operation access.`);
  }
}
for (const [label, source] of [['fleet', content.fleet], ['runs', content.runs], ['compare', content.compare]]) {
  if (/isProModelRun|PRO_MODEL_FAMILIES|QQQ Pro|QQQ family/.test(source)) throw new Error(`${label} still binds product tier to QQQ identity.`);
}
for (const value of ['enable row level security', 'to anon, authenticated', "alpha_engine_role') = 'owner'", "('alpha_engine', 'module', 'securities', 'authenticated')"]) {
  if (!content.moduleMigration.toLowerCase().includes(value.toLowerCase())) throw new Error(`base Supabase access migration missing: ${value}`);
}
for (const value of [
  "array['strategy'::text, 'module'::text]",
  "('alpha_engine', 'strategy', 'qqq_rotation', 'pro'",
  "('alpha_engine', 'strategy', 'us_x', 'public'",
  "('alpha_engine', 'strategy', 'cn_x', 'public'",
  "('alpha_engine', 'strategy', 'byd', 'public'",
  'Strategy current operations follow runtime access policy',
  "p.resource_type = 'strategy'",
  "p.resource_id = strategy_operation_snapshots.strategy_id",
  "p.required_tier = 'authenticated'",
  "p.required_tier = 'pro'",
  "p.required_tier = 'owner'",
]) {
  if (!content.strategyMigration.toLowerCase().includes(value.toLowerCase())) throw new Error(`strategy access migration missing: ${value}`);
}
if (content.strategyMigration.includes('required_entitlement text') || content.strategyMigration.includes("resource_type = 'model'")) {
  throw new Error('Generic strategy access migration must not retain per-model or per-snapshot entitlement authority.');
}

const activeSources = [html, ...Object.entries(content).filter(([key]) => !key.toLowerCase().includes('migration')).map(([, source]) => source)].join('\n');
for (const forbidden of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) {
  if (forbidden.test(activeSources)) throw new Error(`browser assets contain forbidden material: ${forbidden}`);
}

console.log('AlphaEngine access contract passed: historical evidence is independent, current strategy operations use stable strategy_id runtime policy, and Owner manages strategy/module tiers through Supabase.');
