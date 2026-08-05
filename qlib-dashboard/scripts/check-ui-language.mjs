import { readFile, readdir } from 'node:fs/promises';
import { extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const sourceRoot = resolve(root, 'src');
const hanPattern = /[\u3400-\u4dbf\u4e00-\u9fff]/u;

async function collect(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await collect(path));
    else if (['.ts', '.tsx'].includes(extname(entry.name))) files.push(path);
  }
  return files;
}

const shellFiles = [
  resolve(sourceRoot, 'App.tsx'),
  resolve(sourceRoot, 'routes.ts'),
  ...await collect(resolve(sourceRoot, 'components')),
  ...await collect(resolve(sourceRoot, 'pages')),
];

const leaks = [];
for (const file of shellFiles) {
  const source = await readFile(file, 'utf8');
  source.split('\n').forEach((line, index) => {
    if (hanPattern.test(line) && !line.includes('i18n-allow-source-language')) {
      leaks.push(`${relative(root, file)}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (leaks.length) {
  throw new Error([
    'Chinese characters were found in the English application shell.',
    'Research artifacts may retain their source language, but UI copy must stay English until a complete locale is implemented.',
    ...leaks,
  ].join('\n'));
}

const index = await readFile(resolve(root, 'index.html'), 'utf8');
if (!index.includes('<html lang="en">')) throw new Error('index.html must declare the English UI language.');

const manifest = JSON.parse(await readFile(resolve(root, 'public/manifest.webmanifest'), 'utf8'));
if (manifest.lang !== 'en') throw new Error('PWA manifest must declare lang=en for the current application shell.');

const languageModule = await readFile(resolve(sourceRoot, 'lib/ui-language.ts'), 'utf8');
for (const contract of ['ALPHA_ENGINE_UI_LANGUAGE', "document.documentElement.lang = ALPHA_ENGINE_UI_LANGUAGE", 'Research artifacts may retain their source language']) {
  if (!languageModule.includes(contract)) throw new Error(`UI language module is missing contract: ${contract}`);
}

console.log(`Alpha Engine UI language contract passed across ${shellFiles.length} shell files.`);
