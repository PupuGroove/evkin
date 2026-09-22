(function () {
  const EVKIN = window.EVKIN;
  EVKIN.masterPengembalianMod = {};

  function badge(id) { return `<span class="module-badge">${id}</span>`; }

  EVKIN.masterPengembalianMod.render = function (el) {
    el.innerHTML = `
      <div class="module-head">
        <div>
          <h2>Master Pengembalian</h2>
          <p class="muted">Kelola data final, arsip, rekonsiliasi BPK, dan bukti perhitungan secara terstruktur.</p>
        </div>
        <div>${badge('pengembalian')}</div>
      </div>

      <div class="alert warn" style="margin:8px 0;">
        <strong>Catatan:</strong> Data awal dan penyesuaian disimpan sebagai arsip terpisah. Data awal tidak ditimpa saat penyesuaian diimpor.
      </div>

      <div class="pengembalian-shell">
        <div class="card mp-overview">
          <div class="mp-section-heading"><div><h3>Master Pengembalian Tukin</h3><p class="muted">Pilih menu untuk melihat atau mengelola data.</p></div><div><span class="mp-readonly">ARSIP & CURRENT STATE</span> <button id="mpClearDatabase" class="btn btn-sm btn-danger" type="button">Reset Database Master Pengembalian</button></div></div>
          <div class="pengembalian-summary">
            <div class="pengembalian-stat blue">
              <span class="label">Data tersimpan</span>
              <span class="value">Arsip</span>
              <span class="meta">Awal dan penyesuaian terpisah</span>
            </div>
            <div class="pengembalian-stat green">
              <span class="label">Penyimpanan</span>
              <span class="value">Aktif</span>
              <span class="meta">Append-only & traceable</span>
            </div>
            <div class="pengembalian-stat yellow">
              <span class="label">Hasil proses</span>
              <span class="value">Final</span>
              <span class="meta">Data final tersimpan</span>
            </div>
            <div class="pengembalian-stat gray">
              <span class="label">Audit</span>
              <span class="value">Traceable</span>
              <span class="meta">BPK dan sumber data terlacak</span>
            </div>
          </div>

          <div class="mp-menu-label">Menu utama</div><nav class="pengembalian-toolbar" aria-label="Menu Master Pengembalian">
            <button id="mpArchiveDashboard" class="btn btn-primary">Dashboard</button>
            <button id="mpFinal" class="btn btn-secondary">Data Final</button>
            <button id="mpBnbaTrace" class="btn btn-secondary">Pelacakan BNBA</button>
            <button id="mpProgress" class="btn btn-secondary">Progres Pengembalian</button>
            <button id="mpBpkReconciliation" class="btn btn-secondary">Rekonsiliasi BPK</button>
            <button id="mpArchiveList" class="btn btn-secondary">History / Archive</button>
            <button id="mpDailyData" class="btn btn-secondary">Data Dasar Perhitungan</button>
            <button id="mpImportHistory" class="btn btn-secondary">Import Data</button>
            <button id="mpPeriods" class="btn btn-secondary">Periode</button>
            <button id="mpExport" class="btn btn-secondary">Export Data</button>
          </div>
        </div>

        <div id="mpContent" class="card pengembalian-content"></div>
      </div>
    `;

    const defaultPanel = document.getElementById('mpContent');
    document.getElementById('mpProgress').onclick = async function () {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = '<h3>Progress Pengembalian</h3><p class="muted">Memuat kewajiban dan history debit…</p>';
      try {
        if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
        let progressPage = 0, progressCursors = [''];
        const progressSize = 50;
        const money = value => Number(value || 0).toLocaleString('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 });
        cont.innerHTML = `<div class="mp-section-heading"><div><h3>Progress Pengembalian Tukin & Uang Makan</h3><p class="muted">Kewajiban Awal dan Final adalah snapshot Master. Realisasi tersimpan sebagai ledger transaksi terkomit per tahap.</p></div><div><a class="btn btn-secondary" href="${new URL('/pengembalian/archive/progress/template',EVKIN.exportBackend.apiBase)}">Download Template Progress</a> <button id="progressExport" class="btn btn-secondary">Download Tampilan Saat Ini</button> <button id="progressOfficialExport" class="btn btn-secondary">Download Laporan Resmi Terkomit</button> <button id="progressClearDatabase" class="btn btn-sm btn-danger" type="button">Reset Database Progress Pengembalian</button></div></div>
          <div id="progressKpis" class="mp-kpi-grid"></div>
          <div class="mp-filterbar"><select id="progressScopePeriod"><option value="">Periode Master Aktif</option><option value="__ALL__">Konsolidasi Semua Periode</option></select><select id="progressYear"><option value="">Semua Tahun SP2D</option></select><select id="progressBank"><option value="">Semua Bank</option></select><select id="progressProvince"><option value="">Semua Provinsi</option></select><select id="progressCity"><option value="">Semua Kab/Kota</option></select><select id="progressComponent"><option value="">Semua Komponen</option></select><select id="progressStage"><option value="">Semua Tahap</option></select><select id="progressBpkBatch"><option value="">Semua Batch BPK</option></select><button id="progressReset" class="btn btn-secondary" type="button">Reset Filter</button></div>
          <div class="mp-actionbar"><select id="progressMasterPeriod"><option value="">Pilih Periode Master</option></select><input id="progressFile" type="file" accept=".xlsx,.xls,.csv"><button id="progressBaselinePreview" class="btn btn-secondary">Import Baseline / Snapshot</button><button id="progressPreview" class="btn btn-secondary">Import Progress Tahap</button><label><input id="progressIncludeWarnings" type="checkbox"> Sertakan warning</label><button id="progressImport" class="btn btn-primary" disabled>Commit</button></div><div id="progressImportStage" class="muted"></div><div id="progressPreviewResult"></div>
          <div class="mp-tabs"><button class="btn btn-sm btn-secondary progress-tab" data-tab="progress">Progress SDM</button><button class="btn btn-sm btn-secondary progress-tab" data-tab="history">History Debit</button><button class="btn btn-sm btn-secondary progress-tab" data-tab="recaps">Rekap</button><button class="btn btn-sm btn-secondary progress-tab" data-tab="imports">Riwayat Import</button></div><div id="progressResult"></div>`;
        let pendingRows = null, pendingMetadata = null, pendingBatchId = null;
        const params = () => { const p=new URLSearchParams(); [['progressScopePeriod','periode_id'],['progressYear','tahun_sp2d'],['progressBank','bank'],['progressProvince','provinsi'],['progressCity','kabupaten_kota'],['progressComponent','komponen'],['progressStage','tahap'],['progressBpkBatch','batch_bpk']].forEach(([id,key])=>{const v=String(document.getElementById(id).value||'').trim();if(v)p.set(key,v);});if(p.get('tahap'))p.set('stage_mode','single');return p; };
        const componentCells=(row,component,years,stages)=>{const initialCells=years.map(year=>`<td>${money(row.initials?.[component]?.[year]||0)}</td>`).join('');const finalCells=years.map(year=>`<td>${money(row.finals?.[component]?.[year]||0)}</td>`).join('');const stageCells=stages.flatMap(stage=>years.map(year=>{const cell=row.stages?.[component]?.[stage]?.[year];return `<td>${money(cell?.amount||0)}${cell?.ntpn_count?`<br><button class="link-button progress-ntpn" data-nip="${EVKIN.util.esc(row.nip||'')}" data-component="${component}" data-stage="${stage}" data-year="${year}">${cell.ntpn_count} NTPN</button>`:''}</td>`;})).join('');const totalByYear=years.map(year=>Object.values(row.stages?.[component]||{}).reduce((sum,stage)=>sum+Number(stage?.[year]?.amount||0),0));const obligation=Object.values(row.finals?.[component]||{}).reduce((a,b)=>a+Number(b||0),0);const realized=totalByYear.reduce((a,b)=>a+b,0);return initialCells+finalCells+stageCells+totalByYear.map(value=>`<td>${money(value)}</td>`).join('')+`<td>${money(realized)}</td><td>${money(Math.max(obligation-realized,0))}</td><td><span class="module-badge">${EVKIN.util.esc(row['status_'+(component==='TUKIN'?'tukin':'uang_makan')]||'')}</span></td>`;};
        const showProgress = (data,kpi,dashboard={}) => { const rows=data.rows||[],years=(data.years||[]).map(String),stages=(data.stages||[]).map(String),kpiRows=kpi?.rows||[],d=dashboard.kpi||{};document.getElementById('progressKpis').innerHTML=`<div class="muted">Dashboard operasional · ${EVKIN.util.esc(dashboard.scope?.scope_label||kpi?.scope?.scope_label||data.scope?.scope_label||'-')}</div>`+[['Total Kewajiban',d.total_kewajiban],['Total Realisasi Netto',d.total_realisasi_netto],['Total Sisa',d.total_sisa],['Total Kelebihan Bayar',d.total_kelebihan_bayar],['Lunas',d.lunas],['Sebagian',d.sebagian],['Belum',d.belum],['Overpaid',d.overpaid]].map(([label,value])=>`<div class="mp-kpi"><span>${label}</span><strong>${label.includes('Total')?money(value):Number(value||0).toLocaleString('id-ID')}</strong></div>`).join('')+kpiRows.map(s=>`<div class="mp-kpi"><span>SP2D ${s.tahun_sp2d} · Kewajiban Final</span><strong>${money(s.final)}</strong></div>`).join('');
        const loadProgress = async page => {progressPage=Math.max(page,0);const p=params();p.set('limit',progressSize);p.set('offset',progressPage*progressSize);const [res,kpiRes,dashboardRes]=await Promise.all([fetch(new URL('/pengembalian/archive/progress/sdm?'+p,EVKIN.exportBackend.apiBase)),fetch(new URL('/pengembalian/archive/progress/kpi-summary?'+params(),EVKIN.exportBackend.apiBase)),fetch(new URL('/pengembalian/archive/progress/operational-dashboard?'+params(),EVKIN.exportBackend.apiBase))]);const data=await res.json(),kpi=await kpiRes.json(),dashboard=await dashboardRes.json();if(!res.ok||!kpiRes.ok||!dashboardRes.ok)throw new Error(data.detail||kpi.detail||dashboard.detail||'Gagal memuat progress');showProgress(data,kpi,dashboard);};
        };
        const loadProgress = async page => {const p=params();p.set('limit',progressSize);p.set('offset',Math.max(page,0)*progressSize);const [res,kpiRes,dashboardRes]=await Promise.all([fetch(new URL('/pengembalian/archive/progress/sdm?'+p,EVKIN.exportBackend.apiBase)),fetch(new URL('/pengembalian/archive/progress/kpi-summary?'+params(),EVKIN.exportBackend.apiBase)),fetch(new URL('/pengembalian/archive/progress/operational-dashboard?'+params(),EVKIN.exportBackend.apiBase))]);const data=await res.json(),kpi=await kpiRes.json(),dashboard=await dashboardRes.json();if(!res.ok||!kpiRes.ok||!dashboardRes.ok)throw new Error(data.detail||kpi.detail||dashboard.detail||'Gagal memuat progress');showProgress(data,kpi,dashboard);};
        const replaceOptions = (id, values, label) => {
          const select=document.getElementById(id);if(!select)return;
          const current=select.value;
          select.innerHTML=`<option value="">${label}</option>`+(values||[]).map(value=>`<option value="${EVKIN.util.esc(String(value))}">${EVKIN.util.esc(String(value))}</option>`).join('');
          select.value=(values||[]).map(String).includes(String(current))?current:'';
        };
        const loadFilterOptions = async () => {
          const response=await fetch(new URL('/pengembalian/archive/progress/filter-options?'+params(),EVKIN.exportBackend.apiBase));
          const data=await response.json();if(!response.ok)throw new Error(data.detail||'Gagal memuat opsi filter');
          const options=data.options||{};
          replaceOptions('progressYear',options.tahun_sp2d,'Semua Tahun SP2D');
          replaceOptions('progressBank',options.bank,'Semua Bank');
          replaceOptions('progressProvince',options.provinsi,'Semua Provinsi');
          replaceOptions('progressCity',options.kabupaten_kota,'Semua Kab/Kota');
          replaceOptions('progressComponent',options.komponen,'Semua Komponen');
          replaceOptions('progressStage',options.tahap,'Semua Tahap');
          replaceOptions('progressBpkBatch',options.batch_bpk,'Semua Batch BPK');
        };
        const refreshDashboard = async (reloadOptions=true) => {progressCursors=[''];if(reloadOptions)await loadFilterOptions();await loadProgress(0);};
        ['progressScopePeriod','progressYear','progressBank','progressProvince','progressCity','progressComponent','progressStage','progressBpkBatch'].forEach(id=>{
          document.getElementById(id).onchange=()=>refreshDashboard(true);
        });
        document.getElementById('progressReset').onclick=()=>{
          ['progressYear','progressBank','progressProvince','progressCity','progressComponent','progressStage','progressBpkBatch'].forEach(id=>{document.getElementById(id).value='';});
          refreshDashboard(true);
        };
        document.getElementById('progressExport').onclick=()=>window.open(new URL('/pengembalian/archive/progress/download?'+params(),EVKIN.exportBackend.apiBase),'_blank');
        document.getElementById('progressOfficialExport').onclick=()=>{const p=params();p.set('official','true');window.open(new URL('/pengembalian/archive/progress/download?'+p,EVKIN.exportBackend.apiBase),'_blank');};
        document.getElementById('progressClearDatabase').onclick = async function () {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) {
            EVKIN.toast('Backend belum aktif.', 'error');
            return;
          }
          const confirmation = window.prompt(
            'Tindakan ini menghapus seluruh data Progress Pengembalian saja. Ketik RESET PROGRESS PENGEMBALIAN untuk melanjutkan:'
          );
          if (!confirmation) return;
          const normalized = String(confirmation).trim().toUpperCase();
          if (!['HAPUS PROGRES PENGEMBALIAN', 'RESET PROGRESS PENGEMBALIAN'].includes(normalized)) return;
          this.disabled = true;
          try {
            const response = await fetch(new URL('/pengembalian/progress/clear', EVKIN.exportBackend.apiBase), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ confirmation: normalized })
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(result.detail || 'Gagal reset database Progress Pengembalian');
            EVKIN.toast(`Database Progress Pengembalian direset (${result.deleted_rows || 0} baris).`, 'success');
            window.location.reload();
          } catch (error) {
            EVKIN.toast(error.message, 'error');
            this.disabled = false;
          }
        };
        const progressFields = [
          ['NIP', ['nip','nip_sdm','nomor_nip','no_nip'], true],
          ['Nama', ['nama_sdm','nama','nama_pegawai'], false],
          ['Provinsi', ['provinsi','nama_provinsi'], false],
          ['Kab/Kota', ['kab_kota','kabupaten_kota'], false],
          ['Bank', ['nama_bank','bank'], true],
          ['Nomor Rekening', ['nomor_rekening','nomer_rekening','rekening'], false],
          ['Tahun SP2D', ['tahun_sp2d','tahun'], true],
          ['Komponen', ['komponen','komponen_debit'], true],
          ['Tahap', ['tahap','stage'], true],
          ['Nominal Diajukan', ['nominal_diajukan'], true],
          ['Nominal Berhasil', ['nominal_berhasil'], true],
          ['Status', ['status','status_debit'], true],
          ['NTPN', ['ntpn'], false],
          ['Tanggal Proses', ['tanggal_proses','tanggal_debit'], false],
          ['Alasan Gagal', ['alasan_gagal','keterangan_gagal'], false],
          ['Keterangan', ['keterangan'], false]
        ];
        const headerKey = value => String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_|_$/g,'');
        const parseProgressFile = async file => {
          const bytes = new Uint8Array(await file.arrayBuffer());
          const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
          const vendorUrl = new URL('assets/vendor/xlsx.full.min.js', document.baseURI).href;
          try {
            const workerCode = `importScripts(${JSON.stringify(vendorUrl)});onmessage=e=>{try{const wb=XLSX.read(new Uint8Array(e.data),{type:'array',raw:true});const ws=wb.Sheets[wb.SheetNames[0]];const rows=XLSX.utils.sheet_to_json(ws,{defval:'',raw:true});postMessage({rows,headers:rows.length?Object.keys(rows[0]):[]});}catch(error){postMessage({error:error.message});}}`;
            const worker = new Worker(URL.createObjectURL(new Blob([workerCode],{type:'text/javascript'})));
            const result = await new Promise((resolve,reject)=>{worker.onmessage=e=>e.data.error?reject(new Error(e.data.error)):resolve(e.data);worker.onerror=reject;worker.postMessage(bytes.buffer);});
            worker.terminate();
            return {...result,hash};
          } catch (_) {
            const wb=XLSX.read(bytes,{type:'array',raw:true});
            const rows=XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]],{defval:'',raw:true});
            return {rows,headers:rows.length?Object.keys(rows[0]):[],hash};
          }
        };
        fetch(new URL('/pengembalian/periods',EVKIN.exportBackend.apiBase)).then(r=>r.json()).then(data=>{const importSelect=document.getElementById('progressMasterPeriod'),scopeSelect=document.getElementById('progressScopePeriod');if(!importSelect||!scopeSelect)return;(data.rows||[]).forEach(row=>{[importSelect,scopeSelect].forEach(select=>{const option=document.createElement('option');option.value=row.periode_id;option.textContent=`${row.periode_id} — ${row.nama_periode||''}`;select.appendChild(option);});});const active=(data.rows||[]).find(row=>row.is_active);if(active){importSelect.value=active.periode_id;scopeSelect.value=active.periode_id;}refreshDashboard(true);});
        document.getElementById('progressBaselinePreview').onclick=async()=>{
          const file=document.getElementById('progressFile').files[0],period=document.getElementById('progressMasterPeriod').value;
          if(!file)return EVKIN.toast('Pilih workbook baseline','error');if(!period)return EVKIN.toast('Pilih Periode Master','error');
          const stage=document.getElementById('progressImportStage');stage.textContent='UPLOADING · PARSING MANDIRI/BRI/BSI · RECONCILING FINAL';
          const url=new URL('/pengembalian/archive/progress/baseline/preview',EVKIN.exportBackend.apiBase);url.searchParams.set('periode_id',period);url.searchParams.set('filename',file.name);
          const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:file});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Preview baseline gagal');
          pendingBatchId=data.import_batch_id;pendingMetadata={periode_id:period,import_mode:'INITIAL_BASELINE'};document.getElementById('progressIncludeWarnings').checked=true;
          const s=data.statistics||{},i=data.impact||{},sheets=(data.source_adapter?.sheets||[]).map(x=>`${x.sheet}: ${x.transactions||0}`).join('<br>');
          document.getElementById('progressPreviewResult').innerHTML=`${data.file_duplicate?'<div class="alert error">DUPLICATE — file baseline pernah diimport.</div>':''}<div class="alert ${s.invalid?'warn':'success'}"><strong>Preview INITIAL_BASELINE</strong><br>${sheets}<br>NIP ${s.jumlah_nip||0}; transaksi ${s.total||0}; matched Final ${s.matched_final||0}; unmatched Final ${s.unmatched_final||0}; duplicate ${s.duplicate||0}; error ${s.invalid||0}; overpayment ${s.potential_overpayment||0}<br>Total berhasil ${money(s.debit_berhasil||0)} · Proyeksi sisa ${money(i.proyeksi_sisa||0)}</div><a class="btn btn-sm btn-secondary" href="${new URL('/pengembalian/archive/progress/imports/'+encodeURIComponent(pendingBatchId)+'/validation-result',EVKIN.exportBackend.apiBase)}">Download Validation Result</a>`;
          document.getElementById('progressImport').disabled=!(Number(s.valid||0)+Number(s.warning||0))||!!data.file_duplicate;stage.textContent='PREVIEW READY · FINAL BELUM BERUBAH';
        };
        const applyProgressMapping = (rows,mapping) => rows.map(row => {
          const mapped={...row};
          Object.entries(mapping).forEach(([target,source])=>{if(source)mapped[target]=row[source];});
          return mapped;
        });
        const sendProgressPreview = async (rows,metadata) => {
          const stage=document.getElementById('progressImportStage');
          stage.textContent='NORMALIZING · VALIDATING · MATCHING · CHECKING DUPLICATES';
          const res=await fetch(new URL('/pengembalian/archive/progress/preview',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows,metadata})});
          const data=await res.json();if(!res.ok)throw new Error(data.detail||'Preview gagal');
          pendingRows=rows;pendingMetadata=metadata;pendingBatchId=data.import_batch_id;stage.textContent='CALCULATING IMPACT · READY';
          const s=data.statistics,i=data.impact||{};const fileWarning=data.file_duplicate?`<div class="alert error">FILE_ALREADY_IMPORTED — batch ${EVKIN.util.esc(data.file_duplicate.existing_batch_id||'')}</div>`:'';
          const adapterInfo=data.source_adapter?`<div class="alert success"><strong>${EVKIN.util.esc(data.source_adapter.format||'Format terdeteksi')}.</strong> ${Number(data.source_adapter.transaction_rows||0).toLocaleString('id-ID')} transaksi dari sheet bank otoritatif. Sheet ALL SDM dan REKAPITULASI tidak dihitung.</div>`:'';
          document.getElementById('progressPreviewResult').innerHTML=`${fileWarning}${adapterInfo}<div class="alert ${s.invalid||s.needs_review?'warn':'success'}">NIP ${s.jumlah_nip||0}; transaksi ${s.total}; matched Final ${s.matched_final||0}; unmatched Final ${s.unmatched_final||0}; valid ${s.valid}; warning ${s.warning}; error ${s.invalid}; duplikat ${s.duplicate}; overpayment ${s.potential_overpayment}<br>Diajukan ${money(s.total_debit)} · berhasil ${money(s.debit_berhasil)} · gagal ${money(s.debit_gagal)}</div><div class="mp-kpi-grid">${[['Kewajiban sebelum',i.kewajiban_sebelum],['Realisasi sebelum',i.realisasi_sebelum],['Sisa sebelum',i.sisa_sebelum],['Berhasil import',i.nominal_berhasil_import],['Proyeksi realisasi',i.proyeksi_realisasi],['Proyeksi sisa',i.proyeksi_sisa]].map(x=>`<div class="mp-kpi"><span>${x[0]}</span><strong>${money(x[1])}</strong></div>`).join('')}</div><a class="btn btn-sm btn-secondary" href="${new URL('/pengembalian/archive/progress/imports/'+encodeURIComponent(pendingBatchId)+'/validation-result',EVKIN.exportBackend.apiBase)}">Download Validation Result</a><div class="table-wrap"><table class="data-table"><thead><tr><th>Row</th><th>NIP</th><th>SP2D</th><th>Komponen</th><th>Tahap</th><th>Bank</th><th>Diajukan</th><th>Berhasil</th><th>NTPN</th><th>Status</th><th>Matching</th><th>Sisa Proyeksi</th><th>Validasi</th></tr></thead><tbody>${data.rows.slice(0,100).map(r=>`<tr><td>${r.source_row_number}</td><td>${EVKIN.util.esc(r.nip||'')}</td><td>${r.tahun_sp2d||''}</td><td>${EVKIN.util.esc(r.komponen_debit||'')}</td><td>${r.tahap||''}</td><td>${EVKIN.util.esc(r.nama_bank_normalized||'')}</td><td>${money(r.nominal_diajukan)}</td><td>${money(r.nominal_berhasil)}</td><td>${EVKIN.util.esc(r.ntpn||'-')}</td><td>${r.status_debit}</td><td>${r.matching_status}</td><td>${money(r.projected_remaining)}</td><td>${r.classification}: ${EVKIN.util.esc((r.errors||[]).join(', '))}</td></tr>`).join('')}</tbody></table></div>`;
          document.getElementById('progressImport').disabled=!(Number(s.valid||0)+Number(s.warning||0))||!!data.file_duplicate;
        };
        document.getElementById('progressPreview').onclick=async()=>{
          const file=document.getElementById('progressFile').files[0];if(!file)return EVKIN.toast('Pilih file progress','error');
          if(!document.getElementById('progressMasterPeriod').value)return EVKIN.toast('Pilih Periode Master','error');
          const stage=document.getElementById('progressImportStage');stage.textContent='READING FILE';await new Promise(requestAnimationFrame);
          const parsed=await parseProgressFile(file);if(!parsed.rows.length)throw new Error('File tidak memiliki baris data');
          const mapping={};progressFields.forEach(([target,aliases])=>{const header=parsed.headers.find(h=>aliases.includes(headerKey(h)));if(header)mapping[target]=header;});
          const requiredMissing=progressFields.filter(([target,,required])=>required&&!mapping[target]);
          if(requiredMissing.length){
            stage.textContent='COLUMN MAPPING REQUIRED';
            const area=document.getElementById('progressPreviewResult');
            const options=['<option value="">— Tidak dipetakan —</option>',...parsed.headers.map(h=>`<option value="${EVKIN.util.esc(h)}">${EVKIN.util.esc(h)}</option>`)].join('');
            area.innerHTML=`<div class="alert warn">Header file belum dapat dipetakan seluruhnya. Tentukan kolom sumber sebelum preview.</div><div class="mp-detail-grid">${progressFields.map(([target,,required])=>`<label>${target}${required?' *':''}<select class="progress-map" data-target="${target}">${options}</select></label>`).join('')}</div><button id="applyProgressMapping" class="btn btn-primary">Gunakan Mapping & Preview</button>`;
            area.querySelectorAll('.progress-map').forEach(select=>{select.value=mapping[select.dataset.target]||'';});
            document.getElementById('applyProgressMapping').onclick=async()=>{const selected={};area.querySelectorAll('.progress-map').forEach(x=>{if(x.value)selected[x.dataset.target]=x.value;});const missing=progressFields.filter(([target,,required])=>required&&!selected[target]);if(missing.length)return EVKIN.toast('Lengkapi seluruh field wajib','error');await sendProgressPreview(applyProgressMapping(parsed.rows,selected),{filename:file.name,file_hash:parsed.hash,column_mapping:selected,periode_id:document.getElementById('progressMasterPeriod').value,import_mode:'PROGRESS_STAGE_IMPORT'});};
            return;
          }
          await sendProgressPreview(applyProgressMapping(parsed.rows,mapping),{filename:file.name,file_hash:parsed.hash,column_mapping:mapping,periode_id:document.getElementById('progressMasterPeriod').value,import_mode:'PROGRESS_STAGE_IMPORT'});
        };
        document.getElementById('progressImport').onclick = async () => {
          if(!pendingBatchId)return;const includeWarnings=document.getElementById('progressIncludeWarnings').checked;if(includeWarnings&&!confirm('Baris WARNING juga akan disimpan. Lanjutkan?'))return;document.getElementById('progressImportStage').textContent='SAVING · RECALCULATING · RECONCILING';const response = await fetch(new URL('/pengembalian/archive/progress/import', EVKIN.exportBackend.apiBase), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({import_batch_id:pendingBatchId,created_by:'ui',include_warnings:includeWarnings})});
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || 'Import progres gagal');
          document.getElementById('progressImportStage').textContent='COMPLETE · PROGRESS SDM UPDATED';progressCursors=[''];EVKIN.toast(`${result.inserted || 0} transaksi tersimpan. Progress SDM dan sisa piutang sudah dihitung ulang.`, 'success');await loadProgress(0);
        };
        const renderHistory=data=>`<div class="table-wrap"><table class="data-table"><thead><tr><th>Tahap</th><th>Tahun SP2D</th><th>Komponen</th><th>Bank</th><th>Nomor Rekening</th><th>Nominal Diajukan</th><th>Nominal Berhasil</th><th>Status</th><th>NTPN</th><th>Tanggal Proses</th><th>Batch Import</th><th>File / Sheet / Row</th></tr></thead><tbody>${(data.rows||[]).map(r=>`<tr><td>${r.tahap||'-'}</td><td>${r.tahun_sp2d||''}</td><td>${EVKIN.util.esc(r.komponen_debit||'')}</td><td>${EVKIN.util.esc(r.nama_bank_normalized||'-')}</td><td>${EVKIN.util.esc(r.nomor_rekening||'-')}</td><td>${money(r.nominal_diajukan)}</td><td>${money(r.nominal_berhasil)}</td><td>${EVKIN.util.esc(r.status_debit||'')}</td><td>${EVKIN.util.esc(r.ntpn||'-')}</td><td>${EVKIN.util.esc(String(r.tanggal_debit||'-'))}</td><td>${EVKIN.util.esc(r.import_batch_id||'')}</td><td>${EVKIN.util.esc(r.source_filename||'-')}<br>${EVKIN.util.esc(r.source_sheet||'-')} / ${r.source_row_number||'-'}</td></tr>`).join('')||'<tr><td colspan="12">Tidak ada histori.</td></tr>'}</tbody></table></div>`;
        const renderRecaps=data=>{const stage=data.tahap_sp2d||{years:[],rows:[]};const stageTable=`<h4>Rekap Tahap × Tahun SP2D</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>Tahap</th>${stage.years.map(y=>`<th>SP2D ${y}</th>`).join('')}<th>Total</th></tr></thead><tbody>${stage.rows.map(r=>`<tr><td>${r.tahap}</td>${stage.years.map(y=>`<td>${money(r[y]||0)}</td>`).join('')}<td>${money(r.total)}</td></tr>`).join('')||'<tr><td>Tidak ada data.</td></tr>'}</tbody></table></div>`;return stageTable+['provinsi','bank','sp2d','periode'].map(key=>`<h4>Rekap ${key.toUpperCase()}</h4><div class="table-wrap"><table class="data-table"><thead><tr>${Object.keys((data[key]||[])[0]||{}).map(x=>`<th>${EVKIN.util.esc(x)}</th>`).join('')}</tr></thead><tbody>${(data[key]||[]).map(r=>`<tr>${Object.values(r).map(v=>`<td>${typeof v==='number'?Number(v).toLocaleString('id-ID'):EVKIN.util.esc(String(v??''))}</td>`).join('')}</tr>`).join('')||'<tr><td>Tidak ada data.</td></tr>'}</tbody></table></div>`).join('');};
        document.querySelectorAll('.progress-tab').forEach(button=>button.onclick=async()=>{if(button.dataset.tab==='progress')return loadProgress(0);const p=params();p.set('limit','100');const path=button.dataset.tab==='history'?'/pengembalian/archive/progress/transactions?'+p:button.dataset.tab==='imports'?'/pengembalian/archive/progress/import-batches?'+p:'/pengembalian/archive/progress/stage-summary?'+p;const response=await fetch(new URL(path,EVKIN.exportBackend.apiBase));const data=await response.json();if(!response.ok)throw new Error(data.detail||'Gagal memuat data');const area=document.getElementById('progressResult');if(button.dataset.tab==='history'){area.innerHTML=renderHistory(data);return;}if(button.dataset.tab==='recaps'){area.innerHTML=renderRecaps(data);return;}area.innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>Batch</th><th>Mode</th><th>File / Hash</th><th>Rows</th><th>Valid/Warning/Error/Duplicate</th><th>Nominal Berhasil/Gagal</th><th>Status</th><th>Aksi</th></tr></thead><tbody>${(data.rows||[]).map(r=>`<tr><td>${EVKIN.util.esc(r.import_batch_id||'')}</td><td>${EVKIN.util.esc(r.import_mode||'-')}</td><td>${EVKIN.util.esc(r.source_filename||'')}<br><small>${EVKIN.util.esc(r.source_file_hash||'-')}</small></td><td>${r.total_rows||0}</td><td>${r.valid_rows||0}/${r.warning_rows||0}/${r.invalid_rows||0}/${r.duplicate_rows||0}</td><td>${money(r.nominal_berhasil)}/${money(r.nominal_gagal)}</td><td>${EVKIN.util.esc(r.status||'')}</td><td><a class="btn btn-sm btn-secondary" href="${new URL('/pengembalian/archive/progress/imports/'+encodeURIComponent(r.import_batch_id)+'/validation-result',EVKIN.exportBackend.apiBase)}">Validation</a> ${['COMMITTED','PARTIAL'].includes(r.status)?`<button class="btn btn-sm btn-danger batch-rollback" data-id="${EVKIN.util.esc(r.import_batch_id)}">Revert Batch</button>`:''}</td></tr>`).join('')}</tbody></table></div>`;area.querySelectorAll('.batch-rollback').forEach(x=>x.onclick=async()=>{if(!confirm('Revert batch '+x.dataset.id+' dengan transaksi reversal?'))return;const response=await fetch(new URL('/pengembalian/archive/progress/imports/'+encodeURIComponent(x.dataset.id)+'/rollback',EVKIN.exportBackend.apiBase),{method:'POST'});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Revert gagal');EVKIN.toast('Batch direvert; transaksi reversal tercatat','success');button.click();});});
        await loadProgress(0);
        const pendingImports = await fetch(new URL('/pengembalian/archive/progress/imports?limit=20',EVKIN.exportBackend.apiBase)).then(r=>r.json());
        const readyBatch = (pendingImports.rows||[]).find(row=>row.status==='READY');
        if(readyBatch){
          const previewArea=document.getElementById('progressPreviewResult');
          previewArea.innerHTML=`<div class="alert warn"><strong>Import menunggu commit:</strong> ${EVKIN.util.esc(readyBatch.source_filename||readyBatch.import_batch_id)} — ${Number(readyBatch.total_rows||0).toLocaleString('id-ID')} baris, ${Number(readyBatch.warning_rows||0).toLocaleString('id-ID')} warning. Data belum masuk Progress SDM.<br><button id="commitReadyProgress" class="btn btn-primary">Commit ke Progress SDM</button> <a class="btn btn-secondary" href="${new URL('/pengembalian/archive/progress/imports/'+encodeURIComponent(readyBatch.import_batch_id)+'/validation-result',EVKIN.exportBackend.apiBase)}">Lihat Validasi</a></div>`;
          document.getElementById('commitReadyProgress').onclick=async()=>{const includeWarnings=document.getElementById('progressIncludeWarnings').checked;if(includeWarnings&&!confirm('Baris WARNING juga akan disimpan. Lanjutkan?'))return;const stage=document.getElementById('progressImportStage');stage.textContent='SAVING · RECALCULATING · RECONCILING';const response=await fetch(new URL('/pengembalian/archive/progress/import',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({import_batch_id:readyBatch.import_batch_id,created_by:'ui',include_warnings:includeWarnings})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Commit gagal');stage.textContent='COMPLETE · PROGRESS SDM UPDATED';previewArea.innerHTML=`<div class="alert success">${Number(result.inserted||0).toLocaleString('id-ID')} transaksi masuk. Progress SDM dan sisa piutang sudah diperbarui.</div>`;progressCursors=[''];await loadProgress(0);};
        }
      } catch (error) {
        cont.innerHTML = `<div class="alert error">${EVKIN.util.esc(error.message)}</div>`;
      }
    };
    document.getElementById('mpPeriods').onclick = async function () {
      const cont = document.getElementById('mpContent');
      const load = async () => {
        const response = await fetch(new URL('/pengembalian/periods', EVKIN.exportBackend.apiBase));
        const contentType = response.headers.get('content-type') || '';
        const raw = await response.text();
        let data = {};
        if (contentType.includes('json') && raw) {
          try { data = JSON.parse(raw); } catch (error) {
            throw new Error('Respons backend periode tidak valid: ' + error.message);
          }
        }
        if (!response.ok) throw new Error(data.detail || raw || 'Gagal memuat periode');
        const actionButton = (action, id, label, tone = 'secondary') => `<button type="button" class="btn btn-sm btn-${tone} period-action" data-action="${action}" data-id="${EVKIN.util.esc(id)}">${label}</button>`;
        const periodActions = row => {
          const id = EVKIN.util.esc(row.periode_id || '');
          const status = String(row.status || '').toUpperCase();
          const actions = [];
          if (status !== 'ACTIVE') actions.push(actionButton('ACTIVATE', id, 'Aktifkan', 'primary'));
          if (status === 'ACTIVE') actions.push(actionButton('LOCK', id, 'Kunci'));
          if (['LOCKED', 'ARCHIVED'].includes(status)) actions.push(actionButton('REOPEN', id, 'Buka Kembali'));
          if (status !== 'ARCHIVED') actions.push(actionButton('ARCHIVE', id, 'Arsipkan'));
          actions.push(`<button type="button" class="btn btn-sm btn-danger period-delete" data-id="${id}">Hapus Periode</button>`);
          return actions.join(' ');
        };
        cont.innerHTML = `<h3>Periode Arsip</h3><div class="form-row"><input id="periodName" placeholder="Nama periode"><input id="periodYear" type="number" min="2000" max="2100" placeholder="Tahun"><input id="periodStart" type="number" min="1" max="12" placeholder="Bulan awal"><input id="periodEnd" type="number" min="1" max="12" placeholder="Bulan akhir"><button id="periodSave" class="btn btn-primary">Tambah Periode</button></div><div class="alert warn">Periode aktif menerima import. Periode terkunci/arsip harus dibuka kembali sebelum diubah. Menghapus periode hanya menghapus konfigurasi; data arsip historis tetap tersimpan.</div><div class="table-wrap"><table class="data-table"><thead><tr><th>ID</th><th>Periode</th><th>Tahun</th><th>Bulan</th><th>Status</th><th>Terpakai</th><th>Aksi</th></tr></thead><tbody>${(data.rows||[]).map(row=>`<tr><td>${EVKIN.util.esc(row.periode_id||'')}</td><td>${EVKIN.util.esc(row.nama_periode||'')}</td><td>${row.tahun??''}</td><td>${row.bulan_awal??''}–${row.bulan_akhir??''}</td><td>${EVKIN.util.esc(row.status||'')}</td><td>${Number(row.usage_count||0).toLocaleString('id-ID')}</td><td>${periodActions(row)}</td></tr>`).join('')||'<tr><td colspan="7">Belum ada periode.</td></tr>'}</tbody></table></div>`;
        document.getElementById('periodSave').onclick = async () => {
          const name = document.getElementById('periodName').value.trim();
          const year = Number(document.getElementById('periodYear').value);
          const start = Number(document.getElementById('periodStart').value);
          const end = Number(document.getElementById('periodEnd').value);
          if (!name || !Number.isInteger(year) || year < 2000 || year > 2100 ||
              !Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end > 12 || start > end) {
            return EVKIN.toast('Lengkapi nama, tahun, dan rentang bulan periode yang valid.', 'error');
          }
          const button = document.getElementById('periodSave');
          button.disabled = true;
          try {
            const result = await fetch(new URL('/pengembalian/periods',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nama_periode:name,tahun:year,bulan_awal:start,bulan_akhir:end,created_by:(EVKIN.user&&EVKIN.user.username)||'ui'})});
            const json=await result.json().catch(()=>({}));
            if(!result.ok) throw new Error(json.detail||'Gagal menambah periode');
            EVKIN.toast('Periode ditambahkan','success');
            await load();
          } catch (error) {
            EVKIN.toast(error.message, 'error');
          } finally {
            button.disabled = false;
          }
        };
        cont.querySelectorAll('.period-action').forEach(button=>button.onclick=async()=>{
          const id=button.dataset.id;
          const action=button.dataset.action;
          if(!confirm(`${action} periode ${id}?`)) return;
          button.disabled=true;
          try {
            const response=await fetch(new URL('/pengembalian/periods/'+encodeURIComponent(id)+'/action',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,created_by:(EVKIN.user&&EVKIN.user.username)||'ui'})});
            const result=await response.json().catch(()=>({}));
            if(!response.ok) throw new Error(result.detail||`Gagal menjalankan aksi ${action}`);
            EVKIN.toast(`Periode ${id}: ${result.period_status||action}`,'success');
            await load();
          }catch(error){EVKIN.toast(error.message,'error');button.disabled=false;}
        });
        cont.querySelectorAll('.period-delete').forEach(button=>button.onclick=async()=>{const id=button.dataset.id;const required=`HAPUS PERIODE ${id}`;const confirmation=window.prompt(`Hapus periode ${id}? Data arsip historis tidak ikut dihapus. Ketik ${required} untuk melanjutkan:`);if(String(confirmation||'').trim().toUpperCase()!==required.toUpperCase())return;button.disabled=true;try{const response=await fetch(new URL('/pengembalian/periods/'+encodeURIComponent(id),EVKIN.exportBackend.apiBase),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation})});const result=await response.json().catch(()=>({}));if(!response.ok)throw new Error(result.detail||'Gagal menghapus periode');EVKIN.toast(`Periode ${id} dihapus`,'success');await load();}catch(error){EVKIN.toast(error.message,'error');button.disabled=false;}});
      };
      try { await load(); } catch (error) { cont.innerHTML=`<div class="alert error">${EVKIN.util.esc(error.message)}</div>`; }
    };
    document.getElementById('mpClearDatabase').onclick = async function () {
      if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) {
        EVKIN.toast('Backend belum aktif.', 'error');
        return;
      }
      const confirmation = window.prompt(
        'Tindakan ini menghapus seluruh periode, data impor Master Pengembalian, Data Final, dan Progres Pengembalian. Tabel database lain tidak akan disentuh. Ketik RESET MASTER PENGEMBALIAN untuk melanjutkan:'
      );
      if (!confirmation) return;
      const normalized = String(confirmation).trim().toUpperCase();
      if (!['HAPUS MASTER PENGEMBALIAN', 'RESET MASTER PENGEMBALIAN'].includes(normalized)) return;
      this.disabled = true;
      try {
        const response = await fetch(new URL('/pengembalian/archive/clear', EVKIN.exportBackend.apiBase), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirmation: normalized })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || 'Gagal reset database Master Pengembalian');
        EVKIN.toast(`Periode, Master, Data Final, dan Progres Pengembalian berhasil direset (${result.deleted_rows || 0} baris).`, 'success');
        window.location.reload();
      } catch (error) {
        EVKIN.toast(error.message, 'error');
        this.disabled = false;
      }
    };
    if (defaultPanel && !window.EVKIN_MONTHLY_MASTER_ENABLED) {
      defaultPanel.innerHTML = `
        <h2>MASTER PENGEMBALIAN</h2>
        <p class="muted"><strong>Database BNBA Pengembalian Tukin dan Uang Makan</strong></p>
        <div id="mpHomeKpis" class="mp-kpi-grid"><div class="mp-kpi">Memuat ringkasan…</div></div>
        <div id="mpHomeImport" class="card" style="margin-top:16px;"><p class="muted">Memuat import terakhir…</p></div>
      `;
      (async function loadHomeSummary() {
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const base = EVKIN.exportBackend.apiBase;
          const [dashboardResponse, historyResponse] = await Promise.all([
            fetch(new URL('/pengembalian/archive/dashboard?source=DATA_FINAL', base)),
            fetch(new URL('/pengembalian/archive/history?limit=1', base))
          ]);
          const dashboard = await dashboardResponse.json();
          const history = await historyResponse.json();
          if (!dashboardResponse.ok) throw new Error(dashboard.detail || 'Gagal memuat ringkasan');
          if (!historyResponse.ok) throw new Error(history.detail || 'Gagal memuat import terakhir');
          const money = value => Number(value || 0).toLocaleString('id-ID', {
            style: 'currency', currency: 'IDR', maximumFractionDigits: 0
          });
          const status = dashboard.status_pengembalian || {};
          const batch = dashboard.batch_bpk || {};
          // The user may switch to another Master Pengembalian panel while
          // these requests are still running.  In that case the home nodes
          // have already been removed and the stale response must be ignored.
          const homeKpis = document.getElementById('mpHomeKpis');
          const homeImport = document.getElementById('mpHomeImport');
          if (!homeKpis || !homeImport) return;
          homeKpis.innerHTML = [
            ['Total SDM', dashboard.total_sdm],
            ['Berubah', dashboard.sdm_berubah],
            ['Tidak berubah', dashboard.sdm_tidak_berubah],
            ['Nilai naik', dashboard.total_naik],
            ['Nilai turun', dashboard.total_turun],
            ['Total awal', money(dashboard.total_potongan_awal)],
            ['Total final', money(dashboard.total_potongan_penyesuaian)],
            ['Batch BPK', Object.entries(batch).map(([k,v]) => `${k}: ${v}`).join(' · ') || 'Belum ada']
          ].map(item => `<div class="mp-kpi"><span>${item[0]}</span><strong>${item[1] ?? 0}</strong></div>`).join('');
          const lastImport = (history.imports || [])[0] || {};
          homeImport.innerHTML = `
            <h4>Import terakhir</h4>
            <div class="tool-stats">
              <div class="tool-stat"><span class="label">Waktu import</span><span class="value">${EVKIN.util.esc(String(lastImport.imported_at || '-'))}</span></div>
              <div class="tool-stat"><span class="label">Nama file sumber</span><span class="value">${EVKIN.util.esc(String(lastImport.filename || lastImport.source_file_name || '-'))}</span></div>
            </div>`;
        } catch (error) {
          const homeKpis = document.getElementById('mpHomeKpis');
          const homeImport = document.getElementById('mpHomeImport');
          if (homeKpis) homeKpis.innerHTML = `<div class="alert error">${EVKIN.util.esc(error.message)}</div>`;
          if (homeImport) homeImport.innerHTML = '';
        }
      }());
    }

    // Handlers
    document.getElementById('mpFinal').onclick = async function () {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `<h3>BNBA Pengembalian Tukin dan Uang Makan</h3>
        <p class="muted">Data final yang tersimpan dari arsip; data awal dan history tetap immutable.</p>
        <div id="finalKpis" class="mp-kpi-grid"><div class="mp-kpi">Memuat KPI…</div></div>
        <div class="mp-filterbar"><input id="finalSearch" class="mp-global-search" placeholder="Cari NIP, nama, periode, unit…" aria-label="Pencarian BNBA">
          <select id="finalStatus"><option value="">Semua status perubahan</option><option>BERUBAH</option><option>TIDAK BERUBAH</option></select>
          <select id="finalYearSp2d"><option value="">Semua Tahun SP2D</option></select><select id="finalBatch"><option value="">Semua Batch BPK</option></select><select id="finalDirection"><option value="">Semua arah</option><option>NAIK</option><option>TURUN</option><option>TETAP</option></select>
          <input id="finalProvince" placeholder="Provinsi"><input id="finalUnit" placeholder="Unit kerja"><input id="finalPeriod" placeholder="Periode"><select id="finalQuick"><option value="">Quick filter…</option><option value="changed">Semua Berubah</option><option value="unchanged">Tidak Berubah</option><option value="up">Nilai Naik</option><option value="down">Nilai Turun</option><option value="zero">Menjadi 0</option><option value="fromzero">Dari 0 Menjadi Ada</option><option value="october">Oktober Berubah</option><option value="november">November Berubah</option><option value="december">Desember Berubah</option></select><button id="finalLoad" class="btn btn-primary">Terapkan</button>
          <button id="finalColumns" class="btn btn-secondary">Kolom</button><select id="finalExportPreset"><option value="">Export sesuai filter</option><option value="all">Semua data</option><option value="changed">Hanya berubah</option><option value="unchanged">Hanya tidak berubah</option><option value="up">Nilai naik</option><option value="down">Nilai turun</option><option value="batch1">Batch 1 semua</option><option value="batch1changed">Batch 1 berubah</option><option value="batch1unchanged">Batch 1 tidak berubah</option><option value="batch2">Batch 2 semua</option><option value="batch2changed">Batch 2 berubah</option><option value="batch2unchanged">Batch 2 tidak berubah</option><option value="october">Perubahan Oktober</option><option value="november">Perubahan November</option><option value="december">Perubahan Desember</option><option value="change-report">Laporan seluruh perubahan</option><option value="unchanged-report">Laporan data tetap</option></select><button id="finalExport" class="btn btn-secondary">Export BNBA</button>
        </div><div id="finalColumnMenu" class="mp-column-menu hidden"></div><div id="finalSp2dSummary"></div><div id="finalBatchSummary"></div>
        <div class="mp-actionbar"><span id="finalSelection">0 dipilih</span><button id="finalSelectFiltered" class="btn btn-sm btn-secondary">Pilih semua hasil</button>
          <button id="finalAggregate" class="btn btn-sm btn-secondary">Buat agregat</button></div>
        <div class="mp-actionbar"><label>Kelompok agregat <select id="finalGroupBy" multiple size="1"><option value="tahun_sp2d" selected>Tahun SP2D</option><option value="provinsi">Provinsi</option><option value="kabupaten_kota">Kabupaten/Kota</option><option value="final_batch_normalized">Batch final</option><option value="arah_perubahan">Arah perubahan</option></select></label></div><div id="finalAggregateResult"></div><div id="finalResult"><p>Memuat data final…</p></div>`;
      const state = { rows: [], total: 0, page: 1, size: 25, selected: new Set(), cols: ['nip','nama','batch','tukin_pengembalian_oktober','final_pengembalian_tukin_oktober','selisih_oktober','flag_perubahan_oktober','tukin_pengembalian_november','final_pengembalian_tukin_november','selisih_november','flag_perubahan_november','tukin_pengembalian_desember','final_pengembalian_tukin_desember','selisih_desember','flag_perubahan_desember','total_awal_tukin','final_total_pengembalian_tukin','selisih_total_tukin','flag_perubahan_total','arah_perubahan','status_compare'] };
      const savedFilters = (() => { try { return JSON.parse(sessionStorage.getItem('mp-final-filters') || '{}'); } catch (_) { return {}; } })();
      Object.entries(savedFilters).forEach(([id, value]) => { const input = document.getElementById(id); if (input) input.value = value; });
      const finalElement = id => document.getElementById(id);
      const finalValue = id => { const input = finalElement(id); return input ? String(input.value || '') : ''; };
      const finalMounted = () => cont.isConnected && finalElement('finalResult') && finalElement('mpContent') === cont;
      const labels = { nip:'NIP', nama:'Nama', batch:'Batch BPK', periode:'Periode', unit_kerja:'Unit', tahun_sp2d:'Tahun SP2D', tukin_pengembalian_oktober:'Awal Okt', final_pengembalian_tukin_oktober:'Final Okt', selisih_oktober:'Selisih Okt', flag_perubahan_oktober:'Flag Okt', tukin_pengembalian_november:'Awal Nov', final_pengembalian_tukin_november:'Final Nov', selisih_november:'Selisih Nov', flag_perubahan_november:'Flag Nov', tukin_pengembalian_desember:'Awal Des', final_pengembalian_tukin_desember:'Final Des', selisih_desember:'Selisih Des', flag_perubahan_desember:'Flag Des', total_awal_tukin:'Total Awal', final_total_pengembalian_tukin:'Total Final', selisih_total_tukin:'Selisih Total', nilai_awal:'Nilai awal', nilai_final:'Nilai final', selisih:'Selisih total', changed_fields:'Komponen berubah', status_compare:'Status', bpk_batch:'Riwayat kirim BPK', arah_perubahan:'Arah' };
      const value = (r, key) => key === 'nip' ? (r.identity?.nip || r.nip) : key === 'nama' ? (r.identity?.nama || r.nama) : key === 'changed_fields' ? (r.repayment_changes || []).map(x => `${x.field}: ${money(x.delta)}`).join(' | ') : (r[key] ?? '');
      const money = v => Number(v || 0).toLocaleString('id-ID');
      const params = (includeQuick=true) => { const p = new URLSearchParams({ source:'DATA_FINAL' }); [['status_perubahan','finalStatus'],['tahun_sp2d','finalYearSp2d'],['batch','finalBatch'],['arah_perubahan','finalDirection'],['periode','finalPeriod'],['provinsi','finalProvince'],['unit_kerja','finalUnit']].forEach(([k,id]) => { const v=finalValue(id); if(v) p.set(k,v); }); const quick=finalValue('finalQuick'); const quickMap={changed:['flag_ada_perubahan','BERUBAH'],unchanged:['flag_ada_perubahan','TIDAK BERUBAH'],up:['arah_perubahan','NAIK'],down:['arah_perubahan','TURUN'],zero:['change_class','MENJADI 0'],fromzero:['change_class','DARI 0 MENJADI ADA'],october:['flag_perubahan_oktober','BERUBAH'],november:['flag_perubahan_november','BERUBAH'],december:['flag_perubahan_desember','BERUBAH']}; if(includeQuick && quickMap[quick]) p.set(quickMap[quick][0],quickMap[quick][1]); const q=finalValue('finalSearch').trim(); if(q) p.set('search',q); if(includeQuick){p.set('limit',String(state.size));p.set('offset',String((state.page-1)*state.size));} return p; };
      function render() {
        const visible=state.rows, start=(state.page-1)*state.size, keys=state.cols;
        const head=keys.map(k=>`<th>${labels[k]}</th>`).join('');
        const numericColumns = new Set(['tukin_pengembalian_oktober','final_pengembalian_tukin_oktober','selisih_oktober','tukin_pengembalian_november','final_pengembalian_tukin_november','selisih_november','tukin_pengembalian_desember','final_pengembalian_tukin_desember','selisih_desember','total_awal_tukin','final_total_pengembalian_tukin','selisih_total_tukin','nilai_awal','nilai_final','selisih']);
        const body=visible.map((r,i)=>{ const id=String(r.record_id||r.initial_record_id||r.row_id||`${start+i}`); return `<tr><td><input type="checkbox" class="final-check" data-id="${EVKIN.util.esc(id)}" ${state.selected.has(id)?'checked':''}></td>${keys.map(k=>`<td>${numericColumns.has(k)?money(value(r,k)):EVKIN.util.esc(String(value(r,k)))}</td>`).join('')}<td><button class="btn btn-sm final-detail" data-id="${EVKIN.util.esc(id)}">Detail</button></td></tr>`; }).join('');
        document.getElementById('finalResult').innerHTML=`<div class="table-wrap"><table class="data-table mp-bnba-table"><thead><tr><th><input id="finalSelectPage" type="checkbox" aria-label="Pilih halaman"></th>${head}<th>Aksi</th></tr></thead><tbody>${body||'<tr><td colspan="20" class="muted">Tidak ada data.</td></tr>'}</tbody></table></div><div class="mp-pagination"><button id="finalPrev" class="btn btn-sm btn-secondary">‹</button><span>Halaman ${state.page} · ${state.total} baris</span><button id="finalNext" class="btn btn-sm btn-secondary">›</button></div>`;
        document.querySelectorAll('.final-check').forEach(x=>x.onchange=()=>{x.checked?state.selected.add(x.dataset.id):state.selected.delete(x.dataset.id); updateSelection();});
        document.querySelectorAll('.final-detail').forEach(x=>x.onclick=()=>showFinalDetail(x.dataset.id));
        document.getElementById('finalPrev').disabled=state.page===1; document.getElementById('finalNext').disabled=start+state.size>=state.total;
        document.getElementById('finalPrev').onclick=()=>{state.page--;loadFinal();}; document.getElementById('finalNext').onclick=()=>{state.page++;loadFinal();};
        document.getElementById('finalSelectPage').onchange=e=>visible.forEach(r=>{const id=String(r.record_id||r.initial_record_id||r.row_id||''); e.target.checked?state.selected.add(id):state.selected.delete(id);}); document.getElementById('finalSelectPage').onclick=()=>{render();updateSelection();};
      }
      function updateSelection(){document.getElementById('finalSelection').textContent=state.selected.size+' dipilih';}
      function renderDashboard(k) {
        const keepOptions = (id, values, label) => { const select=finalElement(id);if(!select)return;const current=select.value;select.innerHTML=`<option value="">${label}</option>`+(values||[]).map(v=>`<option value="${EVKIN.util.esc(String(v))}">${EVKIN.util.esc(String(v))}</option>`).join('');select.value=current; };
        keepOptions('finalYearSp2d', k.filter_options?.tahun_sp2d, 'Semua Tahun SP2D');
        keepOptions('finalBatch', k.filter_options?.batch, 'Semua Batch BPK');
        const kpis=finalElement('finalKpis');
        if(kpis)kpis.innerHTML=[['Total SDM',k.total_sdm,''],['Berubah',k.sdm_berubah,'BERUBAH'],['Tidak berubah',k.sdm_tidak_berubah,'TIDAK BERUBAH'],['Naik',k.total_naik,'NAIK'],['Turun',k.total_turun,'TURUN'],['Total awal',money(k.total_potongan_awal),''],['Total final',money(k.total_potongan_penyesuaian),''],['Selisih',money(k.total_selisih),''],['Kenaikan',money(k.total_kenaikan),''],['Penurunan',money(k.total_pengurangan),'']].map(x=>`<button type="button" class="mp-kpi final-kpi-drill" data-filter="${x[2]}"><span>${x[0]}</span><strong>${x[1]??0}</strong></button>`).join('');
        kpis?.querySelectorAll('.final-kpi-drill').forEach(button=>button.onclick=()=>{const filter=button.dataset.filter;if(!filter)return;if(['BERUBAH','TIDAK BERUBAH'].includes(filter)){finalElement('finalStatus').value=filter;finalElement('finalDirection').value='';}else{finalElement('finalDirection').value=filter;finalElement('finalStatus').value=filter==='NAIK'||filter==='TURUN'?'BERUBAH':'';}loadFinal(true);});
        const yearRows=k.sp2d_summary||[];
        finalElement('finalSp2dSummary').innerHTML=`<h4>Rekap Tahun SP2D</h4><div class="mp-kpi-grid">${yearRows.map(r=>`<div class="mp-kpi"><span>SP2D ${EVKIN.util.esc(String(r.tahun_sp2d??'-'))}</span><strong>${r.total_sdm||0} SDM</strong><small>Berubah ${r.berubah||0} · Tidak berubah ${r.tidak_berubah||0}<br>Naik ${r.naik||0} · Turun ${r.turun||0}<br>Awal ${money(r.nilai_awal)} · Final ${money(r.nilai_final)}<br>Selisih ${money(r.selisih)}</small></div>`).join('')||'<p class="muted">Tidak ada data.</p>'}</div>`;
        const batchRows=k.batch_summary||[];
        finalElement('finalBatchSummary').innerHTML=`<h4>Rekap Tahun SP2D + Batch BPK</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>Tahun</th><th>Batch BPK</th><th>SDM</th><th>Berubah</th><th>Tidak berubah</th><th>Naik</th><th>Turun</th><th>Awal</th><th>Final</th><th>Selisih</th></tr></thead><tbody>${batchRows.map(r=>`<tr><td>${EVKIN.util.esc(String(r.tahun_sp2d??'-'))}</td><td>${EVKIN.util.esc(String(r.batch??'Belum ada'))}</td><td>${r.total_sdm||0}</td><td>${r.berubah||0}</td><td>${r.tidak_berubah||0}</td><td>${r.naik||0}</td><td>${r.turun||0}</td><td>${money(r.nilai_awal)}</td><td>${money(r.nilai_final)}</td><td>${money(r.selisih)}</td></tr>`).join('')||'<tr><td colspan="10">Tidak ada data.</td></tr>'}</tbody></table></div>`;
      }
      async function loadFinal(resetPage){if(!finalMounted())return;if(resetPage)state.page=1;const area=finalElement('finalResult');area.innerHTML='<p>Memuat data final…</p>';try{if(!EVKIN.exportBackend?.enabled)throw new Error('Backend tidak aktif');const query=params();const saved={};['finalSearch','finalStatus','finalYearSp2d','finalBatch','finalDirection','finalPeriod','finalProvince','finalUnit','finalQuick'].forEach(id=>{saved[id]=finalValue(id);});try{sessionStorage.setItem('mp-final-filters',JSON.stringify(saved));}catch(_){}const res=await fetch(new URL('/pengembalian/archive/final?'+query,EVKIN.exportBackend.apiBase));const json=await res.json();if(!res.ok)throw new Error(json.detail||'Gagal memuat data final');if(!finalMounted())return;state.rows=json.rows||[];state.total=json.total||0;render();const dashboardQuery=new URLSearchParams(query);dashboardQuery.delete('limit');dashboardQuery.delete('offset');const d=await fetch(new URL('/pengembalian/archive/dashboard?'+dashboardQuery,EVKIN.exportBackend.apiBase));const k=await d.json();if(!d.ok)throw new Error(k.detail||'Gagal memuat KPI');if(!finalMounted())return;renderDashboard(k);}catch(e){if(finalMounted())area.innerHTML='<div class="alert error">'+EVKIN.util.esc(e.message)+'</div>';}}
      async function showFinalDetail(id){
        const area=document.getElementById('finalResult');
        try{
          const r=await fetch(new URL('/pengembalian/archive/detail/'+encodeURIComponent(id)+'?source=DATA_FINAL',EVKIN.exportBackend.apiBase));
          const j=await r.json(); if(!r.ok)throw new Error(j.detail||'Detail tidak tersedia');
          const row=j.row||{}, identity=row.identity||{}, basis=row.dasar_perhitungan_absensi||null;
          const esc=EVKIN.util.esc, money=v=>v===null||v===undefined?'-':Number(v||0).toLocaleString('id-ID');
          const percent=v=>v===null||v===undefined?'-':(Number(v)*100).toLocaleString('id-ID',{maximumFractionDigits:6})+'%';
          const batchBpk=row.batch===null||row.batch===undefined||String(row.batch).trim()===''?'Belum ada':row.batch;
          const fields=[['NIP',identity.nip],['Nama',identity.nama],['Periode',identity.periode],['Tahun SP2D',row.tahun_sp2d],['Batch BPK',batchBpk],['Status perubahan',row.status_perubahan||row.flag_ada_perubahan],['Arah perubahan',row.arah_perubahan],['Nilai awal',money(row.nilai_awal)],['Nilai final',money(row.nilai_final)],['Selisih',money(row.selisih)],['Field berubah',(row.changed_fields||[]).join(', ')||'-']];
          const values=Object.entries(row.final_values||{}).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(String(v??'-'))}</td><td>${money((row.deltas||{})[k])}</td></tr>`).join('');
          const monthRows=basis?['oktober','november','desember'].map(name=>{const item=basis.months?.[name]||{};return `<tr><td>${name[0].toUpperCase()+name.slice(1)}</td><td>${percent(item.persentase_potongan)}</td><td>${money(item.nominal_raw)}</td><td>${money(item.nominal_dasar)}</td><td>${money(item.nominal_final_saat_ini)}</td><td>${money(item.selisih_dasar_vs_final)}</td></tr>`;}).join(''):'';
          const basisHtml=basis?`<h5>Dasar perhitungan absensi</h5><p class="muted">Formula: Total Tukin × 30% × persentase rekap. Ini adalah dasar audit; nilai final resmi tidak ditimpa otomatis.</p><div class="mp-detail-grid"><div><span>Total Tukin</span><strong>Rp ${money(basis.total_tukin)}</strong></div><div><span>30% Tukin</span><strong>Rp ${money(basis.tukin_absen_30)}</strong></div><div><span>Total dasar</span><strong>Rp ${money(basis.nominal_dasar_total)}</strong></div><div><span>Status validasi</span><strong>${esc(basis.status||'-')}</strong></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Bulan</th><th>% Potongan</th><th>Nominal raw</th><th>Dasar dibulatkan</th><th>Final saat ini</th><th>Selisih</th></tr></thead><tbody>${monthRows}</tbody></table></div>${basis.issues?.length?`<div class="alert warning">${basis.issues.map(esc).join('<br>')}</div>`:''}`:`<div class="alert warning">Dasar perhitungan absensi belum tersedia untuk data ini.</div>`;
          area.innerHTML=`<button id="finalBack" class="btn btn-secondary">‹ Kembali</button><h4>Detail BNBA</h4><div class="mp-detail-grid">${fields.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(String(v??'-'))}</strong></div>`).join('')}</div>${basisHtml}<h5>Komponen dan perubahan</h5><div class="table-wrap"><table class="data-table"><thead><tr><th>Komponen</th><th>Nilai final</th><th>Selisih</th></tr></thead><tbody>${values||'<tr><td colspan="3">Tidak ada komponen</td></tr>'}</tbody></table></div><div class="mp-drilldown"><button class="btn btn-sm btn-secondary" id="detailDaily">Detail sumber absensi</button><button class="btn btn-sm btn-secondary" id="detailTrace">Lihat lineage</button><div id="detailSub"></div></div>`;
          document.getElementById('finalBack').onclick=render;
          document.getElementById('detailTrace').onclick=()=>{document.getElementById('detailSub').innerHTML=`<pre class="mp-detail">${esc(JSON.stringify(row.traceability||{},null,2))}</pre>`;};
          document.getElementById('detailDaily').onclick=async()=>{const nip=identity.nip||row.nip||'', periodId=row.periode_id||identity.periode_id||'';const sub=document.getElementById('detailSub');sub.innerHTML='<p>Memuat sumber rekap…</p>';try{const query=new URLSearchParams();if(periodId)query.set('periode_id',periodId);const d=await fetch(new URL('/pengembalian/archive/daily-detail/'+encodeURIComponent(nip)+'?'+query,EVKIN.exportBackend.apiBase));const data=await d.json();if(!d.ok)throw new Error(data.detail||'Detail absensi tidak tersedia');const recap=data.tabs?.data_dasar_rekap?.rows||[];sub.innerHTML=`<h5>Sumber rekap per bulan</h5><div class="table-wrap"><table class="data-table"><thead><tr><th>Bulan</th><th>Nilai asli</th><th>Persentase</th><th>Status</th><th>Baris sumber</th></tr></thead><tbody>${recap.map(x=>`<tr><td>${esc(String(x.bulan||'-'))}</td><td>${esc(String(x.raw_value??'-'))}</td><td>${percent(x.persentase_potongan)}</td><td>${esc(x.validation_status||'-')}</td><td>${esc((x.source_sheet||'-')+' / '+(x.source_row||'-'))}</td></tr>`).join('')||'<tr><td colspan="5">Sumber rekap tidak ditemukan.</td></tr>'}</tbody></table></div>`;}catch(err){sub.innerHTML=`<div class="alert error">${esc(err.message)}</div>`;}};
        }catch(e){area.innerHTML='<div class="alert error">'+EVKIN.util.esc(e.message)+'</div>';}
      }
      document.getElementById('finalLoad').onclick=()=>loadFinal(true); document.getElementById('finalQuick').onchange=()=>loadFinal(true); document.getElementById('finalSelectFiltered').onclick=async()=>{const button=document.getElementById('finalSelectFiltered');button.disabled=true;button.textContent='Memuat ID…';try{const p=params();p.delete('limit');p.delete('offset');const response=await fetch(new URL('/pengembalian/archive/final/ids?'+p,EVKIN.exportBackend.apiBase));const json=await response.json();if(!response.ok)throw new Error(json.detail||'Gagal memilih hasil');(json.record_ids||[]).forEach(id=>state.selected.add(String(id)));updateSelection();render();EVKIN.toast((json.total||0)+' hasil dipilih','success');}catch(error){EVKIN.toast(error.message,'error');}finally{button.disabled=false;button.textContent='Pilih semua hasil';}};
      document.getElementById('finalSearch').oninput=(()=>{let t;return()=>{clearTimeout(t);t=setTimeout(()=>loadFinal(true),350);};})();
      document.getElementById('finalExport').onclick=()=>{const preset=document.getElementById('finalExportPreset').value;const p=preset==='all'?new URLSearchParams({source:'DATA_FINAL'}):params(false);const presetMap={changed:['flag_ada_perubahan','BERUBAH'],unchanged:['flag_ada_perubahan','TIDAK BERUBAH'],up:['arah_perubahan','NAIK'],down:['arah_perubahan','TURUN'],batch1:['final_batch_normalized','BATCH 1'],batch2:['final_batch_normalized','BATCH 2'],october:['flag_perubahan_oktober','BERUBAH'],november:['flag_perubahan_november','BERUBAH'],december:['flag_perubahan_desember','BERUBAH']};if(presetMap[preset])p.set(presetMap[preset][0],presetMap[preset][1]);if(['batch1changed','batch2changed','change-report'].includes(preset))p.set('flag_ada_perubahan','BERUBAH');if(['batch1unchanged','batch2unchanged','unchanged-report'].includes(preset))p.set('flag_ada_perubahan','TIDAK BERUBAH');if(preset.startsWith('batch1'))p.set('final_batch_normalized','BATCH 1');if(preset.startsWith('batch2'))p.set('final_batch_normalized','BATCH 2');if(state.selected.size)p.set('record_ids',Array.from(state.selected).join(','));window.open(new URL('/pengembalian/archive/download?'+p,EVKIN.exportBackend.apiBase),'_blank');};
      document.getElementById('finalAggregate').onclick=async()=>{try{const filters=Object.fromEntries(params());delete filters.source;delete filters.limit;delete filters.offset;const groupBy=Array.from(document.getElementById('finalGroupBy').selectedOptions).map(x=>x.value);const r=await fetch(new URL('/pengembalian/archive/aggregate',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:'DATA_FINAL',filters,group_by:groupBy.length?groupBy:['periode']})});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Agregat gagal');const rows=j.rows||[];document.getElementById('finalAggregateResult').innerHTML='<div class="table-wrap"><table class="data-table sm"><thead><tr>'+groupBy.map(x=>'<th>'+EVKIN.util.esc(x)+'</th>').join('')+'<th>SDM</th><th>Total Awal Pengembalian</th><th>Total Pengembalian</th></tr></thead><tbody>'+rows.map(x=>'<tr>'+groupBy.map(k=>'<td>'+EVKIN.util.esc(String(x[k]||'-'))+'</td>').join('')+'<td>'+String(x.jumlah_sdm||0)+'</td><td>'+money(x.total_awal_tukin)+'</td><td>'+money(x.total_potongan_tukin)+'</td></tr>').join('')+'</tbody></table></div>';EVKIN.toast('Agregat: '+rows.length+' grup','success');}catch(e){EVKIN.toast(e.message,'error');}};
      document.getElementById('finalColumns').onclick=()=>{const m=document.getElementById('finalColumnMenu');m.classList.toggle('hidden');m.innerHTML=Object.keys(labels).map(k=>`<label><input type="checkbox" data-col="${k}" ${state.cols.includes(k)?'checked':''}> ${labels[k]}</label>`).join('');m.querySelectorAll('input').forEach(x=>x.onchange=()=>{state.cols=Array.from(m.querySelectorAll('input:checked')).map(y=>y.dataset.col);if(!state.cols.length){x.checked=true;state.cols=[x.dataset.col];}render();});};
      loadFinal();
    };
    document.getElementById('mpDailyData').onclick = async function () {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `<h3>Data Dasar Perhitungan</h3><p class="muted">Workbook besar diproses di server. Hanya REKAP OKT, REKAP NOV, dan REKAP DES kolom NIP serta Total Potongan yang dihubungkan ke Master Pengembalian.</p><div class="form-row"><select id="datasetPeriod"><option value="">Pilih Database Master/Periode</option></select><input id="datasetFile" type="file" accept=".xlsx,.xls,.csv"><button id="datasetImport" class="btn btn-primary">Import & Hubungkan</button><button id="datasetMaterialize" class="btn btn-secondary">Hubungkan Dataset Lama</button><button id="datasetRefresh" class="btn btn-secondary">Muat Ulang</button></div><div id="datasetProgress" class="muted"></div><div id="datasetList"><p>Memuat dataset…</p></div><div id="datasetView"></div>`;
      const periodResponse=await fetch(new URL('/pengembalian/periods',EVKIN.exportBackend.apiBase));
       const periodJson=await periodResponse.json();
       const periodSelect=document.getElementById('datasetPeriod');
       if (!periodSelect || !cont.isConnected) return;
      (periodJson.rows||[]).forEach(row=>{const option=document.createElement('option');option.value=row.periode_id;option.textContent=`${row.periode_id} — ${row.nama_periode||''} (${row.status||'DRAFT'})`;option.disabled=['LOCKED','CLOSED','ARCHIVED'].includes(String(row.status||'').toUpperCase());periodSelect.appendChild(option);});
      const active=(periodJson.rows||[]).find(row=>row.is_active&&!['LOCKED','CLOSED','ARCHIVED'].includes(String(row.status||'').toUpperCase()));if(active)periodSelect.value=active.periode_id;
      const loadDatasets = async () => { const response=await fetch(new URL('/pengembalian/datasets',EVKIN.exportBackend.apiBase));const json=await response.json();if(!response.ok)throw new Error(json.detail||'Gagal memuat dataset');const area=document.getElementById('datasetList');if(!area)return;area.innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>Dataset</th><th>Bulan</th><th>File</th><th>Sheet</th><th>Rows</th><th>Columns</th><th>Tanggal</th><th>Aksi</th></tr></thead><tbody>${(json.rows||[]).map(row=>`<tr><td>${EVKIN.util.esc(row.nama_dataset||'')}</td><td>${EVKIN.util.esc(row.bulan||'-')}</td><td>${EVKIN.util.esc(row.source_filename||'')}</td><td>${EVKIN.util.esc(row.sheet_name||'')}</td><td>${row.jumlah_baris||0}</td><td>${row.jumlah_kolom||0}</td><td>${EVKIN.util.esc(String(row.tanggal_import||''))}</td><td><button class="btn btn-sm dataset-open" data-id="${EVKIN.util.esc(row.dataset_id)}">View</button> <a class="btn btn-sm" href="${new URL('/pengembalian/datasets/'+encodeURIComponent(row.dataset_id)+'/download',EVKIN.exportBackend.apiBase)}">Excel</a></td></tr>`).join('')||'<tr><td colspan="8">Belum ada dataset.</td></tr>'}</tbody></table></div>`;area.querySelectorAll('.dataset-open').forEach(button=>button.onclick=async()=>{const result=await fetch(new URL('/pengembalian/datasets/'+encodeURIComponent(button.dataset.id)+'/rows?limit=100',EVKIN.exportBackend.apiBase)).then(r=>r.json());const rows=result.rows||[];const headers=rows.length?Object.keys(rows[0]):[];document.getElementById('datasetView').innerHTML=`<h4>Preview Dataset (${result.total||0} baris)</h4><div class="table-wrap"><table class="data-table"><thead><tr>${headers.map(h=>`<th>${EVKIN.util.esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${headers.map(h=>`<td>${EVKIN.util.esc(String(row[h]??''))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;});};
      document.getElementById('datasetRefresh').onclick=()=>loadDatasets().catch(error=>EVKIN.toast(error.message,'error'));
      document.getElementById('datasetMaterialize').onclick=async()=>{const periodeId=periodSelect.value;if(!periodeId)return EVKIN.toast('Pilih Database Master/Periode','error');const button=document.getElementById('datasetMaterialize');button.disabled=true;try{const response=await fetch(new URL('/pengembalian/datasets/materialize-rekap',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({periode_id:periodeId})});const json=await response.json();if(!response.ok)throw new Error(json.detail||'Gagal menghubungkan dataset');EVKIN.toast(`${json.datasets||0} dataset terhubung ke Detail SDM`,'success');await loadDatasets();}catch(error){EVKIN.toast(error.message,'error');}finally{button.disabled=false;}};
      document.getElementById('datasetImport').onclick=async()=>{const file=document.getElementById('datasetFile').files[0],periodeId=periodSelect.value,button=document.getElementById('datasetImport'),progress=document.getElementById('datasetProgress');if(!file)return EVKIN.toast('Pilih file Data Dasar','error');if(!periodeId)return EVKIN.toast('Pilih Database Master/Periode','error');button.disabled=true;progress.textContent=`Mengunggah dan membaca ${file.name} di server…`;try{let response;if(file.name.toLowerCase().endsWith('.xlsx')){const url=new URL('/pengembalian/datasets/import-workbook',EVKIN.exportBackend.apiBase);url.searchParams.set('periode_id',periodeId);url.searchParams.set('filename',file.name);response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:file});}else{const workbook=XLSX.read(new Uint8Array(await file.arrayBuffer()),{type:'array',raw:true});const sheetName=workbook.SheetNames[0];const rows=XLSX.utils.sheet_to_json(workbook.Sheets[sheetName],{defval:'',raw:true});response=await fetch(new URL('/pengembalian/datasets/import',EVKIN.exportBackend.apiBase),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows,metadata:{periode_id:periodeId,filename:file.name,sheet_name:sheetName,nama_dataset:file.name},created_by:'ui'})});}const json=await response.json();if(!response.ok)throw new Error(json.detail||'Import Data Dasar gagal');progress.textContent=`Selesai: ${json.rows||0} baris, ${json.datasets||1} dataset. Dasar perhitungan sudah tersedia di Detail SDM.`;EVKIN.toast(`${json.rows||0} baris diimpor dan dihubungkan`,'success');await loadDatasets();}catch(error){progress.textContent='';EVKIN.toast(error.message,'error');}finally{button.disabled=false;}};
      await loadDatasets().catch(error=>{const area=document.getElementById('datasetList');if(area)area.innerHTML=`<div class="alert error">${EVKIN.util.esc(error.message)}</div>`;});
      return;
      cont.innerHTML = '<h3>Data Dasar Perhitungan</h3><div class="form-row"><input id="dailyNip" placeholder="NIP"><input id="dailyPeriod" placeholder="Periode"><button id="dailyLoad" class="btn btn-primary">Tampilkan</button></div><div id="dailyResult"></div>';
      document.getElementById('dailyLoad').onclick = async function () {
        const p = new URLSearchParams({ nip: document.getElementById('dailyNip').value, periode: document.getElementById('dailyPeriod').value });
        const res = await fetch(new URL('/pengembalian/archive/daily-compare?' + p, EVKIN.exportBackend.apiBase));
        const json = await res.json();
        document.getElementById('dailyResult').innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Tanggal</th><th>Nominal Awal</th><th>Nominal Penyesuaian</th><th>Selisih</th><th>Changed Fields</th><th>Status</th></tr></thead><tbody>${(json.rows || []).map(r => `<tr><td>${EVKIN.util.esc(r.nip || '')}</td><td>${EVKIN.util.esc(r.nama || '')}</td><td>${EVKIN.util.esc(r.tanggal || '')}</td><td>${r.nominal_awal || 0}</td><td>${r.nominal_penyesuaian || 0}</td><td>${r.selisih || 0}</td><td>${EVKIN.util.esc((r.changed_fields || []).join(', '))}</td><td>${EVKIN.util.esc(r.status || '')}</td></tr>`).join('')}</tbody></table></div>`;
      };
    };
    document.getElementById('mpExport').onclick = () => window.open(new URL('/pengembalian/archive/download?source=DATA_FINAL', EVKIN.exportBackend.apiBase), '_blank');
    document.getElementById('mpImportHistory').onclick = async function () {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `
        <h3>Import Arsip Pengembalian</h3>
        <div class="alert info"><strong>Import penuh BNBA:</strong> workbook ini wajib berisi data awal dan kolom DATA FINAL. Sistem akan menyimpan keduanya sebagai arsip terpisah dan membentuk DATA_FINAL tanpa menimpa data awal. Status BPK dan mode import tidak diperlukan pada tahap ini.</div>
        <div class="form-row"><label style="flex:1">Jenis Import<select id="mpImportType"><option value="EXISTING">Import Master Pengembalian Existing</option><option value="DASAR_PENGEMBALIAN_2025">Dasar Pengembalian Tahun 2025</option></select></label><label style="flex:1">Periode arsip<select id="mpImportPeriod"><option value="">Memuat periode…</option></select></label><label id="mpDasarYear" hidden>Tahun SP2D<input value="2025" readonly></label><label id="mpDasarComponent" hidden>Komponen<input value="TUKIN" readonly></label></div>
        <div class="dropzone" id="mpDz">
          <i data-lucide="upload-cloud"></i>
          <p><strong>Klik atau tarik file disini</strong></p>
          <p class="muted">Gunakan template <a href="examples/master_pengembalian/FORMAT_IMPORT_BNBA_TERPADU_BERSIH.xlsx" download>FORMAT_IMPORT_BNBA_TERPADU_BERSIH.xlsx</a> dengan sheet BNBA PENGEMBALIAN ALL SDM. Wajib: NIP dan kolom nominal Tukin. DATA FINAL di file yang sama diproses sebagai penyesuaian.</p>
          <input type="file" id="mpFileInput" accept=".xlsx,.xls,.csv" hidden />
          <button class="btn btn-primary" id="mpPickBtn"><i data-lucide="folder-open"></i> Pilih File</button>
        </div>
        <div id="mpImportProgress" class="import-progress" hidden>
          <div class="import-progress-head"><span id="mpImportLabel">Menghitung...</span><span id="mpImportPercent">0%</span></div>
          <div class="import-progress-track"><div id="mpImportBar" class="import-progress-bar"></div></div>
          <p class="muted import-progress-meta" id="mpImportMeta">0 / 0</p>
        </div>
        <div id="mpImportMsg"></div>
        <div id="mpImportPreview"></div>
      `;

      const fi = document.getElementById('mpFileInput');
      const dz = document.getElementById('mpDz');
      const pickBtn = document.getElementById('mpPickBtn');
      let pendingImport = null;
      document.getElementById('mpImportType').onchange = function () {
        const special = this.value === 'DASAR_PENGEMBALIAN_2025';
        document.getElementById('mpDasarYear').hidden = !special;
        document.getElementById('mpDasarComponent').hidden = !special;
        document.getElementById('mpImportPeriod').disabled = special;
      };
      fetch(new URL('/pengembalian/periods', EVKIN.exportBackend.apiBase)).then(r=>r.json()).then(data=>{const select=document.getElementById('mpImportPeriod');if(select)select.innerHTML=(data.rows||[]).map(row=>`<option value="${EVKIN.util.esc(row.periode_id)}">${EVKIN.util.esc(row.nama_periode)}</option>`).join('')||'<option value="">Belum ada periode</option>';}).catch(error=>console.error('[MasterPengembalian] period load failed',error));
      dz.onclick = () => fi.click();
      pickBtn.onclick = (event) => { event.stopPropagation(); fi.click(); };
      dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('drag'); };
      dz.ondragleave = () => dz.classList.remove('drag');
      dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove('drag'); if (e.dataTransfer.files[0]) processFile(e.dataTransfer.files[0]); };
      fi.onchange = () => { if (fi.files[0]) processFile(fi.files[0]); };

      function setProgress(visible, pct, processed, total, batchInfo) {
        const box = document.getElementById('mpImportProgress');
        if (!box) return;
        box.hidden = !visible;
        const bar = document.getElementById('mpImportBar');
        const percent = document.getElementById('mpImportPercent');
        const meta = document.getElementById('mpImportMeta');
        const label = document.getElementById('mpImportLabel');
        if (bar) bar.style.width = (pct || 0) + '%';
        if (percent) percent.textContent = (pct || 0) + '%';
        if (meta) meta.textContent = (processed || 0) + ' / ' + (total || 0);
        if (label) label.textContent = batchInfo || 'Memproses...';
      }

      async function sha1Hex(file) {
        const ab = await file.arrayBuffer();
        if (window.crypto && crypto.subtle && crypto.subtle.digest) {
          const hash = await crypto.subtle.digest('SHA-1', ab);
          const arr = Array.from(new Uint8Array(hash));
          return arr.map(b => b.toString(16).padStart(2, '0')).join('');
        }
        // fallback naive: simple checksum
        let sum = 0;
        const dv = new Uint8Array(ab);
        for (let i = 0; i < dv.length; i++) sum = (sum + dv[i]) & 0xffffffff;
        return 'chk-' + (sum >>> 0).toString(16);
      }

      function norm(h) { return String(h||'').toLowerCase().replace(/[^a-z0-9]/g, ''); }

      function detectHeaders(headers) {
        const map = {};
        headers.forEach((h,i)=>{
          const nh = norm(h);
          if (!map.nip && (nh === 'nip' || nh.includes('nip') || nh.includes('nomorpegawai') || nh.includes('noinduk'))) map.nip = i;
          if (!map.nama && (nh === 'nama' || nh.includes('nama') || nh.includes('namapegawai') || nh.includes('namalengkap'))) map.nama = i;
          if (!map.periode && (nh === 'periode' || nh === 'bulan' || nh === 'tahunbulan' || nh.includes('periode'))) map.periode = i;
          if (!map.tahun && (nh === 'tahun' || nh === 'thn')) map.tahun = i;
          if (!map.bulan && (nh === 'bulan' || nh === 'bln' || nh === 'bulan')) map.bulan = i;
          if (!map.komponen && (nh === 'komponen' || nh.includes('komponen') || nh.includes('jenis'))) map.komponen = i;
          if (!map.nominal && (nh === 'nominal' || nh === 'nominal_awal' || nh === 'amount' || nh === 'nominalawal' || nh.includes('nominal'))) map.nominal = i;
          if (!map.provinsi && (nh === 'provinsi' || nh.includes('prov'))) map.provinsi = i;
          if (!map.unit_kerja && (nh === 'unit' || nh === 'unit_kerja' || nh.includes('unit'))) map.unit_kerja = i;
          if (!map.tahun_sp2d && (nh === 'tahun_sp2d' || nh === 'tahunsp2d')) map.tahun_sp2d = i;
          if (!map.nomor_sp2d && (nh === 'nomor_sp2d' || nh === 'nomorsp2d' || nh.includes('sp2d'))) map.nomor_sp2d = i;
        });
        return map;
      }

      function parseNumber(v) {
        if (v === null || v === undefined || v === '') return null;
        if (typeof v === 'number') return Number.isFinite(v) ? v : null;
        let text = String(v).trim().replace(/[^0-9\-.,]/g, '');
        if (!text) return null;
        const comma = text.lastIndexOf(',');
        const dot = text.lastIndexOf('.');
        if (comma >= 0 && dot >= 0) {
          text = comma > dot ? text.replace(/\./g, '').replace(',', '.') : text.replace(/,/g, '');
        } else if (comma >= 0) {
          text = text.replace(/\./g, '').replace(',', '.');
        } else if ((text.match(/\./g) || []).length > 1) {
          text = text.replace(/\./g, '');
        }
        const n = Number(text);
        return Number.isFinite(n) ? n : null;
      }

      function normalizeImportPeriod(value) {
        if (value === null || value === undefined || value === '') return null;
        const text = String(value).trim();
        if (!text || text.toLowerCase() === 'none' || text.toLowerCase() === 'null') return null;
        const monthMap = {
          jan: '01', januari: '01', january: '01',
          feb: '02', februari: '02', february: '02',
          mar: '03', maret: '03', march: '03',
          apr: '04', april: '04',
          mei: '05', may: '05',
          jun: '06', juni: '06', june: '06',
          jul: '07', juli: '07', july: '07',
          aug: '08', agustus: '08', august: '08',
          sep: '09', sept: '09', september: '09',
          okt: '10', oktober: '10', oct: '10', october: '10',
          nov: '11', november: '11',
          des: '12', desember: '12', dec: '12', december: '12'
        };
        const yearMonth = text.match(/(\d{4})\D*(\d{1,2})/);
        if (yearMonth) {
          const year = Number(yearMonth[1]);
          const month = Number(yearMonth[2]);
          if (year && month >= 1 && month <= 12) return `${year}-${String(month).padStart(2, '0')}`;
        }
        const monthName = text.match(/(\d{4})\D*(jan|januari|january|feb|februari|february|mar|maret|march|apr|april|mei|may|jun|juni|june|jul|juli|july|aug|agustus|august|sep|sept|september|okt|oktober|oct|october|nov|november|des|desember|dec|december)/i);
        if (monthName) {
          const year = Number(monthName[1]);
          const month = monthMap[monthName[2].toLowerCase()];
          if (year && month) return `${year}-${month}`;
        }
        return null;
      }

      function inferImportPeriod(rows) {
        if (!Array.isArray(rows) || !rows.length) return null;
        const counts = new Map();
        rows.forEach(row => {
          if (!row || typeof row !== 'object') return;
          const raw = row.periode_id || row.period_id || row.id_periode || row.periode || row.period || row.tahun_bulan || row.year_month || (row.tahun && row.bulan ? `${row.tahun}-${String(row.bulan).padStart(2,'0')}` : '');
          const value = normalizeImportPeriod(raw);
          if (!value) return;
          const key = value.startsWith('RET-') ? value : `RET-${value}-${value.split('-')[1]}`;
          counts.set(key, (counts.get(key) || 0) + 1);
        });
        if (!counts.size) return null;
        return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0];
      }

      async function processDasar2025(file) {
        const msg=document.getElementById('mpImportMsg'),preview=document.getElementById('mpImportPreview');
        if (!String(file.name||'').toLowerCase().endsWith('.xlsx')) throw new Error('Dasar Pengembalian 2025 wajib berupa XLSX');
        const url=new URL('/pengembalian/dasar-2025/preview',EVKIN.exportBackend.apiBase);url.searchParams.set('filename',file.name);
        const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:file});
        const json=await response.json();if(!response.ok)throw new Error(json.detail||'Preview Dasar 2025 gagal');
        const s=json.summary||{},stageRows=Object.entries(s.progress_per_tahap||{}).map(([stage,count])=>`<tr><td>Tahap ${EVKIN.util.esc(stage)}</td><td>${Number(count||0).toLocaleString('id-ID')}</td></tr>`).join('');
        const issues=[...(json.errors||[]),...(json.warnings||[])].slice(0,20);
        msg.innerHTML='<div class="alert info">Preview selesai. Data belum ditulis ke database.</div>';
        preview.innerHTML=`<div class="card"><h4>Preview Dasar Pengembalian Tahun 2025</h4><p>File: ${EVKIN.util.esc(file.name)} · Sheet: ${EVKIN.util.esc(json.sheet||'')} · Tahun SP2D: 2025 · Komponen: TUKIN</p><div class="tool-stats"><div class="tool-stat"><span class="label">Baris / NIP unik</span><span class="value">${Number(s.jumlah_baris||0).toLocaleString('id-ID')} / ${Number(s.jumlah_nip_unik||0).toLocaleString('id-ID')}</span></div><div class="tool-stat"><span class="label">Oktober / November / Desember</span><span class="value">${Number(s.total_oktober||0).toLocaleString('id-ID')} / ${Number(s.total_november||0).toLocaleString('id-ID')} / ${Number(s.total_desember||0).toLocaleString('id-ID')}</span></div><div class="tool-stat"><span class="label">Total kewajiban / realisasi</span><span class="value">${Number(s.total_kewajiban||0).toLocaleString('id-ID')} / ${Number(s.total_realisasi||0).toLocaleString('id-ID')}</span></div><div class="tool-stat"><span class="label">Exact / Piutang / Overpayment</span><span class="value">${s.jumlah_exact_payment||0} / ${s.jumlah_masih_piutang||0} / ${s.jumlah_overpayment||0}</span></div><div class="tool-stat"><span class="label">Invalid / Duplicate</span><span class="value">${s.jumlah_invalid||0} / ${s.jumlah_duplicate||0}</span></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Progress</th><th>Jumlah baris</th></tr></thead><tbody>${stageRows}</tbody></table></div>${issues.length?'<details open><summary>Sample error/warning</summary><ul>'+issues.map(x=>`<li>Baris ${EVKIN.util.esc(String(x.row||'-'))}: ${EVKIN.util.esc((x.messages||[]).join(', '))}</li>`).join('')+'</ul></details>':''}${json.duplicate_file?'<div class="alert error">File sudah pernah diimport: '+EVKIN.util.esc(json.duplicate_file.import_id)+'</div>':''}<button id="mpCommitDasar2025" class="btn btn-primary" ${json.valid?'':'disabled'}>Import Dasar 2025</button> <button id="mpCancelImport" class="btn btn-secondary">Batalkan</button></div>`;
        document.getElementById('mpCommitDasar2025').onclick=async function(){if(!confirm('Commit dasar kewajiban dan progress ledger Tahun SP2D 2025?'))return;this.disabled=true;try{const commitUrl=new URL('/pengembalian/dasar-2025/import',EVKIN.exportBackend.apiBase);commitUrl.searchParams.set('filename',file.name);commitUrl.searchParams.set('imported_by',(EVKIN.user&&EVKIN.user.username)||'ui');const commit=await fetch(commitUrl,{method:'POST',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:file});const result=await commit.json();if(!commit.ok)throw new Error(result.detail||'Import gagal');preview.innerHTML='';msg.innerHTML=`<div class="alert success">Import berhasil. ${Number(result.obligations||0).toLocaleString('id-ID')} kewajiban dan ${Number(result.transactions||0).toLocaleString('id-ID')} transaksi ledger tersimpan. Import ID: ${EVKIN.util.esc(result.import_id||'')}</div>`;}catch(error){this.disabled=false;EVKIN.toast(error.message,'error');}};
        document.getElementById('mpCancelImport').onclick=()=>{preview.innerHTML='';msg.innerHTML='<div class="alert warn">Import dibatalkan. Tidak ada data yang disimpan.</div>';};
      }

      async function processFile(file) {
        const msg = document.getElementById('mpImportMsg');
        msg.innerHTML = '<div class="alert info">Membaca ' + (file.name || '') + ' ...</div>';
        pickBtn.disabled = true;
        try {
          if (document.getElementById('mpImportType').value === 'DASAR_PENGEMBALIAN_2025') {
            await processDasar2025(file);
            return;
          }
          const extension = String(file.name || '').toLowerCase().split('.').pop();
          if (!['xlsx', 'xls', 'csv'].includes(extension)) throw new Error('Format file harus .xlsx, .xls, atau .csv');
          if (file.size > 50 * 1024 * 1024) throw new Error('Ukuran file melebihi batas 50 MB');
          const file_hash = await sha1Hex(file);
          setProgress(true, 5, 0, 0, 'Membaca file dan memetakan kolom...');
          const ab = await file.arrayBuffer();
          const data = new Uint8Array(ab);
          const wb = XLSX.read(data, { type: 'array', raw: true, cellDates: false });
          const preferredSheet = wb.SheetNames.find(name =>
            norm(name) === 'bnbapengembalianallsdm'
          );
          const sheetName = preferredSheet || wb.SheetNames.find(name => {
            const candidate = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: true, defval: '' });
            return candidate.length && detectHeaders(candidate[0]).nip !== undefined;
          });
          if (!sheetName) throw new Error('Sheet BNBA tidak ditemukan. Pastikan ada kolom NIP.');
          const ws = wb.Sheets[sheetName];
          const aoa = XLSX.utils.sheet_to_json(ws, { header: 1, raw: true, defval: '' });
          if (!aoa || aoa.length < 2) throw new Error('File kosong atau tidak ada data');
          const headers = aoa[0].map(h=>String(h||'').trim());
          const headerMap = detectHeaders(headers);
          if (headerMap.nip === undefined) throw new Error('Kolom wajib NIP tidak ditemukan.');
          const normalizedHeaders = headers.map(norm);
          const hasBnbaNominal = normalizedHeaders.some(h =>
            h.includes('totaltukinpengembalian') ||
            h.includes('totalawaltukin') ||
            h.includes('finaltotalpengembaliantukin') ||
            h.includes('tukinpengembalian')
          );
          if (!hasBnbaNominal && headerMap.nominal === undefined) {
            throw new Error('Kolom nominal BNBA tidak ditemukan. Gunakan Total Awal Tukin, Final Total Pengembalian Tukin, atau kolom Tukin Pengembalian per bulan.');
          }
          // build rows
          const rows = [];
          const nips = new Set();
          const duplicateNips = new Set();
          const total = aoa.length - 1;
          for (let i = 1; i < aoa.length; i++) {
            const r = aoa[i];
            // skip blank rows
            if (!r || r.every(c => String(c).trim() === '')) continue;
            const get = (k) => (headerMap[k] !== undefined ? r[headerMap[k]] : undefined);
            const nip = String(get('nip') || '').trim();
            if (nip) {
              if (nips.has(nip)) duplicateNips.add(nip);
              nips.add(nip);
            }
            const nama = String(get('nama') || '').trim();
            let periode = String(get('periode') || '').trim();
            const tahunVal = get('tahun');
            const bulanVal = get('bulan');
            if ((!periode || periode === '') && tahunVal) {
              const y = String(tahunVal).trim();
              const m = String(bulanVal || '').trim().padStart(2,'0');
              periode = (y && m) ? (y + '-' + m) : '';
            }
            const komponen = String(get('komponen') || 'TUKIN').trim() || 'TUKIN';
            const nominal_awal = parseNumber(get('nominal'));
            const provinsi = String(get('provinsi') || '').trim();
            const unit_kerja = String(get('unit_kerja') || '').trim();
            const tahun_sp2d = get('tahun_sp2d');
            const nomor_sp2d = get('nomor_sp2d');

            // Preserve every source column so the backend can apply its
            // canonical aliases (for example "Total Tukin" and "E-Absensi").
            const sourceFields = {};
            headers.forEach((header, columnIndex) => {
              if (header) sourceFields[header] = r[columnIndex];
            });
            const rowObj = {
              ...sourceFields,
              nip: nip || null,
              nama: nama || null,
              periode: periode || null,
              tahun: tahunVal || null,
              bulan: bulanVal || null,
              komponen: komponen || null,
              nominal_awal: nominal_awal,
              nominal_tukin: null,
              nominal_uang_makan: null,
              sumber_data: file.name,
              tahun_sp2d: tahun_sp2d || null,
              nomor_sp2d: nomor_sp2d || null,
              provinsi: provinsi || null,
              unit_kerja: unit_kerja || null,
              jenis_pegawai: null,
              status_awal: null,
              source_file: file.name,
              source_sheet: sheetName,
              source_row: i + 1 // 1-based including header
            };
            rows.push(rowObj);
            if (i % 50 === 0) setProgress(true, Math.min(95, Math.round(i / total * 100)), i, total, 'Mempersiapkan payload...');
          }

          setProgress(true, 96, rows.length, rows.length, 'Menyiapkan preview import...');
          // send to backend
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) {
            throw new Error('Backend tidak aktif. Aktifkan backend untuk mengirim import ke server.');
          }
          const datasetType = 'DATA_TERPADU';
          const source = 'DATA_AWAL';
          const embeddedFinalColumns = true;
          if (!rows.length) throw new Error('Tidak ada baris data yang dapat diimport.');
          if (duplicateNips.size) {
            throw new Error('Ditemukan NIP duplikat: ' + duplicateNips.size + ' NIP. Perbaiki file sebelum import.');
          }
          const select = document.getElementById('mpImportPeriod');
          const inferredPeriodId = inferImportPeriod(rows);
          const periodId = (select ? select.value : '') || inferredPeriodId || '';
          if (!periodId) throw new Error('Tidak dapat menentukan periode arsip dari kolom bulan Excel. Pilih periode arsip secara manual.');
          const payload = {
            rows: rows,
            source: source,
            metadata: {
              periode_id: periodId,
              periode: inferredPeriodId ? inferredPeriodId.replace(/^RET-/, '').replace(/-\d{2}$/, '') : (rows.find(r => r && r.periode) || {}).periode,
              filename: file.name,
              source_file_name: file.name,
              file_hash: file_hash,
              source: source,
              dataset_type: 'DATA_AWAL',
              embedded_final_columns: true
            },
            created_by: (EVKIN.user && EVKIN.user.username) ? EVKIN.user.username : 'ui'
          };
          const url = new URL('/pengembalian/archive/preview', EVKIN.exportBackend.apiBase).toString();
          const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
          const json = await resp.json().catch(() => ({}));
          if (!resp.ok) {
            if (json && json.detail) throw new Error(json.detail);
            throw new Error('Gagal import: ' + (resp.statusText || resp.status));
          }
          pendingImport = payload;
          const preview = document.getElementById('mpImportPreview');
          msg.innerHTML = '<div class="alert info">Preview selesai. Data belum disimpan ke database.</div>';
          const validationErrors = (json.errors || json.validation_errors || []).slice(0, 20);
          const duplicateDetails = (json.duplicates || []).slice(0, 20);
          const rounding = json.rounding_reconciliation || { fields: [] };
          const roundingDetails = (rounding.fields || []).map(item =>
            `<tr><td>${EVKIN.util.esc(String(item.field || ''))}</td><td>${EVKIN.util.esc(String(item.raw_total || 0))}</td><td>${EVKIN.util.esc(String(item.rounded_total || 0))}</td><td>${EVKIN.util.esc(String(item.difference || 0))}</td><td>${EVKIN.util.esc(String(item.status || ''))}</td></tr>`
          ).join('');
          preview.innerHTML = `<div class="card"><h4>Preview ${EVKIN.util.esc(datasetType)}</h4>
            <p>File: ${EVKIN.util.esc(file.name)} | Sheet: ${EVKIN.util.esc(sheetName)} | Dataset: ${EVKIN.util.esc(datasetType)} | Total: ${json.total || rows.length} | Valid: ${json.valid_count || 0} | Invalid: ${json.invalid_count || 0} | Duplikat: ${json.duplicate_count || 0}</p>
            ${embeddedFinalColumns ? '<div class="alert info">Kolom awal akan diarsipkan sebagai DATA_AWAL dan kolom FINAL akan dibentuk sebagai DATA_PENYESUAIAN. Tidak ada overwrite.</div>' : ''}
            <p>Arsip: DATA AWAL + DATA PENYESUAIAN dari kolom FINAL | Periode: ${EVKIN.util.esc((json.periods || []).join(', ') || '-')} | Total Pengembalian: ${EVKIN.util.esc(String(json.total_pengembalian || 0))}</p>
            <div class="alert ${rounding.status === 'VALID' ? 'success' : 'error'}"><strong>PEMBULATAN NOMINAL — ${EVKIN.util.esc(String(rounding.status || 'TIDAK TERSEDIA'))}</strong><br>Total record: ${Number(rounding.total_records || 0).toLocaleString('id-ID')} · Record desimal: ${Number(rounding.decimal_record_count || 0).toLocaleString('id-ID')} · Record disesuaikan: ${Number(rounding.adjusted_record_count || 0).toLocaleString('id-ID')} · Nilai 0 berubah: ${Number(rounding.zero_modified_count || 0).toLocaleString('id-ID')}</div>
            ${roundingDetails ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Kolom</th><th>Total sebelum</th><th>Total sesudah</th><th>Selisih</th><th>Status</th></tr></thead><tbody>${roundingDetails}</tbody></table></div>` : ''}
            ${validationErrors.length ? '<details open><summary>Error validasi (maks. 20)</summary><ul>' + validationErrors.map(item => '<li>Baris ' + EVKIN.util.esc(String(item.row || '-')) + ': ' + EVKIN.util.esc((item.flags || []).join(', ')) + '</li>').join('') + '</ul></details>' : ''}
            ${duplicateDetails.length ? '<details><summary>Detail duplikat (maks. 20)</summary><ul>' + duplicateDetails.map(item => '<li>' + EVKIN.util.esc(String(item.comparison_key || '-')) + ' (' + EVKIN.util.esc(String(item.count || 0)) + 'x)</li>').join('') + '</ul></details>' : ''}
            ${json.warnings && json.warnings.length ? '<div class="alert warn">' + json.warnings.map(EVKIN.util.esc).join(', ') + '</div>' : ''}
            <button id="mpConfirmImport" class="btn btn-primary" ${json.valid === false ? 'disabled' : ''}>Konfirmasi dan Import</button>
            <button id="mpCancelImport" class="btn btn-secondary">Batalkan</button></div>`;
          document.getElementById('mpConfirmImport').onclick = async function () {
            if (!pendingImport) return;
            const confirmed = window.confirm(
              'Simpan hasil preview ke arsip ' + source + '? Data akan ditambahkan secara append-only.'
            );
            if (!confirmed) return;
            this.disabled = true;
            try {
              const importUrl = new URL('/pengembalian/archive/import', EVKIN.exportBackend.apiBase).toString();
              const importResp = await fetch(importUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pendingImport) });
              const importJson = await importResp.json().catch(() => ({}));
              if (!importResp.ok) throw new Error(importJson.detail || 'Gagal import');
              msg.innerHTML = '<div class="alert success">Import berhasil. ' + (embeddedFinalColumns ? 'DATA_AWAL dan DATA_PENYESUAIAN dari kolom FINAL telah diarsipkan.' : '') + ' Batch id: ' + (importJson.batch_id || importJson.import_id || importJson.initial?.batch_id || '-') + '. Total: ' + (importJson.total || rows.length) + '</div>';
              preview.innerHTML = '';
              pendingImport = null;
              EVKIN.toast('Import ' + source + ' berhasil', 'success');
            } catch (err) {
              this.disabled = false;
              msg.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
            }
          };
          document.getElementById('mpCancelImport').onclick = function () {
            pendingImport = null;
            preview.innerHTML = '';
            msg.innerHTML = '<div class="alert warn">Import dibatalkan. Tidak ada data yang disimpan.</div>';
          };

        } catch (err) {
          document.getElementById('mpImportMsg').innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
        } finally {
          pickBtn.disabled = false;
          setProgress(false, 0, 0, 0);
        }
      }

    };

    if (document.getElementById('mpViewCases')) document.getElementById('mpViewCases').onclick = async function () {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = '<p>Mengambil daftar case dari backend...</p>';
      try {
        if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
        const res = await fetch(new URL('/api/pengembalian/cases', EVKIN.exportBackend.apiBase).toString());
        if (!res.ok) throw new Error('Gagal ambil daftar case');
        const json = await res.json();
        const rows = json.rows || [];
        cont.innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr><th>case_id</th><th>nip</th><th>periode</th><th>komponen</th><th>nominal</th></tr></thead><tbody>${rows.map(r=>`<tr data-case="${r.case_id}"><td>${r.case_id}</td><td>${r.nip}</td><td>${r.periode}</td><td>${r.komponen}</td><td>${r.nominal || ''}</td></tr>`).join('')}</tbody></table></div>`;
        // make rows clickable to open detail
        cont.querySelectorAll('tr[data-case]').forEach(tr => tr.onclick = () => {
          const cid = tr.dataset.case;
          EVKIN.go('master-pengembalian');
          // show dasar for selected case
          showDasarForCase(cid);
        });
      } catch (e) {
        cont.innerHTML = '<div class="alert error">' + EVKIN.util.esc(e.message) + '</div>';
      }
    };

    // helper to show dasar by case
    async function showDasarForCase(case_id) {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = '<p>Mengambil dasar perhitungan untuk case ' + EVKIN.util.esc(case_id) + ' ...</p>';
      try {
        if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
        const res = await fetch(new URL('/api/pengembalian/dasar/' + encodeURIComponent(case_id), EVKIN.exportBackend.apiBase).toString());
        if (!res.ok) throw new Error('Gagal ambil dasar perhitungan');
        const json = await res.json();
        const rows = json.rows || [];
        if (!rows.length) {
          cont.innerHTML = '<div class="alert info">Tidak ada dasar perhitungan untuk case ' + EVKIN.util.esc(case_id) + '</div>';
          return;
        }
        cont.innerHTML = `<h3>Dasar Perhitungan — ${EVKIN.util.esc(case_id)}</h3><div class="table-wrap"><table class="data-table"><thead><tr><th>id</th><th>periode</th><th>komponen</th><th>nilai_awal</th><th>nilai_dasar</th><th>nilai_penyesuaian</th><th>tukin_seharusnya</th><th>nominal_pengembalian</th><th>calculated_at</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.id}</td><td>${r.periode || ''}</td><td>${r.komponen || ''}</td><td>${r.nilai_awal || ''}</td><td>${r.nilai_dasar || ''}</td><td>${r.nilai_penyesuaian || ''}</td><td>${r.tukin_seharusnya || ''}</td><td>${r.nominal_pengembalian || ''}</td><td>${r.calculated_at || ''}</td><td><button class="btn btn-sm btn-secondary" data-id="${r.id}">Buat Penyesuaian dari Baris</button></td></tr>`).join('')}</tbody></table></div>`;
        // attach handlers for quick penyesuaian
        cont.querySelectorAll('button[data-id]').forEach(btn => btn.onclick = (e) => {
          const id = btn.dataset.id;
          const row = rows.find(x=>x.id === id);
          if (row) openPenyesuaianFormWithRow(case_id, row);
        });
      } catch (err) {
        cont.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
      }
    }

    function openPenyesuaianFormWithRow(case_id, row) {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `<h3>Buat Penyesuaian — Case ${EVKIN.util.esc(case_id)}</h3>
        <div class="form-row"><div><label>Case ID</label><input id="py_case_id" value="${EVKIN.util.esc(case_id)}" readonly/></div><div><label>NIP</label><input id="py_nip" value="${EVKIN.util.esc(row.nip || '')}"/></div></div>
        <div class="form-row"><div><label>Periode</label><input id="py_periode" value="${EVKIN.util.esc(row.periode || '')}"/></div><div><label>Komponen</label><input id="py_komponen" value="${EVKIN.util.esc(row.komponen || '')}"/></div></div>
        <div class="form-row"><div><label>Nominal Sebelum</label><input id="py_sebelum" value="${EVKIN.util.esc(row.nilai_awal || '')}"/></div><div><label>Nominal Setelah</label><input id="py_setelah" value=""/></div></div>
        <div class="form-row"><div><label>Selisih</label><input id="py_selisih" readonly/></div><div><label>Jenis Penyesuaian</label><select id="py_jenis"><option>ABSENSI</option><option>WITA</option><option>WIT</option><option>TENDIK</option><option>SP2D</option><option>CUTI</option><option>IZIN</option><option>SKP</option><option>MANUAL</option><option>LAINNYA</option></select></div></div>
        <div class="form-row"><div style="flex:2"><label>Alasan</label><input id="py_alasan"/></div><div style="align-self:flex-end"><button id="py_submit" class="btn btn-primary">Kirim Penyesuaian</button></div></div>
      `;
      const sebelum = cont.querySelector('#py_sebelum');
      const setelah = cont.querySelector('#py_setelah');
      const sel = cont.querySelector('#py_selisih');
      function recalc() { const a = parseFloat(sebelum.value) || 0; const b = parseFloat(setelah.value) || 0; sel.value = (b - a).toString(); }
      setelah.oninput = recalc;
      cont.querySelector('#py_submit').onclick = async function () {
        const payload = [{
          case_id: cont.querySelector('#py_case_id').value,
          nip: cont.querySelector('#py_nip').value,
          periode: cont.querySelector('#py_periode').value,
          komponen: cont.querySelector('#py_komponen').value,
          nominal_sebelum: parseFloat(cont.querySelector('#py_sebelum').value) || 0,
          nominal_setelah: parseFloat(cont.querySelector('#py_setelah').value) || 0,
          selisih: parseFloat(cont.querySelector('#py_selisih').value) || 0,
          jenis_penyesuaian: cont.querySelector('#py_jenis').value,
          alasan_penyesuaian: cont.querySelector('#py_alasan').value,
          reference_id: 'REF-' + Date.now()
        }];
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const res = await fetch(new URL('/pengembalian/penyesuaian', EVKIN.exportBackend.apiBase).toString(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: payload, created_by: (EVKIN.user && EVKIN.user.username) ? EVKIN.user.username : 'ui' }) });
          const j = await res.json();
          if (!res.ok) throw new Error(j.detail || 'Gagal kirim penyesuaian');
          cont.innerHTML = '<div class="alert success">Penyesuaian terkirim. ' + (j.inserted ? j.inserted + ' baris' : '') + '</div>';
        } catch (err) {
          cont.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
        }
      };
    }

    if (document.getElementById('mpCompare')) document.getElementById('mpCompare').onclick = async function () {
      const cont = document.getElementById('mpContent');
       cont.innerHTML = `<p>Bandingkan snapshot DATA_AWAL dan DATA_PENYESUAIAN. Kunci minimal NIP + Tahun SP2D dan diperluas bila tersedia.</p>
      <div class="form-row"><input id="cmpRunName" placeholder="Nama run"/></div>
        <div class="form-row"><button id="cmpGo" class="btn">Jalankan Compare</button></div>
      `;
      document.getElementById('cmpGo').onclick = async function () {
        const runName = document.getElementById('cmpRunName').value || 'quick-compare';
        cont.innerHTML = '<p>Menjalankan compare...</p>';
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const body = { run_name: runName, source_a: 'DATA_AWAL', source_b: 'DATA_PENYESUAIAN', created_by: (EVKIN.user && EVKIN.user.username) ? EVKIN.user.username : 'ui' };
          const res = await fetch(new URL('/pengembalian/archive/compare', EVKIN.exportBackend.apiBase).toString(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          const json = await res.json();
          if (!res.ok) throw new Error(json.detail || 'Compare API error');
          cont.innerHTML = `<pre>${JSON.stringify(json, null, 2)}</pre>`;
        } catch (err) {
          cont.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
        }
      };

    };

    document.getElementById('mpArchiveList').onclick = async function () {
        const cont = document.getElementById('mpContent');
        cont.innerHTML = `<h3>Arsip Pengembalian</h3>
          <div class="form-row">
            <input id="arcSource" value="DATA_AWAL" placeholder="Source">
            <input id="arcNip" placeholder="NIP">
            <input id="arcNama" placeholder="Nama">
            <input id="arcYear" placeholder="Tahun SP2D">
            <input id="arcPeriod" placeholder="Periode">
            <input id="arcProvince" placeholder="Provinsi">
            <input id="arcUnit" placeholder="KdanakSatker">
            <input id="arcStatus" placeholder="Status Perubahan">
            <input id="arcType" placeholder="Jenis Perubahan">
            <button id="arcApply" class="btn btn-primary">Terapkan Filter</button>
          </div>
          <div class="form-row">
            <button id="arcLoadHistory" class="btn btn-secondary">Muat History Import</button>
            <button id="arcClearDatabase" class="btn btn-danger">Hapus Database Archive</button>
            <button id="arcDownloadAwal" class="btn btn-secondary">Download Data Awal</button>
            <button id="arcDownloadPenyesuaian" class="btn btn-secondary">Download Penyesuaian</button>
            <button id="arcDownloadFinal" class="btn btn-secondary">Download Final Database</button>
            <button id="arcDownloadChanged" class="btn btn-secondary">Download Hanya Berubah</button>
          </div><div id="arcImportHistory"><p class="muted">Status sumber import belum dimuat.</p></div><div id="arcResult"><p>Gunakan filter untuk memuat arsip.</p></div>`;
        async function loadImportHistory() {
          const target = document.getElementById('arcImportHistory');
          target.innerHTML = '<p>Memuat history import...</p>';
          try {
            const response = await fetch(new URL('/pengembalian/archive/history?limit=100', EVKIN.exportBackend.apiBase));
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Gagal memuat history import');
            const imports = data.imports || [];
            target.innerHTML = `<h4>History / Status Sumber</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>Waktu</th><th>Sumber</th><th>File</th><th>Periode</th><th>Baris</th><th>Status</th><th>Aksi</th></tr></thead><tbody>${imports.map(item => {
              const active = item.is_active === true || item.is_active === 1;
              const id = EVKIN.util.esc(String(item.import_id || ''));
              return `<tr><td>${EVKIN.util.esc(String(item.imported_at || '-'))}</td><td>${EVKIN.util.esc(String(item.source_type || '-'))}</td><td>${EVKIN.util.esc(String(item.filename || item.source_file_name || '-'))}</td><td>${EVKIN.util.esc(String(item.periode_id || '-'))}</td><td>${item.row_count || 0}</td><td><strong>${active ? 'ACTIVE' : 'INACTIVE'}</strong></td><td><button class="btn btn-sm ${active ? 'btn-secondary' : 'btn-primary'} arc-toggle-import" data-import-id="${id}" data-active="${active ? 'false' : 'true'}">${active ? 'Nonaktifkan' : 'Aktifkan'}</button></td></tr>`;
            }).join('') || '<tr><td colspan="7">Belum ada history import.</td></tr>'}</tbody></table></div>`;
            target.querySelectorAll('.arc-toggle-import').forEach(button => {
              button.onclick = async function () {
                this.disabled = true;
                try {
                  const response = await fetch(new URL('/pengembalian/archive/imports/' + encodeURIComponent(this.dataset.importId) + '/active', EVKIN.exportBackend.apiBase), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: this.dataset.active === 'true' }) });
                  const data = await response.json();
                  if (!response.ok) throw new Error(data.detail || 'Gagal mengubah status sumber');
                  EVKIN.toast(data.is_active ? 'Sumber diaktifkan. Sumber lain pada periode yang sama dinonaktifkan.' : 'Sumber dinonaktifkan.', 'success');
                  await loadImportHistory();
                  await loadArchive();
                } catch (error) { EVKIN.toast(error.message, 'error'); this.disabled = false; }
              };
            });
          } catch (error) { target.innerHTML = '<div class="alert error">' + EVKIN.util.esc(error.message) + '</div>'; }
        }
        document.getElementById('arcLoadHistory').onclick = loadImportHistory;
        document.getElementById('arcClearDatabase').onclick = async function () {
          const required = 'RESET DATABASE MASTER PENGEMBALIAN';
          const confirmation = window.prompt(`Tindakan ini menghapus seluruh archive, history, perbandingan, dan data final. Ketik ${required} untuk melanjutkan:`);
          if (String(confirmation || '').trim().toUpperCase() !== required) return;
          this.disabled = true;
          try {
            const response = await fetch(new URL('/pengembalian/archive/database/clear', EVKIN.exportBackend.apiBase), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmation }) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Gagal menghapus database archive');
            EVKIN.toast(`Database archive dihapus (${data.deleted_rows || 0} baris).`, 'success');
            await loadImportHistory();
            await loadArchive();
          } catch (error) { EVKIN.toast(error.message, 'error'); this.disabled = false; }
        };
        loadImportHistory();
        async function loadArchive() {
          const result = document.getElementById('arcResult');
          result.innerHTML = '<p>Memuat arsip...</p>';
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const params = new URLSearchParams({
            source: document.getElementById('arcSource').value || 'DATA_AWAL',
            nip: document.getElementById('arcNip').value,
            nama: document.getElementById('arcNama').value,
            tahun_sp2d: document.getElementById('arcYear').value,
            periode: document.getElementById('arcPeriod').value,
            provinsi: document.getElementById('arcProvince').value,
            kdanaksatker: document.getElementById('arcUnit').value,
            status_perubahan: document.getElementById('arcStatus').value,
            jenis_perubahan: document.getElementById('arcType').value
          });
          [...params].forEach(([key, value]) => { if (!value) params.delete(key); });
          const res = await fetch(new URL('/pengembalian/archive/list?' + params.toString(), EVKIN.exportBackend.apiBase).toString());
          const json = await res.json();
          if (!res.ok) throw new Error(json.detail || 'Gagal memuat arsip');
          const rows = json.rows || [];
          result.innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Tahun SP2D</th><th>Periode</th><th>Komponen</th><th>Total Tukin</th><th>Flag</th><th>Aksi</th></tr></thead><tbody>${rows.map(r => `<tr><td>${EVKIN.util.esc(r.nip || '')}</td><td>${EVKIN.util.esc(r.nama || '')}</td><td>${r.tahun_sp2d || ''}</td><td>${EVKIN.util.esc(r.periode || '')}</td><td>${EVKIN.util.esc(r.komponen || '')}</td><td>${r.total_tukin == null ? '' : r.total_tukin}</td><td>${EVKIN.util.esc((r.validation_flags || []).join(', '))}</td><td><button class="btn btn-sm btn-secondary arc-detail" data-row-id="${EVKIN.util.esc(r.row_id || '')}">Detail</button> <button class="btn btn-sm btn-danger arc-delete" data-row-id="${EVKIN.util.esc(r.row_id || '')}" data-name="${EVKIN.util.esc(r.nama || r.nip || '')}">Hapus</button></td></tr>`).join('') || '<tr><td colspan="8">Tidak ada data arsip.</td></tr>'}</tbody></table></div>`;
          result.querySelectorAll('.arc-delete').forEach(button => {
            button.onclick = async function () {
              const rowId = this.dataset.rowId;
              const required = 'HAPUS ARSIP ' + rowId;
              const confirmation = window.prompt(`Hapus arsip ${this.dataset.name || rowId}? Tindakan ini tidak dapat dibatalkan. Ketik ${required} untuk melanjutkan:`);
              if (String(confirmation || '').trim().toUpperCase() !== required.toUpperCase()) return;
              this.disabled = true;
              try {
                const source = document.getElementById('arcSource').value || 'DATA_AWAL';
                const deleteUrl = new URL('/pengembalian/archive/detail/' + encodeURIComponent(rowId) + '?source=' + encodeURIComponent(source), EVKIN.exportBackend.apiBase);
                const response = await fetch(deleteUrl.toString(), { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmation }) });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.detail || 'Gagal menghapus arsip');
                EVKIN.toast('Data arsip berhasil dihapus', 'success');
                await loadArchive();
              } catch (err) {
                EVKIN.toast(err.message, 'error');
                this.disabled = false;
              }
            };
          });
          result.querySelectorAll('.arc-detail').forEach(button => {
            button.onclick = async function () {
              const rowId = this.dataset.rowId;
              try {
                const detailUrl = new URL('/pengembalian/archive/detail/' + encodeURIComponent(rowId) + '?source=' + encodeURIComponent(document.getElementById('arcSource').value || 'DATA_AWAL'), EVKIN.exportBackend.apiBase);
                const detailResponse = await fetch(detailUrl.toString());
                const detailJson = await detailResponse.json();
                if (!detailResponse.ok) throw new Error(detailJson.detail || 'Gagal memuat detail SDM');
                const detail = detailJson.row || {};
                const refs = detail.raw_data || {};
                const dailyUrl = new URL('/pengembalian/archive/daily-detail/' + encodeURIComponent(detail.nip || '') +
                  '?periode=' + encodeURIComponent(detail.periode || ''), EVKIN.exportBackend.apiBase);
                const dailyResponse = await fetch(dailyUrl.toString());
                const dailyJson = dailyResponse.ok ? await dailyResponse.json() : { tabs: {} };
                const dailyRows = (dailyJson.tabs || {}).data_dasar_harian || [];
                const changedRows = (dailyJson.tabs || {}).perubahan_absensi || [];
                const dailyTable = rows => rows.map(row => `<tr><td>${EVKIN.util.esc(row.tanggal || '')}</td><td>${EVKIN.util.esc(row.jam_masuk_awal || row.jam_masuk_penyesuaian || '')}</td><td>${EVKIN.util.esc(row.jam_masuk_penyesuaian || '')}</td><td>${EVKIN.util.esc(row.status || '')}</td><td>${EVKIN.util.esc((row.changed_fields || []).join(', '))}</td></tr>`).join('');
                result.innerHTML = `<div class="card"><button id="arcBack" class="btn btn-secondary">Kembali ke Arsip</button>
                  <h4>Detail SDM: ${EVKIN.util.esc(detail.nama || detail.nip || '')}</h4>
                  <p>NIP: ${EVKIN.util.esc(detail.nip || '-')} | Tahun SP2D: ${detail.tahun_sp2d || '-'} | Periode: ${EVKIN.util.esc(detail.periode || '-')}</p>
                  <div class="mp-tabs"><button class="btn mp-tab active">SUMMARY</button><button class="btn mp-tab">HISTORY PENGEMBALIAN</button><button class="btn mp-tab">DATA AWAL</button><button class="btn mp-tab">DATA PENYESUAIAN</button><button class="btn mp-tab">PERUBAHAN ABSENSI</button><button class="btn mp-tab">DATA DASAR HARIAN</button></div>
                  <h5>Nilai dan Validasi Tukin</h5>
                  <pre>${EVKIN.util.esc(JSON.stringify({ total_tukin: detail.total_tukin, tukin_validation: detail.tukin_validation, calculated_total_potongan_absen: detail.calculated_total_potongan_absen, calculated_total_potongan_tukin: detail.calculated_total_potongan_tukin }, null, 2))}</pre>
                  <h5>Flag</h5><p>${EVKIN.util.esc((detail.validation_flags || []).join(', ') || 'TIDAK BERUBAH')}</p>
                  <h5>Traceability</h5><p>Daily: ${EVKIN.util.esc(detail.daily_ref || refs.daily_ref || '-')} | Monthly: ${EVKIN.util.esc(detail.monthly_ref || refs.monthly_ref || '-')} | Absence: ${EVKIN.util.esc(detail.absence_ref || refs.absence_ref || '-')} | Total Tukin: ${EVKIN.util.esc(detail.total_tukin_ref || refs.total_tukin_ref || '-')}</p>
                  <h5>Perubahan Absensi</h5><table class="table"><thead><tr><th>Tanggal</th><th>Jam Masuk Awal</th><th>Jam Masuk Penyesuaian</th><th>Status</th><th>Changed Fields</th></tr></thead><tbody>${dailyTable(changedRows)}</tbody></table>
                  <h5>Data Dasar Harian</h5><table class="table"><thead><tr><th>Tanggal</th><th>Jam Masuk Awal</th><th>Jam Masuk Penyesuaian</th><th>Status</th><th>Changed Fields</th></tr></thead><tbody>${dailyTable(dailyRows)}</tbody></table>
                  <h5>Raw Data Sumber</h5><pre>${EVKIN.util.esc(JSON.stringify(refs, null, 2))}</pre></div>`;
                document.getElementById('arcBack').onclick = loadArchive;
              } catch (err) {
                result.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
              }
            };
          });
        } catch (err) {
          result.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
        }
        }
        document.getElementById('arcApply').onclick = loadArchive;
        function download(source, onlyChanged) {
          const params = new URLSearchParams({
            source: source || '',
            only_changed: onlyChanged ? 'true' : 'false',
            nip: document.getElementById('arcNip').value,
            nama: document.getElementById('arcNama').value,
            tahun_sp2d: document.getElementById('arcYear').value,
            periode: document.getElementById('arcPeriod').value,
            provinsi: document.getElementById('arcProvince').value,
            kdanaksatker: document.getElementById('arcUnit').value,
            status_perubahan: document.getElementById('arcStatus').value,
            jenis_perubahan: document.getElementById('arcType').value
          });
          [...params].forEach(([key, value]) => { if (!value) params.delete(key); });
          window.open(new URL('/pengembalian/archive/download?' + params.toString(), EVKIN.exportBackend.apiBase).toString(), '_blank');
        }
        document.getElementById('arcDownloadAwal').onclick = () => download('DATA_AWAL', false);
        document.getElementById('arcDownloadPenyesuaian').onclick = () => download('DATA_PENYESUAIAN', false);
        document.getElementById('arcDownloadFinal').onclick = () => download('', false);
        document.getElementById('arcDownloadChanged').onclick = () => download('', true);
    };

    document.getElementById('mpArchiveDashboard').onclick = async function () {
        const cont = document.getElementById('mpContent');
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const res = await fetch(new URL('/pengembalian/archive/dashboard?source=DATA_FINAL', EVKIN.exportBackend.apiBase).toString());
          const json = await res.json();
          if (!res.ok) throw new Error(json.detail || 'Gagal memuat dashboard');
          const money = value => Number(value || 0).toLocaleString('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 });
          cont.innerHTML = `<h3>Dashboard Arsip</h3><div class="tool-stats">
            <div class="tool-stat"><span class="label">Total SDM</span><span class="value">${json.total_sdm || 0}</span></div>
            <div class="tool-stat"><span class="label">SDM Berubah</span><span class="value">${json.sdm_berubah || 0}</span></div>
            <div class="tool-stat"><span class="label">SDM Tidak Berubah</span><span class="value">${json.sdm_tidak_berubah || 0}</span></div>
            <div class="tool-stat"><span class="label">Total Pengembalian Tukin Awal</span><span class="value">${money(json.total_pengembalian_tukin_awal ?? json.total_potongan_awal)}</span></div>
            <div class="tool-stat"><span class="label">Total Pengembalian Tukin Final</span><span class="value">${money(json.total_pengembalian_tukin_final ?? json.total_potongan_penyesuaian)}</span></div>
            <div class="tool-stat"><span class="label">Selisih Pengembalian Tukin</span><span class="value">${money(json.selisih_pengembalian_tukin ?? json.total_selisih)}</span></div>
            <div class="tool-stat"><span class="label">Uang Makan Awal</span><span class="value">${money(json.total_pengembalian_uang_makan_awal)}</span></div>
            <div class="tool-stat"><span class="label">Uang Makan Final</span><span class="value">${money(json.total_pengembalian_uang_makan_final)}</span></div>
            <div class="tool-stat"><span class="label">Selisih Uang Makan</span><span class="value">${money(json.selisih_pengembalian_uang_makan)}</span></div>
            <div class="tool-stat"><span class="label">Total Tukin + Uang Makan Final</span><span class="value">${money(json.total_pengembalian_tukin_uang_makan)}</span></div>
            <div class="tool-stat"><span class="label">Total Data Berubah</span><span class="value">${json.sdm_berubah || 0}</span></div>
            <div class="tool-stat"><span class="label">Duplikasi Awal</span><span class="value">${json.duplicate_awal || 0}</span></div>
            <div class="tool-stat"><span class="label">Duplikasi Penyesuaian</span><span class="value">${json.duplicate_penyesuaian || 0}</span></div>
          </div>`;
        } catch (err) {
          cont.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
        }
    };

    document.getElementById('mpBpkReconciliation').onclick = async function () {
      const cont = document.getElementById('mpContent');
      const base = EVKIN.exportBackend.apiBase;
      const money = value => Number(value || 0).toLocaleString('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 });
      async function loadBpk(batch) {
        cont.innerHTML = '<p>Memuat rekonsiliasi BPK berdasarkan kolom Batch...</p>';
        try {
          const params = new URLSearchParams();
          if (batch) params.set('bpk_batch', batch);
          const endpoint = '/pengembalian/archive/bpk-reconciliation' + (params.size ? '?' + params.toString() : '');
          const res = await fetch(new URL(endpoint, base));
          const json = await res.json();
          if (!res.ok) throw new Error(json.detail || 'Gagal memuat rekonsiliasi BPK');
          const k = json.kpi || {};
          const status = k.status_summary || {};
          const statusRow = (label, value) => {
            const item = status[value] || {};
            return `<tr><td>${label}</td><td>${item.jumlah_sdm || 0}</td><td>${item.jumlah_data || 0}</td><td>${money(item.nominal_awal)}</td><td>${money(item.nominal_final)}</td><td>${money(item.selisih_nominal)}</td></tr>`;
          };
          const detailRows = (json.rows || []).map(row => `<tr><td>${EVKIN.util.esc(row.identity.nip || '')}</td><td>${EVKIN.util.esc(row.identity.nama || '')}</td><td>${EVKIN.util.esc(row.identity.periode || '')}</td><td>${EVKIN.util.esc(row.reconciliation_batch || '')}</td><td>${money(row.nilai_awal)}</td><td>${money(row.nilai_final)}</td><td>${money(row.selisih)}</td><td>${EVKIN.util.esc((row.changed_fields || []).join(', '))}</td><td>${EVKIN.util.esc(row.status_compare || '')}</td></tr>`).join('');
          const batchOptions = (json.available_batches || []).map(item => `<option value="${EVKIN.util.esc(item)}" ${json.selected_batch === item ? 'selected' : ''}>${EVKIN.util.esc(item)}</option>`).join('');
          const batchRows = (json.batch_summaries || []).map(item => `<tr><td>${EVKIN.util.esc(item.batch)}</td><td>${item.jumlah_sdm_awal_send_bpk || 0}</td><td>${item.jumlah_sdm_berubah || 0}</td><td>${item.jumlah_tidak_berubah || 0}</td><td>${money(item.total_pengembalian_awal)}</td><td>${money(item.total_pengembalian_final)}</td><td>${money(item.selisih_nominal)}</td></tr>`).join('');
          cont.innerHTML = `<h3>Rekonsiliasi BPK per Batch</h3>
            <p class="muted">Batch dibaca dari kolom <strong>Batch</strong> pada data yang dikirim ke BPK. Nilai awal dibandingkan dengan nilai setelah penyesuaian.</p>
            <div class="form-row"><label>Batch BPK <select id="mpBpkBatch"><option value="">Semua Batch</option>${batchOptions}</select></label><button id="mpBpkExport" class="btn btn-primary">Export XLSX Hasil Filter</button></div>
            <div class="tool-stats">
              <div class="tool-stat"><span class="label">SDM Awal</span><span class="value">${k.jumlah_sdm_awal_send_bpk || 0}</span></div>
              <div class="tool-stat"><span class="label">SDM Final Aktif</span><span class="value">${k.jumlah_sdm_final || 0}</span></div>
              <div class="tool-stat"><span class="label">Nominal Sebelum</span><span class="value">${money(k.total_pengembalian_awal)}</span></div>
              <div class="tool-stat"><span class="label">Nominal Sesudah</span><span class="value">${money(k.total_pengembalian_final)}</span></div>
              <div class="tool-stat"><span class="label">Selisih</span><span class="value">${money(k.selisih_nominal)}</span></div>
            </div>
            <h4>Ringkasan Status ${json.selected_batch ? '— ' + EVKIN.util.esc(json.selected_batch) : 'Semua Batch'}</h4>
            <div class="table-wrap"><table class="data-table"><thead><tr><th>Status</th><th>Jumlah SDM</th><th>Jumlah Data</th><th>Nominal Sebelum</th><th>Nominal Sesudah</th><th>Selisih</th></tr></thead><tbody>
              ${statusRow('Berubah', 'BERUBAH')}${statusRow('Tidak Berubah', 'TIDAK BERUBAH')}${statusRow('Data Baru', 'DATA BARU')}${statusRow('Data Hilang', 'DATA HILANG')}${statusRow('Perlu Review', 'NEED REVIEW')}
            </tbody></table></div>
            ${json.selected_batch ? '' : `<h4>Rekap Semua Batch</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>Batch</th><th>SDM</th><th>Berubah</th><th>Tidak Berubah</th><th>Nominal Sebelum</th><th>Nominal Sesudah</th><th>Selisih</th></tr></thead><tbody>${batchRows}</tbody></table></div>`}
            <h4>Detail Rekonsiliasi</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Periode</th><th>Batch</th><th>Nilai Sebelum</th><th>Nilai Sesudah</th><th>Selisih</th><th>Kolom Berubah</th><th>Status</th></tr></thead><tbody>${detailRows || '<tr><td colspan="9" class="muted">Tidak ada data pada batch ini.</td></tr>'}</tbody></table></div>`;
          document.getElementById('mpBpkBatch').onchange = event => loadBpk(event.target.value);
          document.getElementById('mpBpkExport').onclick = () => window.open(new URL('/pengembalian/archive/bpk-reconciliation/download' + (params.size ? '?' + params.toString() : ''), base).toString(), '_blank');
        } catch (err) {
          cont.innerHTML = '<div class="alert error">' + EVKIN.util.esc(err.message) + '</div>';
        }
      }
      loadBpk('');
    };

    if (document.getElementById('mpAudit')) document.getElementById('mpAudit').onclick = function () {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = '<p>Audit viewer: buka menu Audit.</p>';
      // delegate to audit module if exists
      if (EVKIN.auditMod) EVKIN.go('audit-viewer');
    };

    // RETURN-2 .. RETURN-5 handlers
    if (document.getElementById('mpReturn2')) document.getElementById('mpReturn2').onclick = function () { showReturn2UI(); };
    if (document.getElementById('mpReturn3')) document.getElementById('mpReturn3').onclick = function () { showReturn3UI(); };
    if (document.getElementById('mpReturn4')) document.getElementById('mpReturn4').onclick = function () { showReturn4UI(); };
    if (document.getElementById('mpReturn5')) document.getElementById('mpReturn5').onclick = function () { showReturn5UI(); };

    // RETURN-2: Dasar Perhitungan & Penyesuaian
    async function showReturn2UI() {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `
        <h3>RETURN-2 — Dasar Perhitungan & Penyesuaian</h3>
        <div class="card">
          <h4>Upload Dasar Perhitungan (snapshot)</h4>
          <p class="muted">Unggah file CSV/XLSX berisi hasil perhitungan dasar. Ini akan disimpan sebagai snapshot pada tabel pengembalian_dasar_perhitungan.</p>
          <input type="file" id="r2File" accept=".xlsx,.xls,.csv" /> <button id="r2Upload" class="btn">Upload</button>
        </div>
        <div class="card" style="margin-top:8px">
          <h4>Kelola Penyesuaian</h4>
          <p class="muted">Buat penyesuaian manual atau lihat penyesuaian per case.</p>
          <div class="form-row"><input id="r2_case_filter" placeholder="Masukkan case_id atau NIP untuk filter" /> <button id="r2_list_pen" class="btn">Daftar Penyesuaian</button></div>
          <div id="r2PenResult"></div>
        </div>
      `;

      document.getElementById('r2Upload').onclick = async function () {
        try {
          const f = document.getElementById('r2File').files && document.getElementById('r2File').files[0];
          if (!f) return EVKIN.toast('Pilih file terlebih dahulu', 'error');
          // read file as arraybuffer
          const ab = await f.arrayBuffer();
          const data = new Uint8Array(ab);
          const wb = XLSX.read(data, { type: 'array', raw: true });
          const sheet = wb.Sheets[wb.SheetNames[0]];
          const aoa = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true, defval: '' });
          if (!aoa || aoa.length < 2) throw new Error('File kosong');
          // map rows to objects (simple heuristic using first row as headers)
          const headers = aoa[0].map(h => String(h||'').trim());
          const rows = aoa.slice(1).map(r => {
            const obj = {};
            headers.forEach((h,i)=> obj[h] = r[i]);
            return obj;
          });
          // send to backend
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const url = new URL('/pengembalian/dasar', EVKIN.exportBackend.apiBase).toString();
          const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: rows, batch_meta: { uploaded_file: f.name }, created_by: (EVKIN.user && EVKIN.user.username) ? EVKIN.user.username : 'ui' }) });
          const j = await res.json().catch(()=>({}));
          if (!res.ok) throw new Error(j.detail || 'Gagal upload dasar');
          cont.querySelector('#r2PenResult').innerHTML = '<div class="alert success">Dasar perhitungan tersimpan. batch_id: '+(j.batch_id||'')+'</div>';
        } catch (err) {
          cont.querySelector('#r2PenResult').innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>';
        }
      };

      document.getElementById('r2_list_pen').onclick = async function () {
        const q = (document.getElementById('r2_case_filter').value || '').trim();
        const area = document.getElementById('r2PenResult');
        area.innerHTML = '<p>Memuat penyesuaian...</p>';
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const url = new URL('/pengembalian/penyesuaian/' + encodeURIComponent(q || ''), EVKIN.exportBackend.apiBase).toString();
          const res = await fetch(url);
          if (!res.ok) throw new Error('Gagal ambil penyesuaian');
          const j = await res.json();
          const rows = j.rows || j || [];
          if (!rows.length) { area.innerHTML = '<div class="alert info">Tidak ada penyesuaian</div>'; return; }
          area.innerHTML = '<div class="table-wrap"><table class="data-table"><thead><tr><th>id</th><th>case_id</th><th>nip</th><th>periode</th><th>selisih</th><th>jenis</th><th>alasan</th></tr></thead><tbody>' + rows.map(r=>`<tr><td>${r.id||''}</td><td>${r.case_id||''}</td><td>${r.nip||''}</td><td>${r.periode||''}</td><td>${r.selisih||r.nominal_setelah-r.nominal_sebelum||''}</td><td>${r.jenis_penyesuaian||''}</td><td>${r.alasan_penyesuaian||''}</td></tr>`).join('') + '</tbody></table></div>';
        } catch (err) {
          area.innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>';
        }
      };
    }

    // RETURN-3: Send BPK (stub UI)
    async function showReturn3UI() {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `
        <h3>RETURN-3 — Send BPK</h3>
        <div class="card">
          <p class="muted">Kirim instruksi/daftar ke BPK. Form ini hanya UI — backend harus menyediakan endpoint /pengembalian/send_bpk untuk eksekusi.</p>
          <div class="form-row"><input id="r3_case_id" placeholder="case_id (opsional untuk batch)" /><input id="r3_batch_name" placeholder="Nama batch" /></div>
          <div class="form-row"><textarea id="r3_payload" placeholder="Masukkan JSON array of items atau kosong untuk auto" style="width:100%;height:120px"></textarea></div>
          <div class="form-row"><button id="r3_send" class="btn">Kirim ke BPK</button></div>
          <div id="r3Result"></div>
        </div>
      `;
      document.getElementById('r3_send').onclick = async function () {
        const cont = document.getElementById('r3Result');
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const payloadText = document.getElementById('r3_payload').value || '';
          let payload = null;
          if (payloadText.trim()) payload = JSON.parse(payloadText);
          const body = { case_id: document.getElementById('r3_case_id').value || null, batch_name: document.getElementById('r3_batch_name').value || null, items: payload };
          const url = new URL('/pengembalian/send_bpk', EVKIN.exportBackend.apiBase).toString();
          const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          const j = await res.json().catch(()=>({}));
          if (!res.ok) throw new Error(j.detail || 'Send BPK failed');
          cont.innerHTML = '<div class="alert success">Sent to BPK. '+(j.batch_id?('batch_id: '+j.batch_id):'')+'</div>';
        } catch (err) {
          cont.innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>';
        }
      };
    }

    // RETURN-4: Send Bank (stub UI)
    async function showReturn4UI() {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `
        <h3>RETURN-4 — Send Bank</h3>
        <div class="card">
          <p class="muted">Kirim instruksi pembayaran ke Bank. Backend endpoint /pengembalian/send_bank diperlukan untuk aksi ini.</p>
          <div class="form-row"><input id="r4_batch_name" placeholder="Nama batch" /><input id="r4_file_ref" placeholder="Referensi file / batch" /></div>
          <div class="form-row"><textarea id="r4_payload" placeholder="Masukkan JSON array of items atau kosong untuk auto" style="width:100%;height:120px"></textarea></div>
          <div class="form-row"><button id="r4_send" class="btn">Kirim ke Bank</button></div>
          <div id="r4Result"></div>
        </div>
      `;
      document.getElementById('r4_send').onclick = async function () {
        const resBox = document.getElementById('r4Result');
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const payloadText = document.getElementById('r4_payload').value || '';
          let payload = null;
          if (payloadText.trim()) payload = JSON.parse(payloadText);
          const body = { batch_name: document.getElementById('r4_batch_name').value || null, file_ref: document.getElementById('r4_file_ref').value || null, items: payload };
          const url = new URL('/pengembalian/send_bank', EVKIN.exportBackend.apiBase).toString();
          const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
          const j = await res.json().catch(()=>({}));
          if (!res.ok) throw new Error(j.detail || 'Send Bank failed');
          resBox.innerHTML = '<div class="alert success">Sent to Bank. '+(j.batch_id?('batch_id: '+j.batch_id):'')+'</div>';
        } catch (err) {
          resBox.innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>';
        }
      };
    }

    // RETURN-5: Result Bank (viewer)
    async function showReturn5UI() {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `
        <h3>RETURN-5 — Result Bank</h3>
        <div class="card">
          <p class="muted">Lihat hasil proses bank (berhasil/gagal). Gunakan batch_id untuk memfilter.</p>
          <div class="form-row"><input id="r5_batch" placeholder="Masukkan batch_id" /> <button id="r5_get" class="btn">Ambil Hasil</button></div>
          <div id="r5Result"></div>
        </div>
      `;
      document.getElementById('r5_get').onclick = async function () {
        const resBox = document.getElementById('r5Result');
        resBox.innerHTML = '<p>Memuat hasil bank...</p>';
        try {
          if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
          const b = (document.getElementById('r5_batch').value || '').trim();
          if (!b) throw new Error('batch_id wajib diisi');
          const url = new URL('/pengembalian/result_bank/' + encodeURIComponent(b), EVKIN.exportBackend.apiBase).toString();
          const res = await fetch(url);
          if (!res.ok) throw new Error('Gagal ambil result bank');
          const j = await res.json();
          const rows = j.rows || j || [];
          if (!rows.length) { resBox.innerHTML = '<div class="alert info">Tidak ada hasil untuk batch ini</div>'; return; }
          resBox.innerHTML = '<div class="table-wrap"><table class="data-table"><thead><tr><th>case_id</th><th>nip</th><th>nominal</th><th>status</th><th>reason</th></tr></thead><tbody>' + rows.map(r=>`<tr><td>${r.case_id||''}</td><td>${r.nip||''}</td><td>${r.nominal||''}</td><td>${r.status||''}</td><td>${r.reason||''}</td></tr>`).join('') + '</tbody></table></div>';
        } catch (err) {
          resBox.innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>';
        }
      };
    }


  };
})();
