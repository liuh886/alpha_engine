import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const EXPECTED = {
  'account-shell.js': {
    sha256: '5a8bf92b5e54278d6cc3216070c9454ff6119f7cc85e8bf2042c5c45dbf96434',
    bytes: 30169,
  },
  'account-shell.css': {
    sha256: '0e5e57db13d0779ddc8e10f24af03273c8ec58342911f7369708a7b0364502ec',
    bytes: 13155,
  },
};

const html = await readFile(resolve(root, 'index.html'), 'utf8');

// Verify index.html loads local assets, not remote URLs
const remoteUrl = 'liuh886.github.io/admin/shared/account-shell';
if (html.includes(remoteUrl)) {
  throw new Error('index.html must not load remote account-shell assets');
}
if (!html.includes('./account-shell/account-shell.js')) {
  throw new Error('index.html missing local account-shell.js');
}
if (!html.includes('./account-shell/account-shell.css')) {
  throw new Error('index.html missing local account-shell.css');
}

// Verify local asset integrity
for (const [filename, expected] of Object.entries(EXPECTED)) {
  const filePath = resolve(root, 'public/account-shell', filename);
  const data = await readFile(filePath);
  if (data.length !== expected.bytes) {
    throw new Error(`${filename}: expected ${expected.bytes} bytes, got ${data.length}`);
  }
  const hash = createHash('sha256').update(data).digest('hex');
  if (hash !== expected.sha256) {
    throw new Error(`${filename}: SHA256 mismatch — expected ${expected.sha256}, got ${hash}`);
  }
}

// Verify membership config
const configPath = resolve(root, 'public/membership-config.js');
const config = await readFile(configPath, 'utf8');
for (const value of [
  'window.HaoAccountConfig',
  "productCode: 'alpha_engine'",
  "entitlementCode: 'alpha_engine.pro'",
  'billingEnabled: false',
  'feedbackEnabled: false',
]) {
  if (!config.includes(value)) throw new Error(`account config missing: ${value}`);
}

// No secrets in browser assets
const combined = `${html}\n${config}`;
for (const forbidden of [/sk_(live|test)_/, /whsec_/, /sb_secret_/, /service_role/]) {
  if (forbidden.test(combined)) throw new Error(`browser assets contain forbidden material: ${forbidden}`);
}

console.log('Account shell integrity verified — local, hash-bound, no remote dependency.');
