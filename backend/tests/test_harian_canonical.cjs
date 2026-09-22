const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
async function main() {
  let fail = false;
  const E = {state: {month: '2026-09', data: [{nip: '001', tanggal: {monthKey: '2026-09'}}], daily: []},
    util: {}, calc: {buildContext: () => ({pegByNip: {'001': {nama: 'STALE'}}}),
      computeRecord: (row, ctx) => ({nip: row.nip, nama: ctx.pegByNip[row.nip].nama})},
    lookupWorkflowMaster: async nips => {
      assert.deepEqual(Array.from(nips), ['001']);
      if (fail) throw new Error('Offline');
      return new Map([['001', {nama: 'CANONICAL'}]]);
    }, invalidateFrom() {}, save() {}, auditMod: {logStage() {}}, syncBackendWorkflow: async () => {}};
  vm.runInNewContext(fs.readFileSync('assets/js/harian.js', 'utf8'), {window: {EVKIN: E}, console});
  await E.harianMod.process();
  assert.equal(E.state.daily[0].nama, 'CANONICAL');
  const previous = E.state.daily;
  fail = true;
  await assert.rejects(E.harianMod.process(), /Offline/);
  assert.equal(E.state.daily, previous);
  console.log('Harian uses canonical identity, preserves previous results on lookup failure: PASS');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
