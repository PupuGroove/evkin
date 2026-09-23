const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
async function main() {
  let payload;
  const E = {util:{esc:value=>String(value??'')},state: {config: {masterPegawai: [{nip: 'MASTER'}]}, raw: [{source: true}],
    daily: [{daily: true}], final: [{nip: 'WORKFLOW', tukin: 2000000, komponen: 600000, potPct: 10, nominal: 60000}]},
    exportBackend: {enabled: true, syncWorkflow: async data => {payload = data; return {counts: {}};}}};
  vm.runInNewContext(fs.readFileSync('assets/js/app.js', 'utf8'), {
    window: {EVKIN: E}, document: {addEventListener() {},getElementById(){return null},body:{appendChild(){}},
      createElement(){return {setAttribute(){},remove(){},classList:{add(){},remove(){},contains(){return false}}}}},
    console,setTimeout,clearTimeout
  });
  await E.syncBackendWorkflow(undefined, {finalOnly: true});
  assert.deepEqual(Object.keys(payload).sort(), ['final_absensi','final_combined_skp','final_kombinasi','final_skp']);
  assert.equal(payload.final_absensi[0].nip, 'WORKFLOW');
  await E.syncBackendWorkflow();
  assert.equal(payload.raw_import[0].source, true);
  assert.equal('master_data' in payload, false);
  assert.equal('masterPegawai' in payload.config, false);
  E.state.finalCombinedSKP = {useApp:true,skpRows:[{nip:'WORKFLOW',skpPct:20}]};
  await E.syncBackendWorkflow(undefined,{finalOnly:true});
  assert.equal(payload.final_combined_skp[0].totalPotonganPct,17);
  assert.equal(payload.final_combined_skp[0].totalNominalPotongan,340000);
  assert.equal(payload.final_combined_skp[0].finalDibayarKombinasiSKP,1660000);
  console.log('Final-only sync excludes raw, daily and master; ordinary sync preserved: PASS');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
