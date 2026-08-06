import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const configPath = resolve(root, 'public/membership-config.js');
const [html, config] = await Promise.all([
  readFile(resolve(root, 'index.html'), 'utf8'),
  readFile(configPath, 'utf8'),
]);
const syntax = spawnSync(process.execPath, ['--check', configPath], { encoding: 'utf8' });
if (syntax.status !== 0) throw new Error(syntax.stderr);

for (const value of [
  'https://liuh886.github.io/admin/shared/account-shell.css?v=1',
  'https://liuh886.github.io/admin/shared/account-shell.js?v=1',
  './membership-config.js',
]) {
  if (!html.includes(value)) throw new Error(`AlphaEngine index is missing ${value}`);
}
for (const value of [
  'window.HaoAccountConfig',
  "productCode: 'alpha_engine'",
  "entitlementCode: 'alpha_engine.pro'",
  'billingEnabled: false',
  'feedbackEnabled: false',
  '高级研究模型与完整归因视图',
  '不构成投资建议或收益承诺',
]) {
  if (!config.includes(value)) throw new Error(`AlphaEngine account config is missing ${value}`);
}
const combined = `${html}\n${config}`;
for (const forbidden of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) {
  if (forbidden.test(combined)) throw new Error(`AlphaEngine browser assets contain forbidden secret material: ${forbidden}`);
}
if (combined.includes('membership-widget.js') || combined.includes('membership-widget.css')) {
  throw new Error('AlphaEngine must not load the retired local membership widget');
}

console.log('AlphaEngine shared account contract passed.');
