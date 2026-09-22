const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {webcrypto, createHash} = require('node:crypto');
async function main() {
  const requests = [];
  let fail = false;
  const E = {};
  vm.runInNewContext(fs.readFileSync('assets/js/export-backend.js', 'utf8'), {
    window: {EVKIN:E}, URL, AbortSignal, TextEncoder, crypto:webcrypto, console,
    fetch: async (url, options) => {
      requests.push({url:String(url), body:JSON.parse(options.body)});
      return {ok:!fail, json:async()=>({status:'ok'}), text:async()=> 'Database unavailable'};
    }
  });
  const backend = E.exportBackend;
  const rows = [{nip:'001234567890123456', tukin:100, nominal:10, finalDibayar:90}];
  const manifest = await backend.finalManifest(rows);
  assert.equal(manifest.sha256, createHash('sha256').update('["001234567890123456","100","10","90"]').digest('hex'));
  assert.equal(manifest.paid, '90');
  await assert.rejects(backend.finalManifest([{...rows[0],tukin:null}]));
  const data = {final_absensi:rows, final_skp:[], final_kombinasi:[], final_combined_skp:[]};
  await backend.syncWorkflow(data);
  assert.equal(requests.length, 1);
  assert.ok(requests[0].url.endsWith('/api/workflow/sync'));
  assert.deepEqual(requests[0].body, data);
  fail = true;
  await assert.rejects(backend.syncWorkflow(data));
  fail = false;
  await backend.syncWorkflow(data);
  await backend.createExportJob({bulan:'2026-09',expectedFinal:manifest});
  assert.deepEqual(requests.at(-1).body.expected_final, JSON.parse(JSON.stringify(manifest)));
  const full={processed_data:Array.from({length:35001},(_,i)=>({record:JSON.stringify({nip:String(i)})})),daily_data:[]};
  const requestCount=requests.length;
  await backend.syncWorkflow(full);
  assert.equal(requests.length,requestCount+1);
  assert.equal(requests.at(-1).body.processed_data.length,35001);
  assert.ok(requests.at(-1).url.endsWith('/api/workflow/sync'));
  // Mutating caller data after enqueue must not change an earlier snapshot.
  let release;backend.syncQueue=new Promise(resolve=>{release=resolve;});
  const input={raw_import:[{nip:'FIRST'}]};const write=backend.syncWorkflow(input);
  input.raw_import[0].nip='LATER';release();await write;
  assert.equal(requests.at(-1).body.raw_import[0].nip,'FIRST');
  console.log('Manifest, atomic Final sync, failure/retry and export validation payload: PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
