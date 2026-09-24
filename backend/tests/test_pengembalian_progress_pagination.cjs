const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('assets/js/master-pengembalian.js', 'utf8');
const helper = source.match(/const normalizeProgressPage = page => [^;]+;/);
assert.ok(helper, 'progress page normalization helper should exist');
const normalizeProgressPage = vm.runInNewContext(`(${helper[0].replace('const normalizeProgressPage = ', '').replace(/;$/, '')})`);

const progressSize = 50;
let progressPage = 0;
const loadProgress = page => {
  progressPage = normalizeProgressPage(page);
  return progressPage * progressSize;
};

// Normal navigation: first → next → previous.
assert.equal(loadProgress(0), 0);
assert.equal(progressPage, 0);
assert.equal(loadProgress(progressPage + 1), 50);
assert.equal(progressPage, 1);
assert.equal(loadProgress(progressPage - 1), 0);
assert.equal(progressPage, 0);

// Filter refresh on an old page must reset state and request offset to page one.
progressPage = 2;
assert.equal(loadProgress(0), 0);
assert.equal(progressPage, 0);

// Invalid requests must never produce a negative offset.
assert.equal(loadProgress(-3), 0);
assert.equal(progressPage, 0);
assert.equal(loadProgress('not-a-page'), 0);
assert.equal(progressPage, 0);

assert.match(source, /const loadProgress = async page => \{progressPage=normalizeProgressPage\(page\);/);
assert.match(source, /p\.set\('offset',progressPage\*progressSize\)/);
assert.match(source, /aria-label="Bank Payroll"/);
assert.match(source, /<th>Bank Transaksi<\/th>/);

console.log('Return progress pagination stays synchronized across navigation and filter resets: PASS');
