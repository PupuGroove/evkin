const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  const calls = [];
  const store = new Map();
  let cleanedUrl = null;
  const fakeFetch = async (input, options = {}) => {
    calls.push({ url: String(input), headers: options.headers });
    return { ok: true, status: 200, json: async () => ({ status: 'ok' }) };
  };
  const location = {
    href: 'http://127.0.0.1:8000/#evkin-api-key=browser-test-key',
    origin: 'http://127.0.0.1:8000',
    protocol: 'http:',
    pathname: '/',
    search: '',
    hash: '#evkin-api-key=browser-test-key'
  };
  const sandbox = {
    window: { EVKIN: {}, location, open() {} },
    location,
    history: { replaceState(_state, _title, url) { cleanedUrl = url; } },
    sessionStorage: {
      getItem(key) { return store.get(key) || null; },
      setItem(key, value) { store.set(key, value); },
      removeItem(key) { store.delete(key); }
    },
    document: { addEventListener() {} },
    fetch: fakeFetch,
    Headers,
    URL,
    URLSearchParams,
    AbortSignal,
    AbortController,
    setTimeout,
    clearTimeout,
    console
  };
  vm.runInNewContext(fs.readFileSync('assets/js/export-backend.js', 'utf8'), sandbox);

  assert.equal(sandbox.window.EVKIN.exportBackend.getApiKey(), 'browser-test-key');
  assert.equal(cleanedUrl, '/');
  await sandbox.fetch('http://127.0.0.1:8000/api/workflow/state', { method: 'GET' });
  await sandbox.fetch('https://attacker.invalid/collect', { method: 'GET' });
  assert.equal(calls[0].headers.get('X-EVKIN-API-Key'), 'browser-test-key');
  assert.equal(calls[1].headers, undefined);
  console.log('Frontend local API token injection and foreign-origin non-disclosure: PASS');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
