import { access, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const configPath = resolve(root, 'public/membership-config.js');
const stylesPath = resolve(root, 'public/account-integration.css');
const appPath = resolve(root, 'src/App.tsx');
await Promise.all([access(configPath), access(stylesPath), access(appPath)]);

const [html, config, styles, app] = await Promise.all([
  readFile(resolve(root, 'index.html'), 'utf8'),
  readFile(configPath, 'utf8'),
  readFile(stylesPath, 'utf8'),
  readFile(appPath, 'utf8'),
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
  'billingEnabled: false',
  'feedbackEnabled: false',
]) {
  if (!config.includes(value)) throw new Error(`account config missing: ${value}`);
}
for (const value of ['data-account-slot', 'alpha-account-slot', 'research-topbar-actions']) {
  if (!app.includes(value)) throw new Error(`research topbar missing account integration: ${value}`);
}
for (const value of ['.alpha-account-slot .hao-account-trigger', 'box-shadow: none', 'backdrop-filter: none']) {
  if (!styles.includes(value)) throw new Error(`account integration styles missing: ${value}`);
}
if (styles.includes('is-floating')) {
  throw new Error('AlphaEngine must not retain compatibility with the retired floating account state.');
}

const combined = `${html}\n${config}\n${styles}\n${app}`;
for (const forbidden of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) {
  if (forbidden.test(combined)) throw new Error(`browser assets contain forbidden material: ${forbidden}`);
}

console.log('AlphaEngine account uses only the native research-topbar slot and shared Google/GitHub/X Account Shell v4.');