const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const EVKIN = {util:{esc:value=>String(value)}};
const sandbox = {window:{EVKIN}, console, URL, Date, Math, setTimeout, clearTimeout};
const source = fs.readFileSync('assets/js/tukin-annual.js', 'utf8');
vm.runInNewContext(source, sandbox);

const actionState = EVKIN.tukinAnnualMod.combinedActionState;
const ready = {
  can_calculate:true,
  can_finalize:false,
  calculation:null
};
assert.equal(actionState(ready, '', '').calculateEnabled, false);
assert.equal(actionState(ready, 'Petugas', '').calculateEnabled, true);

const finalReady = {
  can_calculate:true,
  can_finalize:true,
  calculation:{status:'CALCULATED'}
};
assert.equal(actionState(finalReady, 'Approver', '').finalizeEnabled, false);
assert.equal(actionState(finalReady, '', 'Dokumen').finalizeEnabled, false);
assert.equal(actionState(finalReady, 'Approver', 'Dokumen').finalizeEnabled, true);
assert.equal(actionState({...finalReady, calculation:{status:'STALE'}}, 'Approver', 'Dokumen').finalizeEnabled, false);
assert.match(source, /id="taCombinedSkpStatus"/);
assert.match(source, /SKP Tidak Tersedia/);
assert.match(source, /35% dari komponen kinerja 70%/);
assert.match(source, /taShowMissingSkp/);

console.log('Tukin UI gating: readiness + petugas + alasan + freshness PASS');
