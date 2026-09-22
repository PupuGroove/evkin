const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
async function main(){
  const E={};let ok=false,deleteCalls=0;const cleared=[];
  const sandbox={window:{EVKIN:E},console,URL,Date,Math,
    fetch:async(url,options)=>{
      if(String(url).endsWith('/delete-absensi')){
        deleteCalls++;assert.equal(JSON.parse(options.body).confirmation,'HAPUS ABSENSI');
        return {ok,json:async()=>({detail:'Simulated failure',deleted_rows:7})};
      }
      return {ok:true,json:async()=>({data:{config:null,raw_import:[],daily_data:[],final_absensi:[]}})};
    }};
  for(const name of ['utils','data','state'])vm.runInNewContext(fs.readFileSync(`assets/js/${name}.js`,'utf8'),sandbox);
  E.state.config.saved=true;E.state.config.masterPegawai=[{nip:'MASTER'}];E.state.raw=[{nip:'ABSENSI'}];
  E.exportBackend={enabled:true,apiBase:'http://localhost:8000',syncQueue:Promise.resolve()};
  E.db={replaceStore:async(name,rows)=>{assert.equal(rows.length,0);cleared.push(name);}};
  const before=JSON.stringify(E.state);
  await assert.rejects(E.deleteAbsensiWorkflow(),/Simulated failure/);
  assert.equal(JSON.stringify(E.state),before);assert.equal(E.deletingAbsensi,false);
  let release;E.exportBackend.syncQueue=new Promise(resolve=>{release=resolve;});ok=true;
  const deletion=E.deleteAbsensiWorkflow();await Promise.resolve();
  assert.equal(deleteCalls,1);assert.equal(E.deletingAbsensi,true);
  release();await deletion;
  assert.equal(deleteCalls,2);assert.equal(E.state.raw.length,0);
  assert.equal(E.state.config.saved,false);assert.equal(E.state.config.masterPegawai[0].nip,'MASTER');
  assert.equal(E.deletingAbsensi,false);assert.ok(cleared.includes('raw_import'));assert.ok(!cleared.includes('master_data'));
  console.log('Delete attendance: queued writes, failure preservation, browser cleanup and master preservation PASS');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
