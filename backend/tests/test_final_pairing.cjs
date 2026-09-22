const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  const S = {config: {masterPegawai: []}, month: '2026-09', rekap: [
    {nip: '0002', total: 10}, {nip: 'MISSING', total: 20}
  ], final: [], finalPage: 0};
  let calls = 0;
  let fail = false;
  const E = {state: S, util: {esc: String, monthLabel: String, fmtRupiah: String}, calc: {},
    stepUnlocked: () => true, exportBackend: {enabled: true, apiBase: 'http://localhost:8000'}, toast() {}};
  const elements = new Map();
  const el = {innerHTML: '', querySelectorAll: () => [], querySelector: key => {
    if (!elements.has(key)) elements.set(key, {});
    return elements.get(key);
  }};
  vm.runInNewContext(fs.readFileSync('assets/js/final.js', 'utf8'), {
    window: {EVKIN: E}, document: {body: {dataset: {page: 'final'}}}, URL, AbortSignal, console,
    fetch: async (url, options) => {
      calls++;
      assert.ok(String(url).endsWith('/api/shared-master/lookup-tukin'));
      assert.deepEqual(JSON.parse(options.body).nips, S.rekap.map(r => r.nip));
      if (fail) throw new Error('Offline');
      return {ok: true, json: async () => ({rows: [{nip: '0002', tukin: 2000000, nama: 'Nama kanonis', jabatan: 'Jabatan kanonis'}]})};
    }
  });
  const flush = () => new Promise(resolve => setImmediate(resolve));
  E.finalMod.render(el);
  await flush();
  assert.equal(calls, 1);
  assert.equal(S.final.length, 2);
  assert.equal(S.final[0].tukin, 2000000);
  assert.equal(S.final[0].nama, 'Nama kanonis');
  assert.equal(S.final[0].jabatan, 'Jabatan kanonis');
  assert.equal(S.final[0].nominal, 60000);
  assert.equal(S.final[1].tukin, null);
  assert.ok(el.innerHTML.includes('Final Absensi'));
  let navigation = '';
  E.go = page => { navigation = page; };
  E.syncBackendWorkflow = async (progress, options) => {
    assert.equal(options.finalOnly, true);
    progress('final_absensi', 1, 1);
  };
  await elements.get('#exportPairedFinal').onclick();
  assert.equal(navigation, ''); // Missing Tukin must explain the block.
  assert.ok(elements.get('#finalExportStatus').textContent.includes('MISSING'));
  assert.equal(S.config.masterPegawai.length, 0);
  // A new workflow subset must be paired even after an earlier successful load.
  S.rekap = [{nip: '0002', total: 0}];
  E.finalMod.render(el);
  await flush();
  assert.equal(S.final.length, 1);
  assert.equal(S.final[0].nominal, 0);
  await elements.get('#exportPairedFinal').onclick();
  assert.equal(navigation, 'export');
  navigation = '';
  E.syncBackendWorkflow = async () => { throw new Error('Database terkunci'); };
  await elements.get('#exportPairedFinal').onclick();
  assert.equal(navigation, '');
  assert.equal(elements.get('#exportPairedFinal').disabled, false);
  assert.ok(elements.get('#finalExportStatus').textContent.includes('Database terkunci'));
  fail = true;
  E.finalMod.render(el);
  await flush();
  assert.ok(el.innerHTML.includes('Coba lagi'));
  assert.equal(calls, 3);
  fail = false;
  elements.get('#retryFinalMaster').onclick();
  await flush();
  assert.equal(calls, 4);
  assert.ok(el.innerHTML.includes('Final Absensi'));
  console.log('Final pairing: subset, missing NIP, recalculation, workflow change, retry PASS');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
