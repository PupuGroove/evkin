/* Backend-owned, versioned Final Tukin; attendance workflow remains independent. */
(function () {
  'use strict';
  const E = window.EVKIN;
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = v => v == null ? '—' : new Intl.NumberFormat('id-ID').format(v);
  const amountFields=new Set(['tukin_bruto','komponen_absen_30','potongan_absen_rp','komponen_skp_70','potongan_skp_rp','total_potongan','tukin_dibayar']);
  let root, period = '', mode = 'ABSENSI_ONLY', source = 'ASSESSMENT', batch = '', preview = null;
  let uploaded, importPreview, selectedSheet = '', headerRow = -1, mapping = null, importType = 'TEMPLATE_IMPORT';
  let importBatches = [], resultBatches = [], result = null, offset = 0;
  let resultPeriod='', resultMode='';
  const fields = ['nip','nama','periode','tahun','predikat_skp','potongan_skp_percent','reviewer','status_laporan','target','realisasi','rekomendasi','notes','evidence'];
  const cols = ['nip','nama','provinsi','kabupaten_kota','kecamatan','jabatan','periode','tukin_bruto','komponen_absen_30',
    'potongan_absen_percent','potongan_absen_rp','predikat_skp','komponen_skp_70','potongan_skp_percent','potongan_skp_rp',
    'total_potongan','tukin_dibayar','mode','skp_source','status','reason','tukin_bruto_source','warning'];
  const labels = {nip:'NIP',nama:'Nama',provinsi:'Provinsi',kabupaten_kota:'Kabupaten/Kota',kecamatan:'Kecamatan',jabatan:'Jabatan',periode:'Periode',
    tukin_bruto:'Tukin Bruto',komponen_absen_30:'Komponen Kehadiran 30%',potongan_absen_percent:'Potongan Absensi %',potongan_absen_rp:'Potongan Absensi Rp',
    predikat_skp:'Predikat SKP',komponen_skp_70:'Komponen Kinerja 70%',potongan_skp_percent:'Potongan SKP %',potongan_skp_rp:'Potongan SKP Rp',
    total_potongan:'Total Potongan',tukin_dibayar:'Tukin Dibayar',mode:'Mode',skp_source:'Sumber SKP',status:'Status',reason:'Alasan',tukin_bruto_source:'Sumber Bruto',warning:'Peringatan'};
  const url = p => new URL('/api/final-tukin'+p,E.exportBackend?.apiBase || location.origin).toString();
  async function api(p, data) {
    const response = await fetch(url(p),data === undefined ? {} : data instanceof FormData ? {method:'POST',body:data} :
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    if (!response.ok) { let error; try { error = await response.json(); } catch (_) {} throw new Error(error?.detail || response.statusText); }
    return response.json();
  }
  async function action(fn) {
    const buttons = [...root.querySelectorAll('button')].map(b=>[b,b.disabled]); buttons.forEach(([b])=>b.disabled=true);
    try { await fn(); } catch(e) { E.toast(String(e.message),'error'); }
    finally { buttons.forEach(([b,disabled])=>{if(b.isConnected)b.disabled=disabled;}); }
  }
  const payload = () => ({periode:period,mode,...(mode==='ABSENSI_SKP'?{source_type:source,skp_batch_id:source==='ASSESSMENT'?null:batch}:{})});
  const options = (items,value) => items.map(([v,t])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(t)}</option>`).join('');
  function stats(data) { return `<div class="ft-stats">${Object.entries(data).map(([k,v])=>`<div><small>${esc(k.replaceAll('_',' '))}</small><strong>${esc(money(v))}</strong></div>`).join('')}</div>`; }
  function table(rows, target, page = 0) {
    const slice = rows.slice(page,page+100);
    target.innerHTML = `<p>${money(rows.length)} SDM · baris ${rows.length?page+1:0}–${Math.min(page+100,rows.length)}</p>
      <div style="overflow:auto;max-height:560px"><table class="data-table"><thead><tr>${cols.map(k=>`<th>${labels[k]}</th>`).join('')}</tr></thead>
      <tbody>${slice.map((r,i)=>`<tr data-detail="${i}" tabindex="0" style="cursor:pointer">${cols.map(k=>`<td>${esc(r[k] == null?'—':(amountFields.has(k)?money(r[k]):r[k]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <button data-page="prev" ${page===0?'disabled':''}>Sebelumnya</button> <button data-page="next" ${page+100>=rows.length?'disabled':''}>Berikutnya</button>
      <div data-detail-box></div>`;
    target.querySelectorAll('[data-detail]').forEach(tr=>{
      const show=()=>{
        const row=slice[Number(tr.dataset.detail)];
        target.querySelector('[data-detail-box]').innerHTML=`<div class="card" style="padding:16px;margin-top:16px"><h3>${esc(row.nama)} · ${esc(row.nip)} · ${esc(row.periode)}</h3>
          <p>Tukin Bruto: <b>Rp ${money(row.tukin_bruto)}</b></p>
          <p>ABSENSI · ${esc(row.potongan_absen_percent ?? '—')}% × komponen 30% Rp ${money(row.komponen_absen_30)} = Rp ${money(row.potongan_absen_rp)}</p>
          <p>SKP · ${row.mode==='ABSENSI_ONLY'?'Tidak digunakan pada perhitungan ini.':`${esc(row.predikat_skp || '—')} · ${esc(row.potongan_skp_percent ?? '—')}% × komponen 70% Rp ${money(row.komponen_skp_70)} = Rp ${money(row.potongan_skp_rp)}`}</p>
          <p>Total Potongan: Rp ${money(row.total_potongan)} · <b>Tukin Dibayar: Rp ${money(row.tukin_dibayar)}</b></p>
          <p>${esc(row.status)} ${esc(row.reason)} ${esc(row.warning)}</p></div>`;
      }; tr.onclick=show; tr.onkeydown=e=>{if(e.key==='Enter')show();};
    });
    target.querySelector('[data-page="prev"]').onclick=()=>table(rows,target,Math.max(0,page-100));
    target.querySelector('[data-page="next"]').onclick=()=>table(rows,target,page+100);
  }
  function bindPreview() {
    if (!preview) return;
    const target=root.querySelector('#ft-preview');
    target.innerHTML=`<h3>Rekonsiliasi ${esc(period)} · ${esc(mode)}</h3>${stats(preview.stats)}
      <label>Filter <select id="ft-filter">${options([['','Semua'],['READY','Siap Final'],['HOLD','Hold'],['SKP_NOT_FOUND','SKP Tidak Ditemukan'],['DUPLICATE','Duplikat']],'')}</select></label>
      <button id="ft-problems">Lihat Data Bermasalah</button>
      <p>SDM HOLD disimpan sebagai HOLD tanpa nilai pembayaran. Hanya SDM READY yang difinalisasi.</p>
      <button class="btn btn-primary" id="ft-finalize" ${preview.stats.ready?'':'disabled'}>PROSES FINAL · ${money(preview.stats.ready)} SDM siap</button><div id="ft-table"></div>`;
    const filter=()=>{const v=root.querySelector('#ft-filter').value;table(preview.rows.filter(r=>!v||r.status===v||r.reason.includes(v)),root.querySelector('#ft-table'));};
    root.querySelector('#ft-filter').onchange=filter;
    root.querySelector('#ft-problems').onclick=()=>{root.querySelector('#ft-filter').value='HOLD';filter();};
    root.querySelector('#ft-finalize').onclick=()=>action(async()=>{
      const saved=await api('/finalize',{...payload(),preview_signature:preview.preview_signature});
      preview=null; result=await api('/results/'+saved.calculation_batch_id); resultBatches=await api('/batches');
      E.toast('Final tersimpan permanen · versi '+saved.version,'success'); renderResults();
    }); filter();
  }
  function importForm() {
    const fd=new FormData(); fd.append('file',uploaded); fd.append('periode',period);fd.append('source_type',importType);
    if(selectedSheet)fd.append('sheet',selectedSheet); if(headerRow>=0)fd.append('header_row',headerRow);
    if(mapping!==null)fd.append('mapping',JSON.stringify(mapping));
    fd.append('percent_unit',root.querySelector('#ft-unit')?.value || 'POINTS');
    return fd;
  }
  function showImport() {
    if(source==='TEMPLATE_IMPORT'||source==='EXTERNAL_IMPORT') importType=source;
    root.querySelector('#ft-import').innerHTML=`<div class="card" style="padding:16px"><h3>SKP Opsional · Import & Mapping</h3>
      <p>NIP harus berupa teks 18 digit. Periode diambil dari pilihan Final jika kolom Periode tidak ada.</p>
      <select id="ft-import-type">${options([['TEMPLATE_IMPORT','Template Penilaian SKP'],['EXTERNAL_IMPORT','Hasil Final SKP · langsung Kelola Tukin']],importType)}</select>
      <input id="ft-file" type="file" accept=".xlsx"><label>Satuan angka biasa <select id="ft-unit"><option value="POINTS">5 = 5%</option><option value="FRACTION">0.05 = 5%</option></select></label>
      <p>Sel Excel berformat persen dikenali otomatis. Predikat “-”, “tidak bisa dinilai”, dan “tidak membuat SKP” tetap diimpor sebagai HOLD tanpa potongan 0%.</p><div id="ft-mapping"></div>
      <button id="ft-import-cancel">Batalkan</button></div>`;
    root.querySelector('#ft-import-type').onchange=e=>{importType=e.target.value;importPreview=null;root.querySelector('#ft-mapping').innerHTML='';};
    root.querySelector('#ft-unit').onchange=()=>{importPreview=null;root.querySelector('#ft-mapping').innerHTML='<p>Satuan berubah. Pilih ulang file untuk preview.</p>';};
    root.querySelector('#ft-import-cancel').onclick=()=>{uploaded=null;importPreview=null;root.querySelector('#ft-import').innerHTML='';};
    root.querySelector('#ft-file').onchange=e=>action(async()=>{uploaded=e.target.files[0];if(!uploaded)return;selectedSheet='';headerRow=-1;mapping=null;await inspectImport();});
  }
  async function inspectImport() {
    importPreview=await api('/skp/preview',importForm());selectedSheet=importPreview.sheet;headerRow=importPreview.header_row;mapping=importPreview.mapping;
    const box=root.querySelector('#ft-mapping');
    box.innerHTML=`<p>File: ${esc(importPreview.file)}</p><label>Sheet <select id="ft-sheet">${options(importPreview.sheets.map(s=>[s,s]),selectedSheet)}</select></label>
      <label>Baris Header <input id="ft-header" type="number" min="1" value="${headerRow+1}"></label>
      <div class="ft-mapping">${fields.map(k=>`<label>${esc(k)}<select data-map="${k}">${options([['','Tidak dipetakan'],...importPreview.headers.map((h,i)=>[String(i),`${i+1}: ${h}`])],mapping[k]===undefined?'':String(mapping[k]))}</select></label>`).join('')}</div>
      ${stats(importPreview.stats)}<button id="ft-inspect">Preview Data / Validasi Mapping</button>
      ${importPreview.stats.invalid?`<p><label><input type="checkbox" id="ft-valid-only"> Import hanya ${money(importPreview.stats.jumlah_baris-importPreview.stats.invalid)} baris valid. Kecualikan seluruh ${money(importPreview.stats.invalid)} baris bermasalah, termasuk semua anggota duplikat.</label></p>
        <details><summary>Lihat ${money(importPreview.stats.invalid)} Data Bermasalah</summary><div style="overflow:auto;max-height:260px"><table class="data-table"><tr><th>Baris Excel</th><th>NIP</th><th>Predikat</th><th>Alasan</th></tr>
        ${(importPreview.issues || []).map(r=>`<tr><td>${r.source_row}</td><td>${esc(r.nip)}</td><td>${esc(r.predikat_skp)}</td><td>${esc(r.errors.join(', '))}</td></tr>`).join('')}</table></div></details>`:''}
      <button id="ft-import-save" ${importPreview.stats.invalid||!importPreview.stats.jumlah_baris?'disabled':''}>Import</button>
      <div style="overflow:auto;max-height:260px"><table class="data-table"><tr><th>NIP</th><th>Predikat</th><th>Potongan %</th><th>Validasi</th></tr>
      ${importPreview.rows.slice(0,100).map(r=>`<tr><td>${esc(r.nip)}</td><td>${esc(r.predikat_skp)}</td><td>${esc(r.potongan_skp_percent)}</td><td>${esc(r.errors.join(', '))}</td></tr>`).join('')}</table></div>`;
    let mappingChanged=false;
    const invalidate=()=>{mappingChanged=true;root.querySelector('#ft-import-save').disabled=true;};
    const validOnly=box.querySelector('#ft-valid-only');
    if(validOnly)validOnly.onchange=()=>{root.querySelector('#ft-import-save').disabled=mappingChanged||!validOnly.checked||importPreview.stats.jumlah_baris===importPreview.stats.invalid;};
    box.querySelectorAll('[data-map]').forEach(el=>el.onchange=invalidate);
    root.querySelector('#ft-header').onchange=invalidate;
    root.querySelector('#ft-sheet').onchange=e=>action(async()=>{selectedSheet=e.target.value;headerRow=-1;mapping=null;await inspectImport();});
    root.querySelector('#ft-inspect').onclick=()=>action(async()=>{
      const nextHeader=Number(root.querySelector('#ft-header').value)-1;
      mapping=nextHeader===headerRow?Object.fromEntries([...box.querySelectorAll('[data-map]')].filter(el=>el.value!=='').map(el=>[el.dataset.map,Number(el.value)])):null;
      headerRow=nextHeader;await inspectImport();
    });
    root.querySelector('#ft-import-save').onclick=()=>action(async()=>{
      const fd=importForm();fd.append('preview_signature',importPreview.preview_signature);
      fd.append('valid_only',String(!!root.querySelector('#ft-valid-only')?.checked));
      const saved=await api('/skp/import',fd);batch=saved.import_batch_id;source=importType;
      importBatches=await api('/skp/batches');preview=null;renderFinal();E.toast(`${saved.imported} SKP diimport; ${saved.excluded || 0} baris dikecualikan`,'success');
    });
  }
  function renderFinal() {
    root.innerHTML=`<div class="card ft-screen" style="padding:20px"><h2>Final Tukin</h2>
      <p>Rekap SDM → SKP Opsional → Final Tukin → Hasil Perhitungan → Export</p>
      <label>Periode <input id="ft-period" type="month" value="${esc(period)}"></label>
      <fieldset><legend>Mode Perhitungan</legend>${[['ABSENSI_ONLY','ABSENSI SAJA'],['ABSENSI_SKP','ABSENSI + SKP']].map(([v,t])=>`<label style="margin-right:24px"><input type="radio" name="ft-mode" value="${v}" ${mode===v?'checked':''}> ${t}</label>`).join('')}</fieldset>
      <p>Sumber absensi: Rekap SDM ${esc(period)} yang telah diverifikasi. Tukin Bruto: Master SDM sesuai periode.</p>
      <p>Jika histori bruto periode belum tersedia, Master SDM terkini digunakan seperti workflow lama dan ditandai pada kolom Peringatan.</p>
      ${mode==='ABSENSI_SKP'?`<label>Sumber SKP <select id="ft-source">${options([['ASSESSMENT','Hasil Assessment EVKIN (APPROVED)'],['TEMPLATE_IMPORT','Import Template SKP Tersimpan'],['EXTERNAL_IMPORT','Import SKP Eksternal Tersimpan']],source)}</select></label>
        ${source!=='ASSESSMENT'?`<label>Batch Import <select id="ft-batch">${options([['','Pilih batch'],...importBatches.filter(b=>b.periode===period&&b.source_type===source).map(b=>[b.id,`${b.source_file} · ${b.source_sheet} · ${b.row_count} SDM · ${b.imported_at}`])],batch)}</select></label>`:''}
        <button id="ft-show-import">IMPORT SKP</button><div id="ft-import"></div>`:'<p>SKP: TIDAK DIGUNAKAN. Tidak membutuhkan Assessment, import, maupun approval SKP.</p>'}
      <p><button class="btn btn-primary" id="ft-preview-button">Preview Matching Sebelum Final</button> <button id="ft-show-results">Hasil Perhitungan & Riwayat</button> <button class="btn btn-danger" id="ft-reset-module"><i data-lucide="trash-2"></i> Hapus Data Final Tukin</button></p>
      <div id="ft-preview"></div></div>`;
    root.querySelector('#ft-period').onchange=e=>{period=e.target.value;preview=null;batch='';renderFinal();};
    root.querySelectorAll('[name="ft-mode"]').forEach(el=>el.onchange=()=>{mode=el.value;preview=null;renderFinal();});
    const src=root.querySelector('#ft-source');if(src)src.onchange=e=>{source=e.target.value;batch='';preview=null;renderFinal();};
    const sel=root.querySelector('#ft-batch');if(sel)sel.onchange=e=>{batch=e.target.value;preview=null;root.querySelector('#ft-preview').innerHTML='';};
    const imp=root.querySelector('#ft-show-import');if(imp)imp.onclick=showImport;
    root.querySelector('#ft-preview-button').onclick=()=>action(async()=>{preview=await api('/preview',payload());bindPreview();});
    root.querySelector('#ft-show-results').onclick=()=>action(async()=>{resultBatches=await api('/batches');renderResults();});
    root.querySelector('#ft-reset-module').onclick=()=>action(async()=>{
      await E.resetModuleData('final_tukin', 'Final Tukin', [], async()=>{preview=null;result=null;resultBatches=[];renderFinal();});
    });
    bindPreview();
  }
  function renderResults() {
    root.innerHTML=`<div class="card ft-screen" style="padding:20px"><h2>Hasil Perhitungan · Riwayat Final Tukin</h2>
      <div class="ft-mapping"><label>Filter Periode <select id="ft-result-period">${options([['','Semua periode'],...[...new Set(resultBatches.map(b=>b.periode))].sort().reverse().map(v=>[v,v])],resultPeriod)}</select></label>
      <label>Filter Mode <select id="ft-result-mode">${options([['','Semua mode'],['ABSENSI_ONLY','ABSENSI SAJA'],['ABSENSI_SKP','ABSENSI + SKP']],resultMode)}</select></label></div>
      <button id="ft-back">Buat Versi Final Baru</button><p><label>Batch / Periode / Mode / Versi <select id="ft-results-batch">${options([['','Pilih hasil tersimpan'],...resultBatches.map(b=>[b.id,`${b.periode} · ${b.mode} · V${b.version} · ${b.jumlah_sdm} SDM · ${b.created_at}`])],result?.batch.id || '')}</select></label></p><div id="ft-results-body"></div></div>`;
    const filterBatches=()=>{
      const filtered=resultBatches.filter(b=>(!resultPeriod||b.periode===resultPeriod)&&(!resultMode||b.mode===resultMode));
      if(result&&!filtered.some(b=>b.id===result.batch.id))result=null;
      root.querySelector('#ft-results-batch').innerHTML=options([['','Pilih hasil tersimpan'],...filtered.map(b=>[b.id,`${b.periode} · ${b.mode} · V${b.version} · ${b.jumlah_sdm} SDM · ${b.created_at}`])],result?.batch.id||'');drawResults();
    };
    root.querySelector('#ft-result-period').onchange=e=>{resultPeriod=e.target.value;filterBatches();};
    root.querySelector('#ft-result-mode').onchange=e=>{resultMode=e.target.value;filterBatches();};
    root.querySelector('#ft-back').onclick=()=>action(async()=>{
      period=result?.batch.periode || period || E.state.month || new Date().toISOString().slice(0,7);
      mode=result?.batch.mode || mode;source=result?.batch.skp_source || 'ASSESSMENT';batch=result?.batch.skp_batch_id || '';
      importBatches=await api('/skp/batches');preview=null;renderFinal();
    });
    root.querySelector('#ft-results-batch').onchange=e=>action(async()=>{result=e.target.value?await api('/results/'+e.target.value):null;drawResults();});
    filterBatches();
  }
  function drawResults() {
    const body=root.querySelector('#ft-results-body');if(!result){body.innerHTML='<p>Pilih batch untuk membuka kembali snapshot dari DuckDB.</p>';return;}
    const filters=['provinsi','kabupaten_kota','jabatan','status','predikat_skp','skp_source'];
    body.innerHTML=`${result.source_changed?'<p role="alert">⚠ DATA SUMBER BERUBAH · PERLU FINALISASI ULANG. Angka snapshot lama tetap dipertahankan.</p>':''}
      <p>Final dibuat: ${esc(result.batch.created_at)} · V${result.batch.version} · ${esc(result.batch.mode)}</p>
      <div class="ft-mapping">${filters.map(k=>`<label>${labels[k]}<select data-filter="${k}">${options([['','Semua'],...[...new Set(result.rows.map(r=>String(r[k]??'')))].filter(Boolean).sort().map(v=>[v,v])],'')}</select></label>`).join('')}</div>
      <p><a class="btn" href="${esc(url('/export/'+result.batch.id))}" download>Export Excel · BNBA + Rekap + Metadata</a>
      <button id="ft-archive">Hapus Database Hasil Perhitungan Final</button></p><div id="ft-summary"></div><div id="ft-result-table"></div>`;
    const filter=()=>{
      const criteria=[...body.querySelectorAll('[data-filter]')];const rows=result.rows.filter(r=>criteria.every(el=>!el.value||String(r[el.dataset.filter])===el.value));
      const total={total_sdm:rows.length};['tukin_bruto','potongan_absen_rp','potongan_skp_rp','total_potongan','tukin_dibayar'].forEach(k=>{total[k]=rows.reduce((a,r)=>a+BigInt(r[k]??0),0n);});
      ['FINALIZED','OUTDATED','HOLD'].forEach(k=>total[k]=rows.filter(r=>r.status===k).length);
      ['ABSENSI_ONLY','ABSENSI_SKP'].forEach(k=>total[k]=rows.filter(r=>r.mode===k).length);
      body.querySelector('#ft-summary').innerHTML=stats(total);table(rows,body.querySelector('#ft-result-table'));
    };body.querySelectorAll('[data-filter]').forEach(el=>el.onchange=filter);filter();
    body.querySelector('#ft-archive').onclick=()=>action(async()=>{
      const b=result.batch;
      if(!confirm(`Anda akan mengarsipkan hasil Final:\nPeriode: ${b.periode}\nMode: ${b.mode}\nVersi: ${b.version}\nJumlah: ${b.jumlah_sdm} SDM\n\nTindakan ini tidak menghapus Master SDM, Rekap Absensi, atau Data SKP.\nLanjutkan Hapus Hasil Final?`))return;
      await api('/archive/'+b.id,{confirm:true});result=null;resultBatches=await api('/batches');renderResults();
    });
  }
  E.finalTukinMod={render(el){root=el;period=period||E.state.month||new Date().toISOString().slice(0,7);preview=null;
    root.innerHTML='<p>Memuat Final Tukin…</p>';action(async()=>{importBatches=await api('/skp/batches');renderFinal();});}};
  E.finalTukinResultsMod={render(el){root=el;root.innerHTML='<p>Memuat hasil tersimpan…</p>';action(async()=>{resultBatches=await api('/batches');
    if(result)result=await api('/results/'+result.batch.id);renderResults();});}};
})();
