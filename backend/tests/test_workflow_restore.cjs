const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
async function main() {
  let payload;
  const E = {};
  let ok = true;
  const sandbox = {window:{EVKIN:E},console,Date,Math,URL,setTimeout,clearTimeout,
    document:{addEventListener(){},getElementById(){return null},body:{appendChild(){}},
      createElement(){return {setAttribute(){},remove(){},classList:{add(){},remove(){},contains(){return false}}}}},
    fetch:async(url,options)=>{
      if(String(url).endsWith('/module-reset/workflow_results/preview')) return {ok:true,json:async()=>({preview_token:'preview',confirmation:'RESET WORKFLOW RESULTS'})};
      if(String(url).endsWith('/module-reset/workflow_results')) return {ok,json:async()=>ok?({deleted_rows:1}):({detail:'Reset workflow gagal'})};
      const parsed=new URL(String(url));
      if(parsed.pathname==='/api/workflow/state') {
        const counts={};for(const [key,value] of Object.entries(payload||{})) if(Array.isArray(value)) counts[key]=value.length;
        return {ok:true,json:async()=>({data:{config:payload&&payload.config},meta:{workflow_id:'default',periode:payload&&payload.config&&payload.config._workflow&&payload.config._workflow.month,row_counts:counts,total_row_counts:counts}})};
      }
      if(parsed.pathname==='/api/workflow/calculation-input') {
        const rows=Array.isArray(payload&&payload.raw_import)?payload.raw_import:[];
        const page=Number(parsed.searchParams.get('page')||1),perPage=Number(parsed.searchParams.get('page_size')||500);
        const expected=Number(payload&&payload.config&&payload.config._workflow&&payload.config._workflow.importStats&&payload.config._workflow.importStats.totalRecord||rows.length);
        return {ok:true,json:async()=>({workflow_id:'default',import_status:'COMPLETE',
          expected_source_rows:rows.length,persisted_source_rows:rows.length,expected_calculation_rows:expected,
          rows:rows.slice((page-1)*perPage,page*perPage),page,page_size:perPage,total:rows.length,total_pages:Math.ceil(rows.length/perPage)})};
      }
      if(parsed.pathname.startsWith('/api/workflow/data/')) {
        const source=decodeURIComponent(parsed.pathname.split('/').pop());const rows=source==='config'&&payload&&payload.config?[payload.config]:(Array.isArray(payload&&payload[source])?payload[source]:[]);
        const page=Number(parsed.searchParams.get('page')||1),perPage=Number(parsed.searchParams.get('per_page')||100);
        return {ok:true,json:async()=>({rows:rows.slice((page-1)*perPage,page*perPage),total:rows.length,page,per_page:perPage,total_pages:Math.ceil(rows.length/perPage)})};
      }
      return {ok:true,json:async()=>({data:payload})};
    }};
  for(const name of ['utils','data','state','import','calc']) vm.runInNewContext(fs.readFileSync(`assets/js/${name}.js`,'utf8'),sandbox);
  E.exportBackend={enabled:true,apiBase:'http://localhost:8000'};
  const raw=[{NIP:'001234567890123456',Nama:'Tes',Tanggal:'03/08/2026','Jam Masuk':'07:30','Jam Pulang':'16:00'}];
  payload={config:{saved:true},raw_import:raw,daily_data:[],processed_data:[]};
  assert.equal(await E.load(),true);
  await E.ensureWorkflowDataForModule('harian');
  await E.ensureWorkflowDataForComputation(['processed_data']);
  assert.equal(E.state.data[0].tanggal.monthKey,'2026-08');
  assert.equal(E.state.month,'2026-08');
  const record=E.state.data[0];
  const result=E.calc.computeRecord(record,E.calc.buildContext(),'original');
  assert.ok(Array.isArray(result.flags));
  assert.equal(result.nip,raw[0].NIP);
  payload={config:{saved:true,_workflow:{month:'2026-08',timeMode:'wib',semifinalVerified:true}},
    daily_data:[result],raw_import:raw,processed_data:[{record:JSON.stringify({...record,deleted:true})}]};
  assert.equal(await E.load(),true);
  await E.ensureWorkflowDataForModule('harian');
  await E.ensureWorkflowDataForComputation(['processed_data']);
  assert.notEqual(E.state.data[0].deleted,true,'Legacy workflow_records JSON must not override canonical raw import');
  assert.equal(E.state.timeMode,'wib');
  assert.equal(E.state.semifinalVerified,false); // A deleted source cannot validate an old daily row.
  E.state.data[0].deleted=false;
  assert.notEqual(E.state.data[0]._id,result._id,'Hydration regenerates the browser-only row id');
  const coverage=E.assertDailyCoverage();
  assert.equal(coverage.expected,1,
    'Persisted daily results must still match canonical input after a refresh');
  assert.equal(coverage.calculated,1);
  E.state.semifinalVerified=true;
  E.state.rekap=[{nip:record.nip,bulan:'2026-08',jumlahRecord:1}];
  vm.runInNewContext(fs.readFileSync('assets/js/app.js','utf8'),sandbox);
  E.state.finalSKP = {enabled:true,rows:[{nip:'001',skpPct:25}]};
  E.state.finalKombinasi = {enabled:true,useApp:false,useEabsensi:true,useEsdm:false,rows:[{nip:'001',eabs:12}]};
  E.state.finalCombinedSKP = {useApp:false,useEabsensi:true,useEsdm:true,
    skpRows:[{nip:'001',skpPct:25}],eabsensiRows:[{nip:'001',pct:12}],esdmRows:[],
    combinedRows:[],absensiProcessed:true};
  E.state.final = [{nip:'001',tukin:2000000,potPct:10}];
  const expected = JSON.stringify([E.state.finalSKP,E.state.finalKombinasi,E.state.finalCombinedSKP]);
  E.exportBackend.syncWorkflow = async data => {payload=JSON.parse(JSON.stringify(data));return {};};
  await E.syncBackendWorkflow();
  E.state.finalSKP = {enabled:false,rows:[]};
  E.state.finalCombinedSKP = {};
  assert.equal(await E.load(),true);
  await E.ensureWorkflowDataForModule('final');
  assert.equal(JSON.stringify([E.state.finalSKP,E.state.finalKombinasi,E.state.finalCombinedSKP]),expected);
  // A failed reset must preserve the visible workflow; a successful reset keeps the canonical master cache.
  E.state.config.masterPegawai = [{nip:'MASTER'}];
  const before = JSON.stringify(E.state);
  ok = false;
  await assert.rejects(E.resetAll(),/Reset workflow gagal/);
  assert.equal(JSON.stringify(E.state),before);
  ok = true;
  payload={config:{saved:true},raw_import:raw};
  await E.resetAll();
  await E.ensureWorkflowDataForModule('harian');
  await E.ensureWorkflowDataForComputation(['processed_data']);
  assert.equal(E.state.data.length,1);
  assert.equal(E.state.config.masterPegawai[0].nip,'MASTER');
  E.state.daily=[{nip:'STALE'}]; E.state.final=[{nip:'STALE'}];
  payload={config:{saved:false}};
  assert.equal(await E.load(),true);
  assert.equal(E.state.daily.length,0);
  assert.equal(E.state.final.length,0);
  assert.equal(E.state.finalSKP.enabled,false);
  payload={config:{saved:true,_workflow:{semifinalVerified:true,
    finalSKP:{enabled:true,rows:[{nip:'STALE'}]},
    finalCombinedSKP:{absensiProcessed:true}}},raw_import:raw,daily_data:[],final_absensi:[]};
  assert.equal(await E.load(),true);
  assert.equal(E.state.semifinalVerified,false);
  assert.equal(E.stepUnlocked('rekap'),true); // Viewing is allowed; calculation still requires verification.
  assert.equal(E.state.finalSKP.enabled,false);
  assert.equal(E.state.finalCombinedSKP.absensiProcessed,false);
  const nextRaw={...raw[0],Tanggal:'04/08/2026'};
  payload={config:{saved:true,_workflow:{importStats:{totalRecord:2},semifinalVerified:true}},
    raw_import:[...raw,nextRaw],processed_data:[{record:JSON.stringify(record)}],daily_data:[result],
    final_absensi:[{nip:record.nip,tukin:2000000}]};
  assert.equal(await E.load(),true);
  await E.ensureWorkflowDataForModule('rekap');
  await E.ensureWorkflowDataForComputation(['processed_data','daily_data']);
  assert.equal(E.state.data.length,2,'Recover the missing suffix of an interrupted old save');
  assert.notEqual(E.state.data[0]._id,record._id,'Canonical raw import is re-normalized instead of reading legacy row JSON');
  assert.equal(E.state.dailyComplete,false);
  assert.equal(E.state.semifinalVerified,false);
  assert.equal(E.state.final.length,0);
  assert.equal(E.stepUnlocked('export'),false);
  console.log('Legacy import restoration, real daily calculation and normalized record roundtrip: PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
