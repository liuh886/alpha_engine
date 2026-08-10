import { access, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const files = {
  config: resolve(root, 'public/membership-config.js'),
  styles: resolve(root, 'public/account-integration.css'),
  app: resolve(root, 'src/App.tsx'),
  accessRules: resolve(root, 'src/lib/model-access.ts'),
  membershipHook: resolve(root, 'src/hooks/useAlphaMembership.ts'),
  accessHook: resolve(root, 'src/hooks/useAccessControl.tsx'),
  fleet: resolve(root, 'src/components/StrategyFleet.tsx'),
  gate: resolve(root, 'src/components/AccessGate.tsx'),
  routes: resolve(root, 'src/routes.ts'),
  settings: resolve(root, 'src/pages/AccessSettingsPage.tsx'),
  runs: resolve(root, 'src/pages/RunsPage.tsx'),
  compare: resolve(root, 'src/pages/ComparePage.tsx'),
  migration: resolve(root, '../supabase/migrations/20260809070851_alpha_engine_access_control.sql'),
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
  'AlphaEngine Pro 解锁高级模型、完整回测、归因与研究证据',
  '访问 Pro 高级模型与模块',
  '查看完整回测、归因与研究证据',
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
for (const value of ['AccessControlProvider', 'AccessGate', 'requiredTierForModel', 'accessResourceId', "ownerOnly\n    ? 'owner'"]) {
  if (!content.app.includes(value)) throw new Error(`research shell missing policy-driven access: ${value}`);
}
for (const value of ["export type AccessTier = 'public' | 'authenticated' | 'pro' | 'owner'", 'DEFAULT_ACCESS_POLICIES', "resourceId: 'qqq_rotation'", "resourceId: 'securities'", 'resolveRequiredTier']) {
  if (!content.accessRules.includes(value)) throw new Error(`access policy contract missing: ${value}`);
}
for (const value of ['app_metadata', "alpha_engine_role === 'owner'", 'snapshot.isPro === true', 'getClient']) {
  if (!content.membershipHook.includes(value)) throw new Error(`membership role integration missing: ${value}`);
}
for (const value of ["from('product_access_policies')", 'membership.isOwner', 'savePolicy', 'mergeAccessPolicies']) {
  if (!content.accessHook.includes(value)) throw new Error(`Supabase access policy integration missing: ${value}`);
}
for (const value of ['is a Pro product', 'requires an active AlphaEngine Pro subscription', 'AlphaEngine Pro is not required']) {
  if (!content.gate.includes(value)) throw new Error(`access gate copy missing: ${value}`);
}
if (!content.routes.includes("path: 'securities'") || !content.routes.includes("accessResourceId: 'securities'")) throw new Error('Security Explorer must use configurable module access.');
if (!content.routes.includes("path: 'settings/access'") || !content.routes.includes('ownerOnly: true')) throw new Error('Access settings must stay Owner-only.');
for (const value of ['ACCESS_TIERS', 'access.savePolicy', 'Model families', 'Product modules']) {
  if (!content.settings.includes(value)) throw new Error(`Owner settings missing: ${value}`);
}
for (const [label, source] of [['fleet', content.fleet], ['runs', content.runs], ['compare', content.compare]]) {
  if (!source.includes('requiredTierForModel') || !source.includes('Pro product') && label !== 'compare') throw new Error(`${label} missing policy-driven model access.`);
  if (/isProModelRun|PRO_MODEL_FAMILIES|QQQ Pro|QQQ family/.test(source)) throw new Error(`${label} still binds product tier to QQQ identity.`);
}
for (const value of ['enable row level security', 'to anon, authenticated', "alpha_engine_role') = 'owner'", "('alpha_engine', 'model', 'qqq_rotation', 'pro')", "('alpha_engine', 'module', 'securities', 'authenticated')"]) {
  if (!content.migration.toLowerCase().includes(value.toLowerCase())) throw new Error(`Supabase migration missing: ${value}`);
}

const combined = `${html}\n${Object.values(content).join('\n')}`;
for (const forbidden of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) {
  if (forbidden.test(combined)) throw new Error(`browser assets contain forbidden material: ${forbidden}`);
}

console.log('AlphaEngine access contract passed: public account copy is user-facing while internal access policy remains enforced separately.');
