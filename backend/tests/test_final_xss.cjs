const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('assets/js/final.js', 'utf8');
const payloads = [
  '"><img src=x onerror="window.__evkin_xss=1">',
  '123" autofocus onfocus="window.__evkin_xss=1',
  '"><svg onload="window.__evkin_xss=1">'
];

// Dynamic identifiers and values must be assigned as DOM properties after the
// static row template has been parsed. Do not regress to string interpolation.
assert.doesNotMatch(source, /data-(?:tukin|skp|nip)="\$\{/);
assert.doesNotMatch(source, /value="\$\{/);
assert.doesNotMatch(source, /<option value="\$\{/);
assert.match(source, /inp\.dataset\.tukin = String\(f\.nip \?\? ''\)/);
assert.match(source, /inp\.dataset\.skp = String\(f\.nip \?\? ''\)/);
assert.match(source, /inp\.dataset\.nip = String\(f\.nip \?\? ''\)/);
assert.match(source, /inp\.value = safeNumericInputValue\(/);
assert.match(source, /option\.value = String\(month \?\? ''\)/);
assert.match(source, /option\.textContent = U\.monthLabel\(month\)/);
assert.match(source, /querySelector\('#finalMonthLabel'\)\.textContent = U\.monthLabel\(S\.month\)/);

const numericHelper = source.match(/function safeNumericInputValue\(value\) \{[\s\S]*?\n  \}/);
assert.ok(numericHelper, 'numeric input normalization helper should exist');
const normalizeNumber = vm.runInNewContext(`(${numericHelper[0].replace('function safeNumericInputValue', 'function')})`);
assert.equal(normalizeNumber(1250000), '1250000');
assert.equal(normalizeNumber('12.5'), '12.5');
assert.equal(normalizeNumber(null), '');
payloads.forEach(payload => assert.equal(normalizeNumber(payload), ''));

// Property assignment preserves hostile strings as values; it does not parse
// them as markup or create event-handler attributes.
for (const payload of payloads) {
  const fakeInput = { dataset: {}, value: '' };
  fakeInput.dataset.nip = String(payload ?? '');
  assert.equal(fakeInput.dataset.nip, payload);
  assert.equal(Object.prototype.hasOwnProperty.call(fakeInput, 'onfocus'), false);
  assert.equal(Object.prototype.hasOwnProperty.call(fakeInput, 'onerror'), false);
}

console.log('Final dynamic attributes use inert DOM properties: PASS');
