const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const payloads = [
  '<img src=x onerror="window.__evkin_xss=1">',
  '<script>window.__evkin_xss=1</script>',
  '"><svg onload="window.__evkin_xss=1">'
];

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.className = '';
    this.style = { cssText: '' };
    this.listeners = {};
    this._textContent = '';
    this._innerHTML = '';
  }

  set textContent(value) {
    this._textContent = value == null ? '' : String(value);
    this.children = [];
  }

  get textContent() {
    return this._textContent + this.children.map(child => child.textContent).join('');
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    if (payloads.some(payload => this._innerHTML.includes(payload))) {
      throw new Error('Untrusted payload reached innerHTML');
    }
  }

  get innerHTML() { return this._innerHTML; }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  append(...children) { children.forEach(child => this.appendChild(child)); }

  replaceChildren(...children) {
    this.children = [];
    this._textContent = '';
    this.append(...children);
  }

  addEventListener(type, handler) { this.listeners[type] = handler; }
}

function createSandbox() {
  const document = {
    createElement(tagName) { return new FakeNode(tagName); },
    createTextNode(value) {
      const node = new FakeNode('#text');
      node.textContent = value;
      return node;
    }
  };
  const EVKIN = {
    util: {},
    state: { auditLog: [] },
    auditMod: { getStats: () => ({ total: 0, byAction: {} }) },
    exportBackend: { apiBase: 'http://127.0.0.1:8000' },
    jobs: {}
  };
  const sandbox = {
    window: { EVKIN },
    document,
    URL,
    console,
    alert() {},
    fetch: async () => ({ ok: true, json: async () => ({}) })
  };
  vm.runInNewContext(fs.readFileSync('assets/js/job-monitor.js', 'utf8'), sandbox);
  vm.runInNewContext(fs.readFileSync('assets/js/audit-viewer.js', 'utf8'), sandbox);
  return { sandbox, document, EVKIN };
}

function tagsBelow(node) {
  return node.children.flatMap(child => [child.tagName, ...tagsBelow(child)]);
}

function assertPayloadsAreText(root, sandbox, expectedPayloads = payloads) {
  const renderedText = root.textContent;
  expectedPayloads.forEach(payload => assert.ok(renderedText.includes(payload), `payload should be visible as text: ${payload}`));
  const tags = tagsBelow(root);
  assert.equal(tags.includes('IMG'), false);
  assert.equal(tags.includes('SCRIPT'), false);
  assert.equal(tags.includes('SVG'), false);
  assert.equal(sandbox.window.__evkin_xss, undefined);
}

function testJobMonitor() {
  const { sandbox, document, EVKIN } = createSandbox();
  const root = document.createElement('div');
  EVKIN.jobs.renderJobs(root, [{
    id: payloads[0],
    type: payloads[1],
    status: payloads[2],
    progress: 0.5,
    row_count: 1,
    started_at: payloads[0],
    finished_at: payloads[1],
    message: payloads.join(' ')
  }]);
  assert.equal(root.children.length, 1);
  assert.equal(root.children[0].className, 'job-row card small');
  assertPayloadsAreText(root, sandbox);
}

function testAuditViewer() {
  const { sandbox, document, EVKIN } = createSandbox();
  const tbody = document.createElement('tbody');
  EVKIN.auditViewerMod.renderRows(tbody, [{
    timestamp: '2026-01-01T00:00:00Z',
    sessionId: payloads[0],
    action: payloads.join(' '),
    details: { error: payloads[2], metadata: payloads }
  }]);
  assert.equal(tbody.children.length, 1);
  assert.equal(tbody.children[0].tagName, 'TR');
  assert.equal(tbody.children[0].children.length, 4);
  assertPayloadsAreText(tbody, sandbox);

  const stats = document.createElement('div');
  EVKIN.auditViewerMod.renderActionStats(stats, { [payloads[2]]: 1 });
  assert.ok(stats.textContent.includes(payloads[2]));
  assertPayloadsAreText(stats, sandbox, [payloads[2]]);
}

testJobMonitor();
testAuditViewer();
console.log('Stored XSS payloads render as inert text in job monitor and audit viewer: PASS');
