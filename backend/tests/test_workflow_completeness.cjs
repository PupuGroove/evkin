const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function main(){
  const E={};let syncs=0,marks=0;
  const box={window:{EVKIN:E},console,Date,Math,URL,setTimeout,clearTimeout,TextDecoder,
    FileReader:class {readAsArrayBuffer(blob){blob.arrayBuffer().then(result=>this.onload({target:{result}}));}}};
  for(const name of ['utils','data','state','import','import-wali','calc','config','harian','rekap','semifinal'])
    vm.runInNewContext(fs.readFileSync(`assets/js/${name}.js`,'utf8'),box);
  E.syncBackendWorkflow=async()=>{syncs++;};E.auditMod={logStage(){},logDataImport(){}};
  E.lookupWorkflowMaster=async()=>new Map();
  E.exportBackend={enabled:true,markSemifinalVerified:async()=>{marks++;}};
  const headers=['NIP','Nama','Tanggal','Jam Masuk','Jam Pulang'];
  const rows=Array.from({length:35001},(_,i)=>{
    const day=i%21+1, month=day<=11?'08':'09';
    return [String(Math.floor(i/21)+1).padStart(18,'0'),'Pegawai '+Math.floor(i/21),`${String(day).padStart(2,'0')}/${month}/2026`,'07:30','16:30'];
  });
  await E.importMod.processAsync([headers,...rows]);
  assert.equal(syncs,1,'Import must save exactly one complete snapshot');
  assert.equal(E.state.raw.length,35001);assert.equal(E.state.data.length,35001);
  E.state.month='2026-08';await E.harianMod.process({sync:false});
  assert.equal(E.state.daily.length,35001,'All imported months must be computed');
  E.assertDailyCoverage();
  const removed=E.state.daily.pop();
  assert.throws(()=>E.assertDailyCoverage(),/1 record impor belum/);
  E.state.daily.push(removed);E.state.semifinalVerified=true;
  await E.rekapMod.process({sync:false});
  assert.equal(E.state.rekap.reduce((s,r)=>s+r.jumlahRecord,0),35001);
  assert.equal(E.state.rekap.length,3334);
  assert.equal(new Set(E.state.rekap.map(r=>r.nip+'|'+r.bulan)).size,3334);
  assert.equal(new Set(E.state.rekap.map(r=>r.bulan)).size,2);
  // Exercise the actual verification handler and Rekap controls without writing to a live database.
  const nodes=new Map();
  const el={innerHTML:'',querySelectorAll:()=>[],querySelector:key=>{
    if(!nodes.has(key))nodes.set(key,{disabled:false,value:'',focus(){},setSelectionRange(){}});
    return nodes.get(key);
  }};
  E.toast=()=>{};E.go=()=>{};
  E.semifinalMod.render(el);
  const syncBeforeVerify=syncs;
  await nodes.get('#verify').onclick();
  assert.equal(E.state.semifinal.length,35001);
  assert.equal(syncs,syncBeforeVerify,'Verification without edits must not resend the full workflow');
  assert.equal(marks,1,'Verification must use the lightweight backend marker');
  E.rekapMod.render(el);
  assert.ok(el.innerHTML.includes('Direkap: <b>35001</b>'));
  assert.ok(el.innerHTML.includes('rekapMonthFilter'));
  nodes.get('#rekapNipSearch').oninput({target:{value:'not-found'}});
  assert.ok(el.innerHTML.includes('Tidak ada SDM yang sesuai'));
  assert.ok(el.innerHTML.includes('Data 0–0'));
  E.state.final=[{nip:'001',bulan:'2026-08',tukin:2000000}];
  const finalBefore=JSON.stringify(E.state.final),syncBefore=syncs;
  assert.equal(E.stepUnlocked('rekap'),true);
  E.rekapMod.render(el);
  assert.equal(JSON.stringify(E.state.final),finalBefore,'Reopening Rekap must preserve Final');
  assert.equal(syncs,syncBefore,'Viewing Rekap must not save or recalculate');
  E.state.semifinalVerified=false;E.state.dailyComplete=false;E.state.rekap=[];
  assert.equal(E.stepUnlocked('rekap'),true);
  E.rekapMod.render(el);
  assert.ok(el.innerHTML.includes('Belum ada hasil Rekap SDM yang valid'));
  assert.ok(el.innerHTML.includes('data-testid="rekap-run" disabled'));
  await assert.rejects(E.rekapMod.process({sync:false}),/Verifikasi/);
  // A valid Wali date with both punches empty must not silently disappear.
  const wh=['nip','nmpeg','tgl_finger','absen_pagi','absen_sore','jabatan','jnshadir','nmjabatan'];
  await E.waliImportMod.processAoa([wh,['001','Pegawai','03/08/2026','','','Wali Asuh','Bekerja di Kantor','Wali Asuh']]);
  assert.equal(E.state.raw.length,1);assert.equal(E.state.data.length,1);
  assert.equal(E.state.data[0].masukMin,null);assert.equal(E.state.data[0].pulangMin,null);
  await E.harianMod.process({sync:false});assert.equal(E.state.daily.length,1);
  const csv=[wh.join(','),...Array.from({length:1205},(_,i)=>[String(i+1).padStart(18,'0'),'Pegawai','03/08/2026','07:30','16:00','Wali Asuh','Bekerja di Kantor','Wali Asuh'].join(','))].join('\n');
  const blob=new Blob([csv]);
  await E.waliImportMod.processFile({name:'test.csv',size:blob.size,slice:(a,b)=>blob.slice(a,b)});
  assert.equal(E.state.raw.length,1205,'CSV raw source must not be truncated to 1,000 rows');
  assert.equal(E.state.data.length,1205);
  E.syncBackendWorkflow=async()=>{throw new Error('Storage unavailable');};
  await assert.rejects(E.importMod.processAsync([headers,...rows.slice(0,2)]),/Storage unavailable/);
  assert.ok(E.state.workflowLoadError.includes('belum tersimpan lengkap'));
  console.log('35,001 imports -> all-month daily -> 3,334 NIP/month recap; missing record gate; empty Wali punches: PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
