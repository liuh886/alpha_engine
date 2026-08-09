import { access, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const configPath = resolve(root, 'public/membership-config.js');
const stylesPath = resolve(root, 'public/account-integration.css');
const appPath = resolve(root, 'src/App.tsx');
const accessPath = resolve(root, 'src/lib/model-access.ts');
const membershipHookPath = resolve(root, 'src/hooks/useAlphaMembership.ts');
const fleetPath = resolve(root, 'src/components/StrategyFleet.tsx');
const gatePath = resolve(root, 'src/components/ProModelGate.tsx');
const runsPath = resolve(root, 'src/pages/RunsPage.tsx');
const comparePath = resolve(root, 'src/pages/ComparePage.tsx');
await Promise.all([access(configPath), access(stylesPath), access(appPath), access(accessPath), access(membershipHookPath), access(fleetPath), access(gatePath), access(runsPath), access(comparePath)]);

const [html, config, styles, app, accessRules, membershipHook, fleet, gate, runs, compare] = await Promise.all([
  readFile(resolve(root, 'index.html'), 'utf8'),
  readFile(configPath, 'utf8'),
  readFile(stylesPath, 'utf8'),
  readFile(appPath, 'utf8'),
  readFile(accessPath, 'utf8'),
  readFile(membershipHookPath, 'utf8'),
  readFile(fleetPath, 'utf8'),
  readFile(gatePath, 'utf8'),
  readFile(runsPath, 'utf8'),
  readFile(comparePath, 'utf8'),
]);

for (const reference of [
  'https://liuh886.github.io/admin/shared/account-shell.css?v=4',
  'https://liuh886.github.io/admin/shared/account-shell.js?v=4',
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
  'QQQ 系列为 Pro 模型',
  'feedbackEnabled: false',
]) {
  if (!config.includes(value)) throw new Error(`account config missing: ${value}`);
}
for (const value of ['data-account-slot', 'alpha-account-slot', 'research-topbar-actions', 'ProModelGate', 'isProModelRun']) {
  if (!app.includes(value)) throw new Error(`research shell missing account/Pro integration: ${value}`);
}
for (const value of ["PRO_MODEL_FAMILIES = new Set(['qqq_rotation'])", "ALPHA_PRO_ENTITLEMENT = 'alpha_engine.pro'"]) {
  if (!accessRules.includes(value)) throw new Error(`QQQ Pro access rule missing: ${value}`);
}
for (const value of ["window.addEventListener('hao:account-changed'", 'snapshot.isPro === true', 'openAccount']) {
  if (!membershipHook.includes(value)) throw new Error(`Alpha membership hook missing: ${value}`);
}
for (const value of ['isProModelRun(run)', 'AlphaEngine Pro access', 'membership.openAccount()']) {
  if (!fleet.includes(value)) throw new Error(`Strategy fleet missing Pro model treatment: ${value}`);
}
for (const value of ['QQQ strategy details', 'Open Pro access']) {
  if (!gate.includes(value)) throw new Error(`Pro model gate missing: ${value}`);
}
for (const value of ['isProModelRun(run)', 'AlphaEngine Pro model', 'membership.openAccount()']) {
  if (!runs.includes(value)) throw new Error(`Runs catalog missing QQQ Pro treatment: ${value}`);
}
for (const value of ['workspace.runs', '.filter(isProModelRun)', 'accessibleModels', 'QQQ Pro evidence cannot enter Free-tier comparisons']) {
  if (!compare.includes(value)) throw new Error(`Compare view missing QQQ Pro filtering: ${value}`);
}
for (const value of ['.alpha-account-slot .hao-account-trigger', 'box-shadow: none', 'backdrop-filter: none']) {
  if (!styles.includes(value)) throw new Error(`account integration styles missing: ${value}`);
}
if (styles.includes('is-floating')) {
  throw new Error('AlphaEngine must not retain compatibility with the retired floating account state.');
}

const combined = `${html}\n${config}\n${styles}\n${app}\n${accessRules}\n${membershipHook}\n${fleet}\n${gate}\n${runs}\n${compare}`;
for (const forbidden of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) {
  if (forbidden.test(combined)) throw new Error(`browser assets contain forbidden material: ${forbidden}`);
}

console.log('AlphaEngine account and QQQ Pro model access cover strategy, run, detail, and comparison browsing through the shared entitlement boundary.');
