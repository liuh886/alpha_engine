import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const port = Number(process.env.PORT || 43173);
const root = fileURLToPath(new URL('../dist/', import.meta.url));

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

async function serveFile(response, path) {
  const body = await readFile(path);
  response.writeHead(200, {
    'Content-Type': MIME_TYPES[extname(path)] || 'application/octet-stream',
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || '/', `http://${request.headers.host}`);
    if (url.pathname.startsWith('/api/')) {
      response.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' });
      response.end(JSON.stringify({ detail: 'Static artifact runtime has no API.' }));
      return;
    }

    const requested = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\/+/, '');
    const safePath = normalize(requested).replace(/^(\.\.[/\\])+/, '');
    try {
      await serveFile(response, join(root, safePath));
    } catch {
      await serveFile(response, join(root, 'index.html'));
    }
  } catch (error) {
    response.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ detail: error instanceof Error ? error.message : String(error) }));
  }
});

server.listen(port, '127.0.0.1', () => {
  process.stdout.write(`static fixture server listening on http://127.0.0.1:${port}\n`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
