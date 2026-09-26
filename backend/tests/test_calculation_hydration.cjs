const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

async function main() {
  const E = {};
  const raw = Array.from({length:1201}, (_, index) => ({
    NIP:String(index + 1).padStart(18, '0'), Nama:`Pegawai ${index}`,
    Tanggal:`${String(index % 28 + 1).padStart(2, '0')}/08/2026`,
    'Jam Masuk':'07:30', 'Jam Pulang':'16:00'
  }));
  let calls = 0;
  const sandbox = {window:{EVKIN:E},console,Date,Math,URL,setTimeout,clearTimeout,
    fetch:async url => {
      const parsed = new URL(String(url));
      assert.equal(parsed.pathname, '/api/workflow/calculation-input');
      assert.equal(parsed.searchParams.get('workflow_id'), 'WORKFLOW-A');
      const page = Number(parsed.searchParams.get('page'));
      const start = (page - 1) * 500;
      calls++;
      return {ok:true,json:async()=>({status:'ok',workflow_id:'WORKFLOW-A',
        import_status:'COMPLETE',expected_source_rows:1201,persisted_source_rows:1201,
        expected_calculation_rows:1201,page,page_size:500,total:1201,total_pages:3,
        rows:raw.slice(start,start + 500)})};
    }};
  for (const name of ['utils','data','state','import','calc','harian']) {
    vm.runInNewContext(fs.readFileSync(`assets/js/${name}.js`, 'utf8'), sandbox);
  }
  E.exportBackend={enabled:true,apiBase:'http://localhost'};
  E.state.workflowMeta={workflow_id:'WORKFLOW-A',total_row_counts:{raw_import:1201,processed_data:0},row_counts:{}};
  E.state.config={...E.defaultConfig(),saved:true,_workflow:{workflow_id:'WORKFLOW-A',
    importStatus:'COMPLETE',importMode:'standard',importStats:{totalRaw:1201,totalRecord:1201,months:['2026-08']}}};
  E.state.importStats={totalRaw:1201,totalRecord:1201,months:['2026-08']};
  E.state.importMode='standard'; E.state.month='2026-08';
  E.lookupWorkflowMaster=async()=>new Map(); E.invalidateFrom=()=>{};
  E.auditMod={logStage(){}}; E.progress=()=>{};
  await E.harianMod.process({sync:false});
  assert.equal(calls,3,'Calculation hydration must walk all 500-row pages');
  assert.equal(E.state.data.length,1201);
  assert.equal(E.state.daily.length,1201,'Every canonical row must reach calc.js');
  assert.equal(E.state.workflowMeta.total_row_counts.processed_data,0);
  console.log('Calculation hydration: 1,201 canonical rows across 3 pages -> 1,201 Harian rows PASS');
}

main().catch(error => { console.error(error); process.exitCode=1; });
