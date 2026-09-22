(function () {
  const EVKIN = window.EVKIN;
  if (!EVKIN || !EVKIN.masterPengembalianMod) return;

  window.EVKIN_MONTHLY_MASTER_ENABLED = true;
  const legacyRender = EVKIN.masterPengembalianMod.render;
  const MONTHS = {10: 'Oktober', 11: 'November', 12: 'Desember'};
  const SOURCE_NAME = 'sumber aktif';
  const PERIOD_ID = 'PENGEMBALIAN-2025-TAHAP-1';
  const esc = value => EVKIN.util.esc(String(value == null ? '' : value));
  const number = value => Number(value || 0).toLocaleString('id-ID');
  const money = value => Number(value || 0).toLocaleString('id-ID', {style:'currency',currency:'IDR',maximumFractionDigits:0});
  const signedMoney = value => `${Number(value || 0) > 0 ? '+' : ''}${money(value)}`;
  const api = path => new URL(path, EVKIN.exportBackend.apiBase).toString();
  const currentPanel = (content, id) => content && content.isConnected && content.dataset.monthlyPanel === id;

  async function request(path, options) {
    if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif');
    const response = await fetch(api(path), options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Permintaan gagal');
    return result;
  }

  function fileDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
      reader.onerror = () => reject(reader.error || new Error('Gagal membaca file'));
      reader.readAsDataURL(file);
    });
  }

  function setCanonicalHeader(source) {
    const note = document.querySelector('.pengembalian-shell')?.previousElementSibling;
    if (note && note.classList.contains('alert')) {
      const filename = source?.filename || SOURCE_NAME;
      const sheet = source?.source_sheet || 'belum tersedia';
      const status = source ? 'Sumber resmi aktif' : 'Belum ada sumber resmi aktif';
      note.innerHTML = `<strong>${status}:</strong> ${esc(filename)} · Sheet ${esc(sheet)} · <strong>FINAL PENGEMBALIAN</strong> adalah kewajiban utama.`;
    }
    const readonly = document.querySelector('.mp-readonly');
    if (readonly) readonly.textContent = 'MASTER BULANAN RESMI';
    const values = [
      ['Sumber utama','98.255 BNBA','NIP + Tahun + Bulan'],
      ['Versi data','Aktif','Sumber lama dapat ditelusuri'],
      ['Kewajiban','Final','Berasal dari FINAL PENGEMBALIAN'],
      ['Audit','42 kolom','Cek selisih & raw source tersimpan']
    ];
    document.querySelectorAll('.pengembalian-stat').forEach((card,index) => {
      if (!values[index]) return;
      const [label,value,meta]=values[index];
      card.querySelector('.label').textContent=label;
      card.querySelector('.value').textContent=value;
      card.querySelector('.meta').textContent=meta;
    });
  }

  function kpis(items) {
    return `<div class="mp-kpi-grid">${items.map(([label,value,tone])=>`<div class="mp-kpi ${tone||''}"><span>${esc(label)}</span><strong>${value}</strong></div>`).join('')}</div>`;
  }

  function statusMonthTable(rows) {
    const statuses=[...new Set((rows||[]).map(row=>row.status_send_bpk))];
    return `<div class="table-wrap"><table class="data-table mp-pivot-table"><thead><tr><th>Status Send BPK</th><th>Bulan</th><th>Count</th><th>Pengembalian Awal</th><th>Final Pengembalian</th></tr></thead><tbody>${statuses.map(status=>{const children=rows.filter(row=>row.status_send_bpk===status);const totalRows=children.reduce((sum,row)=>sum+Number(row.rows||0),0);const totalAwal=children.reduce((sum,row)=>sum+Number(row.total_awal||0),0);const totalFinal=children.reduce((sum,row)=>sum+Number(row.total_final||0),0);return `<tr class="mp-pivot-total"><td>${esc(status)}</td><td>Semua bulan</td><td>${number(totalRows)}</td><td>${money(totalAwal)}</td><td>${money(totalFinal)}</td></tr>${children.map(row=>`<tr><td></td><td>${esc(row.bulan_nama)}</td><td>${number(row.rows)}</td><td>${money(row.total_awal)}</td><td>${money(row.total_final)}</td></tr>`).join('')}`;}).join('')||'<tr><td colspan="5">Belum ada data.</td></tr>'}</tbody></table></div>`;
  }

  function sp2dTable(rows) {
    return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Status Send BPK</th><th>Bulan</th><th>Tahun SP2D Update</th><th>Count</th><th>Pengembalian Awal</th><th>Final Pengembalian</th></tr></thead><tbody>${(rows||[]).map(row=>`<tr><td>${esc(row.status_send_bpk)}</td><td>${esc(row.bulan_nama)}</td><td>${row.tahun_sp2d_update||'-'}</td><td>${number(row.rows)}</td><td>${money(row.total_awal)}</td><td>${money(row.total_final)}</td></tr>`).join('')||'<tr><td colspan="6">Belum ada data.</td></tr>'}</tbody></table></div>`;
  }

  function reasonBars(rows) {
    const max=Math.max(1,...(rows||[]).map(row=>Number(row.dampak_nominal||0)));
    return `<div class="mp-reason-list">${(rows||[]).slice(0,12).map(row=>`<button class="mp-reason-row" data-reason="${esc(row.alasan_perubahan)}"><span class="mp-reason-label"><strong>${esc(row.alasan_perubahan)}</strong><small>${number(row.rows)} BNBA · ${number(row.sdm)} SDM · dampak ${money(row.dampak_nominal)}</small></span><span class="mp-reason-track"><span style="width:${Math.max(2,Number(row.dampak_nominal||0)/max*100)}%"></span></span></button>`).join('')||'<p class="muted">Belum ada perubahan nominal.</p>'}</div>`;
  }

  function installDashboard() {
    document.getElementById('mpArchiveDashboard').onclick=async function(){
      const content=document.getElementById('mpContent');
      content.innerHTML='<h3>Dashboard Master Pengembalian</h3><p class="muted">Memuat rekap sumber resmi…</p>';
      try{
        const data=await request('/pengembalian/monthly/dashboard');
        if(!currentPanel(content,'mpArchiveDashboard'))return;
        const source=(data.active_imports||[])[0];
        setCanonicalHeader(source);
        content.innerHTML=`<div class="mp-section-heading"><div><h3>Dashboard Master Pengembalian</h3><p class="muted">Rekap resmi mengikuti sheet workbook dan dapat ditelusuri sampai BNBA.</p></div><button id="monthlyRefresh" class="btn btn-secondary">Muat Ulang</button></div>
          ${kpis([['Baris Bulanan',number(data.total_rows)],['SDM Unik',number(data.total_sdm)],['Pengembalian Awal',money(data.total_awal)],['Kewajiban Final',money(data.total_final),'mp-kpi-primary'],['Penyesuaian Final–Awal',signedMoney(data.selisih)],['Naik',number(data.naik)],['Turun',number(data.turun)],['Tidak Berubah',number(data.tidak_berubah)],['Warning Sumber',number(data.warning_rows)]])}
          <div class="mp-source-card"><div><span>Sumber resmi aktif</span><strong>${esc(source?.filename||'Belum ada')}</strong><small>Sheet ${esc(source?.source_sheet||'-')} · ${number(source?.total_rows||0)} baris · diimpor ${esc(source?.imported_at||'-')}</small></div><span class="module-badge">FINAL PENGEMBALIAN</span></div>
          <section class="mp-dashboard-section"><div class="mp-section-heading"><div><h4>Rekap Status Send BPK per Bulan</h4><p class="muted">Susunan dan angka mengikuti pivot pada sheet rekap 3 bulan.</p></div></div>${statusMonthTable(data.by_status_month)}</section>
          <section class="mp-dashboard-section"><div class="mp-section-heading"><div><h4>Rekap STATUS SP2D UPDATE</h4><p class="muted">Pemisahan tahun SP2D 2025 dan 2026 per status serta bulan.</p></div></div>${sp2dTable(data.by_sp2d_status_month)}</section>
          <section class="mp-dashboard-section"><div class="mp-section-heading"><div><h4>Alasan Perubahan BNBA</h4><p class="muted">Kategori berasal langsung dari kolom cek selisih. Klik alasan untuk membuka daftar BNBA.</p></div><button id="openAllTrace" class="btn btn-secondary">Pelacakan BNBA</button></div>${reasonBars(data.by_reason)}</section>`;
        document.getElementById('monthlyRefresh').onclick=()=>document.getElementById('mpArchiveDashboard').click();
        document.getElementById('openAllTrace').onclick=()=>document.getElementById('mpBnbaTrace').click();
        content.querySelectorAll('.mp-reason-row').forEach(button=>button.onclick=()=>{window.EVKIN_MONTHLY_TRACE_REASON=button.dataset.reason;document.getElementById('mpBnbaTrace').click();});
      }catch(error){content.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}
    };
  }

  async function showDetail(rowId,target){
    target.innerHTML='<p class="muted">Memuat detail dan lineage…</p>';
    try{
      const row=await request('/pengembalian/monthly/detail/'+encodeURIComponent(rowId));
      target.innerHTML=`<div class="card mp-trace-detail"><div class="mp-section-heading"><div><h4>${esc(row.nip)} — ${esc(row.bulan_nama)} ${row.tahun}</h4><p class="muted">${esc(row.source_filename)} · sheet ${esc(row.source_sheet)} · baris ${row.source_row_number}</p></div><button class="btn btn-sm btn-secondary mp-close-detail">Tutup</button></div>${kpis([['Pengembalian Awal',money(row.pengembalian_awal)],['Final Pengembalian',money(row.final_pengembalian)],['Perubahan',signedMoney(row.selisih_pengembalian)],['Kategori Alasan',esc(row.alasan_perubahan)]])}<div class="alert info"><strong>Cek selisih sumber:</strong> ${esc(row.cek_selisih||'-')}<br><strong>Keterangan tambahan:</strong> ${esc(row.keterangan_penyesuaian||'-')}</div><details><summary>Seluruh data normalisasi</summary><div class="table-wrap"><table class="data-table"><tbody>${Object.entries(row).filter(([key])=>key!=='raw_source').map(([key,value])=>`<tr><th>${esc(key.replaceAll('_',' '))}</th><td>${esc(typeof value==='object'?JSON.stringify(value):value)}</td></tr>`).join('')}</tbody></table></div></details><details><summary>Raw source 42 kolom</summary><pre>${esc(JSON.stringify(row.raw_source,null,2))}</pre></details></div>`;
      target.querySelector('.mp-close-detail').onclick=()=>{target.innerHTML='';};
    }catch(error){target.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}
  }

  function openBnbaTrace(nip){window.EVKIN_MONTHLY_TRACE_NIP=nip;document.getElementById('mpBnbaTrace').click();}

  function installFinal(){
    document.getElementById('mpFinal').onclick=async function(){
      const content=document.getElementById('mpContent');let offset=0;const limit=100;
      const reasonData=await request('/pengembalian/monthly/reasons').catch(()=>({rows:[]}));
      content.innerHTML=`<div class="mp-section-heading"><div><h3>Data Final Bulanan</h3><p class="muted">FINAL PENGEMBALIAN adalah kewajiban resmi; alasan diambil dari cek selisih.</p></div><button id="monthlyFinalExport" class="btn btn-primary">Export Hasil Filter</button></div><div class="mp-filterbar"><input id="mfSearch" placeholder="Cari NIP, nama, atau cek selisih"><input id="mfYear" type="number" placeholder="Tahun"><select id="mfMonth"><option value="">Semua Bulan</option>${Object.entries(MONTHS).map(([key,value])=>`<option value="${key}">${value}</option>`).join('')}</select><input id="mfSp2d" type="number" placeholder="Tahun SP2D"><input id="mfProvince" placeholder="Provinsi"><select id="mfZone"><option value="">Semua Zona</option><option>WIB</option><option>WITA</option><option>WIT</option></select><select id="mfBpk"><option value="">Semua Status BPK</option><option>TAHAP 1 SEND BPK</option><option>BELUM MASUK BPK</option></select><select id="mfReason"><option value="">Semua Alasan</option>${reasonData.rows.map(row=>`<option>${esc(row.alasan)}</option>`).join('')}<option>TIDAK ADA PERUBAHAN</option></select><select id="mfChange"><option value="">Semua Perubahan</option><option>NAIK</option><option>TURUN</option><option>TIDAK BERUBAH</option></select><select id="mfValidation"><option value="">Semua Validasi</option><option>VALID</option><option>WARNING</option></select><button id="mfApply" class="btn btn-primary">Terapkan</button></div><div id="mfResult"><p>Memuat…</p></div><div id="mfDetail"></div>`;
      const params=()=>{const result=new URLSearchParams();[['mfSearch','search'],['mfYear','tahun'],['mfMonth','bulan'],['mfSp2d','tahun_sp2d'],['mfProvince','provinsi'],['mfZone','zona_waktu'],['mfBpk','status_send_bpk'],['mfReason','alasan_perubahan'],['mfChange','status_perubahan'],['mfValidation','validation_status']].forEach(([id,key])=>{const value=document.getElementById(id)?.value.trim();if(value)result.set(key,value);});return result;};
      const load=async()=>{const query=params();query.set('limit',limit);query.set('offset',offset);const data=await request('/pengembalian/monthly/list?'+query);if(!currentPanel(content,'mpFinal'))return;document.getElementById('mfResult').innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Periode</th><th>Awal</th><th>Final</th><th>Selisih</th><th>Alasan dari Cek Selisih</th><th>BPK</th><th>SP2D</th><th>Wilayah</th><th>Validasi</th><th>Aksi</th></tr></thead><tbody>${(data.rows||[]).map(row=>`<tr><td>${esc(row.nip)}</td><td>${esc(row.nama)}</td><td>${esc(row.bulan_nama)} ${row.tahun}</td><td>${money(row.pengembalian_awal)}</td><td><strong>${money(row.final_pengembalian)}</strong></td><td class="${Number(row.selisih_pengembalian)<0?'mp-negative':Number(row.selisih_pengembalian)>0?'mp-positive':''}">${signedMoney(row.selisih_pengembalian)}</td><td><strong>${esc(row.alasan_perubahan)}</strong><br><small>${esc(row.cek_selisih||'-')}</small></td><td>${esc(row.status_send_bpk)}</td><td>${row.tahun_sp2d_awal||'-'} → ${row.tahun_sp2d_update||'-'}</td><td>${esc(row.provinsi)}<br>${esc(row.kabupaten_kota)}</td><td><span class="module-badge">${esc(row.validation_status)}</span></td><td><button class="btn btn-sm btn-secondary mf-detail" data-id="${esc(row.row_id)}">Detail</button> <button class="btn btn-sm btn-primary mf-trace" data-nip="${esc(row.nip)}">Lacak</button></td></tr>`).join('')||'<tr><td colspan="12">Tidak ada data.</td></tr>'}</tbody></table></div><div class="mp-actionbar"><span>${data.total?offset+1:0}–${Math.min(offset+(data.rows||[]).length,data.total)} dari ${number(data.total)}</span><button id="mfPrev" class="btn btn-sm btn-secondary" ${offset===0?'disabled':''}>Sebelumnya</button><button id="mfNext" class="btn btn-sm btn-secondary" ${data.has_more?'':'disabled'}>Berikutnya</button></div>`;document.getElementById('mfPrev').onclick=()=>{offset=Math.max(0,offset-limit);load();};document.getElementById('mfNext').onclick=()=>{offset+=limit;load();};document.querySelectorAll('.mf-detail').forEach(button=>button.onclick=()=>showDetail(button.dataset.id,document.getElementById('mfDetail')));document.querySelectorAll('.mf-trace').forEach(button=>button.onclick=()=>openBnbaTrace(button.dataset.nip));};
      document.getElementById('mfApply').onclick=()=>{offset=0;load().catch(error=>EVKIN.toast(error.message,'error'));};
      document.getElementById('monthlyFinalExport').onclick=()=>EVKIN.exportBackend.downloadAuthenticated(api('/pengembalian/monthly/download?'+params()));
      load().catch(error=>{document.getElementById('mfResult').innerHTML=`<div class="alert error">${esc(error.message)}</div>`;});
    };
  }

  function traceTimeline(data){
    return `<div class="mp-trace-profile"><div><span>NIP</span><strong>${esc(data.nip)}</strong></div><div><span>Nama</span><strong>${esc(data.nama)}</strong></div><div><span>Jumlah bulan</span><strong>${number(data.summary.months)}</strong></div><div><span>Total awal</span><strong>${money(data.summary.total_awal)}</strong></div><div><span>Kewajiban final</span><strong>${money(data.summary.total_final)}</strong></div><div><span>Total perubahan</span><strong>${signedMoney(data.summary.total_selisih)}</strong></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Periode</th><th>Awal</th><th>Final</th><th>Perubahan</th><th>Alasan dari Cek Selisih</th><th>Status BPK</th><th>SP2D</th><th>Sumber</th><th>Detail</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td>${esc(row.bulan_nama)} ${row.tahun}</td><td>${money(row.pengembalian_awal)}</td><td><strong>${money(row.final_pengembalian)}</strong></td><td>${signedMoney(row.selisih_pengembalian)}</td><td><strong>${esc(row.alasan_perubahan)}</strong><br><small>${esc(row.cek_selisih||'-')}</small></td><td>${esc(row.status_send_bpk)}</td><td>${row.tahun_sp2d_awal||'-'} → ${row.tahun_sp2d_update||'-'}</td><td>${esc(row.source_filename)}<br><small>${esc(row.source_sheet)} · baris ${row.source_row_number}</small></td><td><button class="btn btn-sm btn-secondary trace-detail" data-id="${esc(row.row_id)}">Buka</button></td></tr>`).join('')}</tbody></table></div><h4>Kewajiban yang Disinkronkan ke Progres Pengembalian</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>Periode</th><th>Tahun SP2D</th><th>Final Tukin</th><th>Total Kewajiban</th><th>Status</th><th>Sumber</th></tr></thead><tbody>${(data.obligations||[]).map(row=>`<tr><td>${esc(row.periode_id)}</td><td>${row.tahun_sp2d}</td><td>${money(row.final_tukin)}</td><td>${money(row.final_total)}</td><td>${esc(row.status_sp2d)}</td><td>${esc(row.sumber_sp2d)}</td></tr>`).join('')||'<tr><td colspan="6">Belum ada kewajiban.</td></tr>'}</tbody></table></div><div id="traceRowDetail"></div>`;
  }

  function installTrace(){
    document.getElementById('mpBnbaTrace').onclick=async function(){
      const content=document.getElementById('mpContent');const reasons=await request('/pengembalian/monthly/reasons').catch(()=>({rows:[]}));const presetReason=window.EVKIN_MONTHLY_TRACE_REASON||'';const presetNip=window.EVKIN_MONTHLY_TRACE_NIP||'';window.EVKIN_MONTHLY_TRACE_REASON='';window.EVKIN_MONTHLY_TRACE_NIP='';
      content.innerHTML=`<div class="mp-section-heading"><div><h3>Pelacakan BNBA</h3><p class="muted">Telusuri perubahan dari nilai awal ke FINAL PENGEMBALIAN beserta cek selisih dan sumber barisnya.</p></div></div><div class="mp-filterbar"><input id="traceSearch" value="${esc(presetNip)}" placeholder="NIP atau nama"><select id="traceMonth"><option value="">Semua Bulan</option>${Object.entries(MONTHS).map(([key,value])=>`<option value="${key}">${value}</option>`).join('')}</select><select id="traceBpk"><option value="">Semua Status BPK</option><option>TAHAP 1 SEND BPK</option><option>BELUM MASUK BPK</option></select><select id="traceReason"><option value="">Semua Alasan</option>${reasons.rows.map(row=>`<option ${row.alasan===presetReason?'selected':''}>${esc(row.alasan)}</option>`).join('')}</select><select id="traceChange"><option value="">Semua Perubahan</option><option>NAIK</option><option>TURUN</option><option>TIDAK BERUBAH</option></select><button id="traceLoad" class="btn btn-primary">Cari BNBA</button></div><div id="traceResults"></div><div id="traceTimeline"></div>`;
      const load=async()=>{const query=new URLSearchParams({limit:'100',offset:'0'});[['traceSearch','search'],['traceMonth','bulan'],['traceBpk','status_send_bpk'],['traceReason','alasan_perubahan'],['traceChange','status_perubahan']].forEach(([id,key])=>{const value=document.getElementById(id).value.trim();if(value)query.set(key,value);});const data=await request('/pengembalian/monthly/list?'+query);document.getElementById('traceResults').innerHTML=`<p class="muted">Ditemukan ${number(data.total)} baris. Pilih BNBA untuk melihat riwayat seluruh bulan.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Periode</th><th>Awal</th><th>Final</th><th>Perubahan</th><th>Alasan</th><th>BPK</th><th>Aksi</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td>${esc(row.nip)}</td><td>${esc(row.nama)}</td><td>${esc(row.bulan_nama)} ${row.tahun}</td><td>${money(row.pengembalian_awal)}</td><td>${money(row.final_pengembalian)}</td><td>${signedMoney(row.selisih_pengembalian)}</td><td>${esc(row.alasan_perubahan)}</td><td>${esc(row.status_send_bpk)}</td><td><button class="btn btn-sm btn-primary trace-open" data-nip="${esc(row.nip)}">Lacak</button></td></tr>`).join('')||'<tr><td colspan="9">Tidak ada data.</td></tr>'}</tbody></table></div>`;document.querySelectorAll('.trace-open').forEach(button=>button.onclick=()=>loadNip(button.dataset.nip));};
      const loadNip=async nip=>{const area=document.getElementById('traceTimeline');area.innerHTML='<p class="muted">Memuat timeline BNBA…</p>';try{const data=await request('/pengembalian/monthly/bnba/'+encodeURIComponent(nip));area.innerHTML=`<div class="mp-section-heading"><h4>Timeline BNBA</h4><button id="traceClose" class="btn btn-sm btn-secondary">Tutup</button></div>${traceTimeline(data)}`;document.getElementById('traceClose').onclick=()=>{area.innerHTML='';};area.querySelectorAll('.trace-detail').forEach(button=>button.onclick=()=>showDetail(button.dataset.id,document.getElementById('traceRowDetail')));}catch(error){area.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}};
      document.getElementById('traceLoad').onclick=()=>load().catch(error=>EVKIN.toast(error.message,'error'));await load();if(presetNip)await loadNip(presetNip);
    };
  }

  function installDailyData(){
    document.getElementById('mpDailyData').onclick=async function(){
      const content=document.getElementById('mpContent');content.innerHTML=`<div class="mp-section-heading"><div><h3>Data Dasar Perhitungan</h3><p class="muted">Komponen yang membentuk FINAL PENGEMBALIAN pada master bulanan aktif.</p></div></div><div class="mp-filterbar"><input id="basisSearch" placeholder="Cari NIP atau nama"><select id="basisMonth"><option value="">Semua Bulan</option>${Object.entries(MONTHS).map(([key,value])=>`<option value="${key}">${value}</option>`).join('')}</select><button id="basisLoad" class="btn btn-primary">Terapkan</button></div><div id="basisResult"></div>`;
      const load=async()=>{const query=new URLSearchParams({limit:'100'});const search=document.getElementById('basisSearch').value.trim();const month=document.getElementById('basisMonth').value;if(search)query.set('search',search);if(month)query.set('bulan',month);const data=await request('/pengembalian/monthly/list?'+query);document.getElementById('basisResult').innerHTML=`<div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Bulan</th><th>Tukin</th><th>Potongan SKP</th><th>Pot. Kehadiran eSDM</th><th>Pot. Kehadiran e-Absensi</th><th>Final Kehadiran</th><th>Pengembalian Awal</th><th>FINAL PENGEMBALIAN</th><th>Validasi</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td>${esc(row.nip)}</td><td>${esc(row.nama)}</td><td>${esc(row.bulan_nama)}</td><td>${money(row.tukin)}</td><td>${money(row.potongan_skp)}</td><td>${money(row.potongan_kehadiran_esdm)}</td><td>${money(row.potongan_kehadiran_eabsensi)}</td><td>${money(row.final_kehadiran)}</td><td>${money(row.pengembalian_awal)}</td><td><strong>${money(row.final_pengembalian)}</strong></td><td>${esc(row.validation_status)}</td></tr>`).join('')||'<tr><td colspan="11">Tidak ada data.</td></tr>'}</tbody></table></div>`;};document.getElementById('basisLoad').onclick=()=>load().catch(error=>EVKIN.toast(error.message,'error'));load().catch(error=>{document.getElementById('basisResult').innerHTML=`<div class="alert error">${esc(error.message)}</div>`;});
    };
  }

  function installImport(){
    document.getElementById('mpImportHistory').onclick=async function(){
      const content=document.getElementById('mpContent');content.innerHTML=`<div class="mp-section-heading"><div><h3>Import Sumber Resmi</h3><p class="muted">Sumber utama: ${esc(SOURCE_NAME)}. Sistem otomatis memilih sheet detail berdasarkan header.</p></div></div><div class="alert info">Import pada periode yang sama akan menggantikan versi aktif. Versi lama tetap tersedia di History / Archive.</div><div class="form-row"><label style="flex:1">ID Periode Internal<input id="monthlyPeriod" value="${PERIOD_ID}"></label><label style="flex:2">File sumber<input id="monthlyFile" type="file" accept=".xlsx"></label><button id="monthlyPreview" class="btn btn-secondary">Preview & Validasi</button></div><div id="monthlyImportResult"></div>`;let encoded,file;
      document.getElementById('monthlyPreview').onclick=async function(){const box=document.getElementById('monthlyImportResult');file=document.getElementById('monthlyFile').files[0];if(!file)return EVKIN.toast('Pilih file XLSX','error');box.innerHTML='<p>Membaca sheet detail dan memvalidasi seluruh workbook…</p>';try{encoded=await fileDataUrl(file);const preview=await request('/pengembalian/monthly/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,file_base64:encoded})});const summary=preview.summary;box.innerHTML=`<div class="alert success"><strong>Sheet terpilih:</strong> ${esc(preview.sheet)} · sumber akan disimpan sebagai raw audit.</div>${kpis([['Baris',number(summary.total_rows)],['SDM',number(summary.unique_nip)],['Valid',number(summary.valid_rows)],['Warning',number(summary.warning_rows)],['Invalid',number(summary.invalid_rows)],['Duplikat',number(summary.duplicate_rows)],['Total Awal',money(summary.total_awal)],['Total Final',money(summary.total_final)]])}<h4>Flag Validasi</h4><pre>${esc(JSON.stringify(summary.flags,null,2))}</pre><button id="monthlyCommit" class="btn btn-primary">Aktifkan sebagai Sumber Resmi Utama</button><div id="monthlyCommitState"></div>`;document.getElementById('monthlyCommit').onclick=async function(){this.disabled=true;const state=document.getElementById('monthlyCommitState');state.innerHTML='<p>Menyimpan raw source, master bulanan, alasan perubahan, dan kewajiban…</p>';try{const result=await request('/pengembalian/monthly/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,file_base64:encoded,periode_id:document.getElementById('monthlyPeriod').value.trim(),created_by:(EVKIN.user&&EVKIN.user.username)||'ui',metadata:{official_source:true,official_source_name:SOURCE_NAME}})});state.innerHTML=`<div class="alert success">Import selesai: ${number(result.summary.total_rows)} baris. FINAL PENGEMBALIAN telah menjadi kewajiban utama dan sumber lama berstatus superseded.</div>`;}catch(error){this.disabled=false;state.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}};}catch(error){box.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}};
    };
  }

  function installHistory(){
    document.getElementById('mpArchiveList').onclick=async function(){const content=document.getElementById('mpContent');content.innerHTML='<h3>History / Archive Sumber Resmi</h3><p>Memuat…</p>';try{const data=await request('/pengembalian/monthly/imports');if(!currentPanel(content,'mpArchiveList'))return;content.innerHTML=`<div class="mp-section-heading"><div><h3>History / Archive</h3><p class="muted">Versi aktif digunakan untuk dashboard, BNBA, dan kewajiban. Versi lama dapat diaktifkan kembali atau dihapus dari backend.</p></div><button id="monthlyResetSources" class="btn btn-danger">Reset Database Sumber</button></div><div class="alert warn"><strong>Reset Database Sumber</strong> menghapus seluruh versi workbook Master dan kewajiban turunannya. Transaction ledger Progress tidak dihapus.</div><div class="table-wrap"><table class="data-table"><thead><tr><th>Status</th><th>Periode</th><th>File</th><th>Waktu</th><th>Baris</th><th>Valid</th><th>Warning</th><th>Invalid</th><th>Awal</th><th>Final</th><th>Aksi</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td><span class="module-badge">${esc(row.status)}</span>${row.is_active?' · AKTIF':''}</td><td>${esc(row.periode_id)}</td><td>${esc(row.source_filename)}<br><small>sheet ${esc(row.source_sheet||'-')}</small></td><td>${esc(row.imported_at)}</td><td>${number(row.total_rows)}</td><td>${number(row.valid_rows)}</td><td>${number(row.warning_rows)}</td><td>${number(row.invalid_rows)}</td><td>${money(row.total_awal)}</td><td>${money(row.total_final)}</td><td>${row.is_active?'Sumber utama':`<button class="btn btn-sm btn-primary monthly-activate" data-id="${esc(row.import_id)}">Aktifkan</button> <button class="btn btn-sm btn-danger monthly-delete" data-id="${esc(row.import_id)}">Hapus Database</button>`}</td></tr>`).join('')||'<tr><td colspan="11">Belum ada import.</td></tr>'}</tbody></table></div>`;document.getElementById('monthlyResetSources').onclick=async function(){const required='RESET SUMBER MASTER PENGEMBALIAN';const confirmation=prompt(`Tindakan ini menghapus seluruh History/Archive sumber Master dan kewajiban turunannya. Progress transaksi tetap disimpan. Ketik ${required} untuk melanjutkan:`);if(String(confirmation||'').trim().toUpperCase()!==required)return;this.disabled=true;try{const result=await request('/pengembalian/monthly/source-database/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:required,reset_by:(EVKIN.user&&EVKIN.user.username)||'ui'})});EVKIN.toast(`Database sumber direset (${number(result.deleted_rows||0)} baris). Progress tetap ${number(result.progress_rows||0)} transaksi.`,'success');document.getElementById('mpArchiveList').click();}catch(error){this.disabled=false;EVKIN.toast(error.message,'error');}};content.querySelectorAll('.monthly-activate').forEach(button=>button.onclick=async()=>{if(!confirm('Aktifkan versi ini sebagai database utama?'))return;await request('/pengembalian/monthly/imports/'+encodeURIComponent(button.dataset.id)+'/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({created_by:(EVKIN.user&&EVKIN.user.username)||'ui'})});EVKIN.toast('Versi berhasil diaktifkan','success');document.getElementById('mpArchiveList').click();});content.querySelectorAll('.monthly-delete').forEach(button=>button.onclick=async()=>{if(!confirm('Hapus database tersimpan ini beserta seluruh baris sumbernya dari backend? Data aktif tidak dapat dihapus.'))return;button.disabled=true;try{const result=await request('/pengembalian/monthly/imports/'+encodeURIComponent(button.dataset.id),{method:'DELETE'});EVKIN.toast(`Database dihapus (${number(result.deleted_rows||0)} baris).`,'success');document.getElementById('mpArchiveList').click();}catch(error){button.disabled=false;EVKIN.toast(error.message,'error');}});}catch(error){content.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}};
  }

  function installReconciliation(){
    document.getElementById('mpBpkReconciliation').onclick=async function(){const content=document.getElementById('mpContent');content.innerHTML='<h3>Rekonsiliasi BPK</h3><p>Memuat…</p>';try{const data=await request('/pengembalian/monthly/reconciliation');if(!currentPanel(content,'mpBpkReconciliation'))return;content.innerHTML=`<div class="mp-section-heading"><div><h3>Rekonsiliasi BPK</h3><p class="muted">Nilai awal dibandingkan FINAL PENGEMBALIAN per status kirim dan bulan.</p></div><button id="monthlyBpkExport" class="btn btn-primary">Export</button></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Status BPK</th><th>SDM</th><th>Baris</th><th>Awal</th><th>Final</th><th>Selisih</th><th>Naik</th><th>Turun</th><th>Tetap</th></tr></thead><tbody>${data.rows.map(row=>`<tr><td>${esc(row.status_send_bpk)}</td><td>${number(row.jumlah_sdm)}</td><td>${number(row.jumlah_data)}</td><td>${money(row.nominal_awal)}</td><td>${money(row.nominal_final)}</td><td>${signedMoney(row.selisih)}</td><td>${number(row.naik)}</td><td>${number(row.turun)}</td><td>${number(row.tidak_berubah)}</td></tr>`).join('')}</tbody></table></div><h4>Rincian per Bulan</h4><div class="table-wrap"><table class="data-table"><thead><tr><th>Status BPK</th><th>Bulan</th><th>Baris</th><th>SDM</th><th>Awal</th><th>Final</th><th>Selisih</th></tr></thead><tbody>${data.by_month.map(row=>`<tr><td>${esc(row.status_send_bpk)}</td><td>${esc(row.bulan_nama)}</td><td>${number(row.jumlah_data)}</td><td>${number(row.jumlah_sdm)}</td><td>${money(row.nominal_awal)}</td><td>${money(row.nominal_final)}</td><td>${signedMoney(row.selisih)}</td></tr>`).join('')}</tbody></table></div>`;document.getElementById('monthlyBpkExport').onclick=()=>window.open(api('/pengembalian/monthly/download'),'_blank');}catch(error){content.innerHTML=`<div class="alert error">${esc(error.message)}</div>`;}};
  }

  function installImportSelector(bnbaImport, monthlyImport) {
    const button = document.getElementById('mpImportHistory');
    if (!button) return;
    button.onclick = function () {
      const content = document.getElementById('mpContent');
      content.innerHTML = `<div class="mp-section-heading"><div><h3>Import Data Master Pengembalian</h3><p class="muted">Pilih format file yang akan dimasukkan ke database.</p></div></div>
        <div class="mp-detail-grid">
          <div class="card"><h4>BNBA Terpadu</h4><p class="muted">Untuk file dengan data awal dan DATA FINAL dalam satu workbook.</p><button id="mpChooseBnba" class="btn btn-primary">Import BNBA Terpadu</button></div>
          <div class="card"><h4>Master Bulanan Resmi</h4><p class="muted">Untuk workbook detail bulanan dengan kolom FINAL PENGEMBALIAN.</p><button id="mpChooseMonthly" class="btn btn-primary">Import Master Bulanan</button></div>
        </div>`;
      document.getElementById('mpChooseBnba').onclick = bnbaImport;
      document.getElementById('mpChooseMonthly').onclick = monthlyImport;
    };
  }

  EVKIN.masterPengembalianMod.render=function(element){
    legacyRender(element);const bnbaImport=document.getElementById('mpImportHistory')?.onclick;setCanonicalHeader();installDashboard();installFinal();installTrace();installDailyData();installImport();const monthlyImport=document.getElementById('mpImportHistory')?.onclick;installImportSelector(bnbaImport,monthlyImport);installHistory();installReconciliation();
    document.querySelectorAll('.pengembalian-toolbar button').forEach(button=>button.addEventListener('click',()=>{const content=document.getElementById('mpContent');if(content)content.dataset.monthlyPanel=button.id;},{capture:true}));
    document.getElementById('mpExport').onclick=()=>EVKIN.exportBackend.downloadAuthenticated(api('/pengembalian/monthly/download'));
    document.getElementById('mpClearDatabase').onclick=async function(){const confirmation=prompt('Ketik RESET MASTER PENGEMBALIAN untuk menghapus seluruh data Master Pengembalian, History/Archive, hasil turunan, progress, dan kewajiban dari backend:');if(String(confirmation||'').trim().toUpperCase()!=='RESET MASTER PENGEMBALIAN')return;this.disabled=true;try{const result=await request('/pengembalian/monthly/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:'RESET MASTER PENGEMBALIAN'})});EVKIN.toast(`Database Master Pengembalian direset (${number(result.deleted_rows||0)} baris).`,'success');document.getElementById('mpArchiveDashboard').click();}catch(error){EVKIN.toast(error.message,'error');this.disabled=false;}};
    document.getElementById('mpArchiveDashboard').click();
  };
})();
