/* EVKIN Penilaian SKP: import, classification, approval, and annual records. */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util;
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  const view = {
    tab: 'import', period: '', year: 2026, workbook: null, file: null,
    preview: null, rows: [], selected: new Set(), page: 1, pages: 1
  };

  function esc(value) { return U.esc(String(value == null ? '' : value)); }
  function num(value) { return Number(value || 0).toLocaleString('id-ID'); }
  function baseUrl(path) { return new URL(path, EVKIN.exportBackend.apiBase).toString(); }
  async function api(path, options) {
    const response = await fetch(baseUrl(path), { cache: 'no-store', ...(options || {}) });
    const type = response.headers.get('content-type') || '';
    const data = type.includes('json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error((data && data.detail) || data || 'Permintaan gagal');
    return data;
  }
  function showError(error) { EVKIN.toast(error && error.message ? error.message : String(error), 'error'); }
  function pill(value) {
    const raw = String(value || 'BELUM ADA').toUpperCase();
    const color = /APPROVED|MENCAPAI|VALID$/.test(raw) ? 'green'
      : /INVALID|RETURN|SANGAT KURANG|TIDAK_ADA/.test(raw) ? 'red'
        : /PENDING|RECOMMENDED|KURANG|REVIEW/.test(raw) ? 'yellow' : 'gray';
    return `<span class="pill ${color}">${esc(raw.replaceAll('_', ' '))}</span>`;
  }
  function download(path, filename) {
    // Let the browser stream the response directly to disk. Avoid response.blob(),
    // which temporarily duplicates the whole XLSX in browser memory.
    const link = document.createElement('a');
    link.href = baseUrl(path); link.download = filename; document.body.appendChild(link);
    link.click(); link.remove();
  }
  const EXPORT_SHEETS = [
    ['summary','Rekap Tahunan','Ringkasan per SDM dan semester'],
    ['detail','Detail Bulanan','Nilai, indikator, dan status review per bulan'],
    ['meetings','Keputusan Rapat','Dokumentasi rekomendasi hasil rapat'],
    ['exceptions','Pengecualian','Cuti, tugas belajar, meninggal, dan kondisi resmi'],
    ['conditions','Kondisi & Hukdis','Keputusan, dokumen, efek SKP, dan efek pembayaran'],
    ['configs','Versi Konfigurasi','Target HEK, Verkom, Graduasi, dan P2K2']
  ];
  function updateExportSelection(root) {
    const checked = [...root.querySelectorAll('.skp-export-sheet:checked')];
    const label = root.querySelector('#skpExportSheetLabel');
    const button = root.querySelector('#skpDownload');
    if (label) label.textContent = `Sheet ekspor: ${checked.length} dipilih`;
    if (button) button.disabled = checked.length === 0;
  }
  async function startExportJob(root) {
    const button = root.querySelector('#skpDownload');
    const status = root.querySelector('#skpExportStatus');
    const sheets = [...root.querySelectorAll('.skp-export-sheet:checked')].map(item => item.value);
    if (!sheets.length) throw new Error('Pilih minimal satu sheet yang ingin diunduh.');
    button.disabled = true; status.textContent = 'Membuat job ekspor…';
    if (EVKIN.progress) EVKIN.progress({ title: 'Export Penilaian SKP', percent: 0, message: 'Membuat job ekspor...' });
    try {
      const job = await api('/api/skp-assessment/export/jobs', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ year:view.year, sheets })
      });
      while (true) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const current = await api(`/api/skp-assessment/export/jobs/${job.job_id}`);
        status.textContent = `${current.message} (${current.progress || 0}%)`;
        if (EVKIN.progress) EVKIN.progress({ title: 'Export Penilaian SKP', percent: current.progress || 0, message: current.message || 'Memproses export...' });
        if (current.status === 'failed') throw new Error(current.message || 'Ekspor gagal');
        if (current.status === 'finished') {
          if (EVKIN.progress) EVKIN.progress({ title: 'Export Penilaian SKP', percent: 100, message: 'File SKP selesai dibuat.', state: 'done' });
          download(current.download_url, current.filename);
          EVKIN.toast('File hasil penilaian SKP siap diunduh.', 'success');
          break;
        }
      }
    } catch (error) {
      if (EVKIN.progress) EVKIN.progress({ title: 'Export Penilaian SKP gagal', message: error.message, state: 'error' });
      throw error;
    } finally { button.disabled = false; }
  }

  function shell(root) {
    const active = EVKIN.state.month || '2026-08';
    view.period = view.period || active;
    view.year = Number(view.period.slice(0, 4)) || 2026;
    root.innerHTML = `
      <div class="module-head">
        <div><h2>Penilaian SKP</h2><p class="muted">Validasi sumber, klasifikasi indikator, dokumentasi keputusan, dan persetujuan sebelum potongan masuk ke Tukin.</p></div>
        <div><div class="actions-row"><button id="skpDownloadApproved" class="btn btn-secondary"><i data-lucide="badge-check"></i> Download Hasil APPROVED</button><div class="skp-export-picker"><button id="skpExportToggle" type="button" class="btn btn-secondary skp-export-toggle" aria-expanded="false"><i data-lucide="list-checks"></i><span id="skpExportSheetLabel">Sheet ekspor: 2 dipilih</span><i data-lucide="chevron-down"></i></button><div id="skpExportOptions" class="card skp-export-options hidden"><div class="skp-export-options-head"><strong>Isi file Excel yang diunduh</strong><span>Centang satu atau beberapa sheet.</span></div><div class="skp-export-quick"><button id="skpExportAll" type="button">Pilih semua</button><button id="skpExportDefault" type="button">Pilihan standar</button></div>${EXPORT_SHEETS.map((item, index) => `<label><input class="skp-export-sheet" type="checkbox" value="${item[0]}" ${index < 2 ? 'checked' : ''}><span><b>${item[1]}</b><small>${item[2]}</small></span></label>`).join('')}</div></div><button id="skpDownload" class="btn btn-success"><i data-lucide="file-spreadsheet"></i> Proses & Download ${view.year}</button></div><div id="skpExportStatus" class="muted"></div></div>
      </div>
      <div class="alert info"><i data-lucide="shield-check"></i><span>Nilai yang belum valid atau belum disetujui akan menahan pembayaran pada status <b>HOLD</b>. Hanya hasil berstatus <b>APPROVED</b> yang dikirim ke Pengelolaan Tukin.</span></div>
      <div class="skp-tabs" role="tablist">
        ${[['import','Impor & Validasi'],['configuration','Konfigurasi Indikator'],['classification','Klasifikasi & Keputusan'],['review','Review & Persetujuan'],['exceptions','Kondisi & Pengecualian'],['annual','Rekap & Histori']].map(tab => `<button class="skp-tab ${view.tab === tab[0] ? 'active' : ''}" data-tab="${tab[0]}">${tab[1]}</button>`).join('')}
      </div>
      <div id="skpPanel"></div>`;
    root.querySelector('.module-head .actions-row').insertAdjacentHTML('afterbegin', '<button id="skpResetAll" class="btn btn-danger"><i data-lucide="trash-2"></i> Hapus Data Penilaian SKP</button>');
    if (window.lucide) lucide.createIcons();
    root.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => {
      view.tab = button.dataset.tab; view.selected.clear(); shell(root); bindShell(root); renderTab(root).catch(showError);
    });
    root.querySelectorAll('.skp-export-sheet').forEach(box => box.onchange = () => updateExportSelection(root));
    root.querySelector('#skpExportToggle').onclick = () => {
      const options = root.querySelector('#skpExportOptions');
      const willOpen = options.classList.contains('hidden');
      options.classList.toggle('hidden', !willOpen);
      root.querySelector('#skpExportToggle').setAttribute('aria-expanded', String(willOpen));
    };
    root.querySelector('#skpExportAll').onclick = event => {
      event.preventDefault(); root.querySelectorAll('.skp-export-sheet').forEach(box => { box.checked = true; }); updateExportSelection(root);
    };
    root.querySelector('#skpExportDefault').onclick = event => {
      event.preventDefault(); root.querySelectorAll('.skp-export-sheet').forEach((box, index) => { box.checked = index < 2; }); updateExportSelection(root);
    };
    root.querySelector('#skpDownload').onclick = () => {
      root.querySelector('#skpExportOptions').classList.add('hidden');
      root.querySelector('#skpExportToggle').setAttribute('aria-expanded', 'false');
      startExportJob(root).catch(showError);
    };
    root.querySelector('#skpDownloadApproved').onclick = () => {
      download(`/api/skp-assessment/export/annual?year=${view.year}&scope=approved`, `HASIL_SKP_APPROVED_${view.year}.xlsx`);
      EVKIN.toast('Unduhan hanya berisi penilaian berstatus APPROVED.', 'success');
    };
    root.querySelector('#skpResetAll').onclick = async () => {
      try {
        await EVKIN.resetModuleData('skp', 'Penilaian SKP', ['final_skp'], async () => {
          view.selected.clear(); view.rows = []; shell(root); bindShell(root); await renderTab(root);
        });
      } catch (error) { showError(error); }
    };
    updateExportSelection(root);
  }

  function importPanel(root) {
    root.querySelector('#skpPanel').innerHTML = `
      <section class="card">
        <div class="ta-section-head"><div><h3>Impor Nilai SKP Bulanan</h3><p class="muted">Sistem memeriksa NIP, duplikat, predikat resmi, dan kecocokan Master SDM sebelum data boleh disimpan.</p></div></div>
        <div class="form-row">
          <div><label>Periode penilaian</label><input id="skpPeriod" type="month" value="${esc(view.period)}"></div>
          <div><label>Jalur impor</label><select id="skpImportMode"><option value="REVIEW">Penilaian untuk direview</option><option value="FINAL">Hasil Final SKP — langsung Kelola Tukin</option></select><small>Final: NIP, nama, predikat. Tanda - / tidak bisa dinilai / tidak membuat SKP memakai aturan tidak membuat SKP, termasuk bulan berturut-turut. Sel kosong tidak valid.</small></div>
          <div><label>File Excel sumber</label><input id="skpFile" type="file" accept=".xlsx,.xls,.csv"></div>
          <div class="sheet-source-control"><label>Sheet sumber yang dibaca</label><select id="skpSheet" disabled><option value="">Pilih file Excel terlebih dahulu</option></select><small>Pilih satu sheet yang berisi nilai SKP bulanan.</small></div>
          <div><label>Petugas impor</label><input id="skpImporter" value="EVKIN" placeholder="Nama petugas"></div>
        </div>
        <div id="skpSheetMeta" class="sheet-source-meta empty"><i data-lucide="table-2"></i><span><b>Belum ada sheet dipilih</b><small>Pilih file, lalu pastikan nama sheet dan jumlah barisnya benar.</small></span></div>
        <div class="actions-row"><a class="btn btn-secondary" href="assets/templates/Template_Penilaian_SKP.xlsx" download><i data-lucide="download"></i> Download Template</a><button id="skpPreview" class="btn btn-primary" disabled><i data-lucide="scan-search"></i> Preview Sheet Terpilih</button><button id="skpCommit" class="btn btn-success" disabled><i data-lucide="database-zap"></i> Konfirmasi Simpan</button><span id="skpImportInfo" class="muted"></span></div>
      </section>
      <section id="skpPreviewArea" class="card hidden"></section>`;
    const file = root.querySelector('#skpFile');
    const updateSheetMeta = () => {
      const select = root.querySelector('#skpSheet'); const meta = root.querySelector('#skpSheetMeta');
      if (!view.workbook || !view.file || !select.value) {
        meta.classList.add('empty'); meta.classList.remove('warning'); meta.innerHTML = '<i data-lucide="table-2"></i><span><b>Belum ada sheet dipilih</b><small>Pilih file, lalu pastikan nama sheet dan jumlah barisnya benar.</small></span>';
        return;
      }
      const sheet = view.workbook.Sheets[select.value];
      const rows = XLSX.utils.sheet_to_json(sheet, { defval:'', raw:false });
      const range = XLSX.utils.decode_range(sheet['!ref'] || 'A1:A1');
      const matrix = XLSX.utils.sheet_to_json(sheet, { header:1, defval:'', raw:false });
      const headers = (matrix[0] || []).map(value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, ''));
      const hasNip = headers.includes('nip'); const ready = hasNip && rows.length > 0;
      meta.classList.remove('empty'); meta.classList.toggle('warning', !ready);
      if (!hasNip) meta.innerHTML = `<i data-lucide="triangle-alert"></i><span><b>Sheet aktif: ${esc(select.value)} — bukan sheet data SKP</b><small>Kolom NIP tidak ditemukan. Pilih sheet data, bukan sheet petunjuk.</small></span>`;
      else if (!rows.length) meta.innerHTML = `<i data-lucide="triangle-alert"></i><span><b>Sheet aktif: ${esc(select.value)} — belum berisi data</b><small>${esc(view.file.name)} · format kolom terdeteksi · isi minimal satu baris SDM.</small></span>`;
      else meta.innerHTML = `<i data-lucide="circle-check-big"></i><span><b>Sheet aktif: ${esc(select.value)}</b><small>${esc(view.file.name)} · ${rows.length.toLocaleString('id-ID')} baris data · ${range.e.c + 1} kolom</small></span>`;
      root.querySelector('#skpPreview').disabled = !ready;
      if (window.lucide) lucide.createIcons();
    };
    file.onchange = async () => {
      view.file = file.files && file.files[0]; view.workbook = null; view.preview = null;
      const select = root.querySelector('#skpSheet');
      root.querySelector('#skpCommit').disabled = true;
      root.querySelector('#skpPreview').disabled = true;
      if (!view.file) { select.disabled = true; select.innerHTML = '<option value="">Pilih file Excel terlebih dahulu</option>'; updateSheetMeta(); return; }
      try {
        const bytes = await view.file.arrayBuffer();
        view.workbook = XLSX.read(bytes, { type: 'array', cellDates: true });
        select.innerHTML = view.workbook.SheetNames.map((name, index) => `<option value="${esc(name)}">${index + 1}. ${esc(name)}</option>`).join('');
        select.disabled = false;
        const dataSheet = view.workbook.SheetNames.find(name => {
          const sheet = view.workbook.Sheets[name];
          const lastColumn = Math.min(100, XLSX.utils.decode_range(sheet['!ref'] || 'A1').e.c);
          const headers = Array.from({length:lastColumn+1}, (_,col) => String((sheet[XLSX.utils.encode_cell({r:0,c:col})] || {}).v || '').toLowerCase().replace(/[^a-z0-9]/g,''));
          return headers.includes('nip') && headers.some(key => ['predikatkinerjaperiodik','predikat','predikatskp','nilaiskp'].includes(key));
        });
        if (dataSheet) select.value = dataSheet;
        root.querySelector('#skpImportInfo').textContent = `${view.workbook.SheetNames.length} sheet ditemukan. ${dataSheet ? 'Sheet data SKP dipilih otomatis; periksa periode penilaian.' : 'Pilih sheet data SKP yang memiliki NIP dan predikat.'}`;
        updateSheetMeta();
      } catch (error) {
        select.disabled = true; select.innerHTML = '<option value="">File tidak dapat dibaca</option>'; updateSheetMeta(); showError(error);
      }
    };
    root.querySelector('#skpSheet').onchange = () => { view.preview = null; root.querySelector('#skpCommit').disabled = true; updateSheetMeta(); };
    const invalidatePreview = () => { view.preview = null; root.querySelector('#skpCommit').disabled = true; root.querySelector('#skpPreviewArea').classList.add('hidden'); };
    root.querySelector('#skpImportMode').onchange = invalidatePreview;
    root.querySelector('#skpPeriod').onchange = event => { view.period = event.target.value; view.year = Number(view.period.slice(0, 4)); invalidatePreview(); };
    root.querySelector('#skpPreview').onclick = () => previewImport(root);
    root.querySelector('#skpCommit').onclick = () => commitImport(root);
  }

  function workbookRows(root) {
    if (!view.workbook || !view.file) throw new Error('Pilih file Excel terlebih dahulu.');
    const sheetName = root.querySelector('#skpSheet').value;
    const rows = XLSX.utils.sheet_to_json(view.workbook.Sheets[sheetName], { defval: '', raw: false });
    if (!rows.length) throw new Error('Sheet terpilih tidak berisi data.');
    return rows;
  }
  async function previewImport(root) {
    const button = root.querySelector('#skpPreview');
    try {
      button.disabled = true; const rows = workbookRows(root);
      const sourceFile = view.file, sourceSheet = root.querySelector('#skpSheet').value;
      const payload = { import_mode: root.querySelector('#skpImportMode').value, assessment_period: root.querySelector('#skpPeriod').value, source_file: view.file.name, rows };
      view.preview = null; root.querySelector('#skpCommit').disabled = true;
      const result = await api('/api/skp-assessment/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (sourceFile !== view.file || sourceSheet !== root.querySelector('#skpSheet').value || payload.import_mode !== root.querySelector('#skpImportMode').value || payload.assessment_period !== root.querySelector('#skpPeriod').value) return;
      view.preview = { payload, result };
      renderPreview(root, view.preview.result);
      root.querySelector('#skpCommit').disabled = !view.preview.result.valid_count;
    } catch (error) { showError(error); } finally { button.disabled = false; }
  }
  function renderPreview(root, data) {
    const area = root.querySelector('#skpPreviewArea'); area.classList.remove('hidden');
    if (data.import_mode === 'FINAL') {
      area.innerHTML = `<h3>Validasi Hasil Final SKP</h3><p>${num(data.row_count)} baris · ${num(data.valid_count)} valid · ${num(data.rejected_count)} ditolak. Menampilkan maksimal 100 baris; seluruh baris valid akan diproses.</p><div class="table-wrap"><table class="data-table sm"><thead><tr><th>NIP</th><th>Nama</th><th>Predikat sumber</th><th>Status laporan</th><th>Validasi</th></tr></thead><tbody>${data.rows.slice(0,100).map(row => `<tr><td>${esc(row.nip)}</td><td>${esc(row.nama)}</td><td>${esc(row.source_predicate)}</td><td>${esc(row.report_status)}</td><td>${esc(row.validation_status)} ${(row.issues || []).map(i => esc(i.message)).join('; ')}</td></tr>`).join('')}</tbody></table></div>`;
      return;
    }
    const metric = (row, code) => `${pill(row[code + '_status'])}<br><span class="muted">${esc(row[code + '_actual'] ?? '—')} / ${esc(row[code + '_target'] ?? '—')}${row[code + '_achievement_pct'] != null ? ` · ${esc(row[code + '_achievement_pct'])}%` : ''}</span>`;
    area.innerHTML = `<div class="ta-section-head"><div><h3>Hasil Validasi</h3><p class="muted">${num(data.row_count)} baris diperiksa · ${num(data.valid_count)} valid · ${num(data.rejected_count)} ditolak · ${num(data.warning_count)} peringatan · ${num(data.active_config_count)} aturan aktif</p></div>${pill(data.master_available ? 'MASTER TERHUBUNG' : 'MASTER KOSONG')}</div>
      <div class="table-wrap"><table class="data-table sm"><thead><tr><th>Baris</th><th>NIP/Nama</th><th>Predikat</th><th>HEK<br><span class="muted">realisasi/target</span></th><th>Verkom</th><th>Graduasi</th><th>P2K2</th><th>Validasi</th><th>Masalah</th></tr></thead><tbody>${data.rows.map(row => `<tr><td>${row.source_row}</td><td><b>${esc(row.nama || '-')}</b><br><span class="muted">${esc(row.nip)}</span></td><td>${esc(row.source_predicate || row.report_status)}</td><td>${metric(row,'hek')}</td><td>${metric(row,'verkom')}</td><td>${metric(row,'graduasi')}</td><td>${metric(row,'p2k2')}</td><td>${pill(row.validation_status)}</td><td>${(row.issues || []).map(i => `<div class="skp-issue ${i.severity.toLowerCase()}">${esc(i.message)}</div>`).join('') || '—'}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function configurationPanel(root) {
    root.querySelector('#skpPanel').innerHTML = `
      <section class="card"><div class="ta-section-head"><div><h3>Konfigurasi Target dan Ambang Indikator</h3><p class="muted">Aturan disimpan sebagai versi baru. Impor SKP merekam snapshot aturan sehingga histori bulan lama tidak berubah saat target berikutnya diganti.</p></div></div>
        <div class="alert info"><i data-lucide="info"></i><span><b>FIXED</b>: target angka dari konfigurasi. <b>WORKDAYS</b>: target HEK berasal dari hari kerja efektif pada file/periode. <b>FROM_IMPORT</b>: target wajib tersedia pada file sumber. Nilai kosong tetap “Belum Dinilai”, bukan nol.</span></div>
        <div class="form-row">
          <div><label>Indikator</label><select id="cfgIndicator"><option>HEK</option><option>VERKOM</option><option>GRADUASI</option><option>P2K2</option></select></div>
          <div><label>Mode target</label><select id="cfgMode"><option value="FIXED">Target tetap</option><option value="WORKDAYS">Hari kerja efektif</option><option value="FROM_IMPORT">Dari file impor</option></select></div>
          <div><label>Nilai target</label><input id="cfgTarget" type="number" min="0" step="0.01" value="100"></div>
          <div><label>Ambang mencapai (%)</label><input id="cfgThreshold" type="number" min="0.01" step="0.01" value="100"></div>
          <div><label>Satuan</label><input id="cfgUnit" value="kegiatan"></div>
          <div><label>Berlaku mulai</label><input id="cfgFrom" type="month" value="${esc(view.period)}"></div>
          <div><label>Berlaku sampai</label><input id="cfgTo" type="month"></div>
          <div><label>Lingkup</label><select id="cfgScope"><option value="ALL">Seluruh SDM</option><option value="UNIT">Unit</option><option value="JABATAN">Jabatan</option><option value="WILAYAH_3T">Wilayah 3T</option><option value="JENIS_SDM">Jenis SDM</option></select></div>
          <div><label>Nilai lingkup</label><input id="cfgScopeValue" placeholder="Kosong untuk seluruh SDM"></div>
          <div><label>Dasar/nomor rapat</label><input id="cfgDocument" placeholder="Nomor dokumen keputusan"></div>
          <div><label>Petugas</label><input id="cfgActor" value="EVKIN"></div>
        </div>
        <div class="actions-row"><button id="cfgDraft" class="btn btn-secondary">Simpan Draft</button><button id="cfgApprove" class="btn btn-primary">Simpan & Aktifkan Versi</button></div>
      </section><section class="card"><div class="ta-section-head"><div><h3>Versi Konfigurasi</h3><p class="muted">Versi aktif dipilih berdasarkan periode berlaku. Hapus menghentikan penggunaan versi pada impor berikutnya; snapshot penilaian lama dan audit tetap disimpan.</p></div><input id="cfgPeriod" type="month" value="${esc(view.period)}"></div>
        <div class="form-row"><div><label for="cfgDeleteActor">Petugas penghapusan</label><input id="cfgDeleteActor" type="text"></div><div class="skp-wide"><label for="cfgDeleteReason">Alasan penghapusan</label><input id="cfgDeleteReason" type="text" placeholder="Contoh: target salah atau versi dibuat dua kali"></div></div>
        <p id="cfgDeleteStatus" role="status"></p><div id="cfgList"></div></section>`;
    async function loadConfigs() {
      const period = root.querySelector('#cfgPeriod').value; view.period = period;
      const data = await api(`/api/skp-assessment/indicator-config?period=${encodeURIComponent(period)}`);
      root.querySelector('#cfgList').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>Indikator</th><th>Versi</th><th>Target</th><th>Ambang</th><th>Lingkup</th><th>Periode Berlaku</th><th>Dokumen</th><th>Status</th><th>Aksi</th></tr></thead><tbody>${(data.rows || []).map(row => `<tr><td><b>${esc(row.display_name)}</b><br><span class="muted">${esc(row.indicator_code)}</span></td><td>v${esc(row.version)}</td><td>${esc(row.target_mode)} · ${esc(row.target_value ?? 'dari impor')} ${esc(row.unit || '')}</td><td>${esc(row.reaches_min_percent)}%</td><td>${esc(row.scope_type)} ${esc(row.scope_value || '')}</td><td>${esc(row.effective_from)} s.d. ${esc(row.effective_to || 'seterusnya')}</td><td>${esc(row.meeting_document || '-')}</td><td>${pill(row.status)}</td><td><button type="button" class="btn btn-danger btn-sm" data-delete-config="${esc(row.id)}">Hapus</button></td></tr>`).join('') || '<tr><td colspan="9">Belum ada konfigurasi pada periode ini.</td></tr>'}</tbody></table></div>`;
      root.querySelectorAll('[data-delete-config]').forEach(button => {
        button.onclick = async () => {
          const actor = root.querySelector('#cfgDeleteActor').value.trim();
          const reason = root.querySelector('#cfgDeleteReason').value.trim();
          const status = root.querySelector('#cfgDeleteStatus');
          const row = data.rows.find(item => item.id === button.dataset.deleteConfig);
          if (!actor || !reason) { status.textContent = 'Isi nama petugas dan alasan penghapusan terlebih dahulu.'; return; }
          if (!confirm(`Hapus konfigurasi ${row.indicator_code} v${row.version} (${row.scope_type} ${row.scope_value || ''}, mulai ${row.effective_from})?\nVersi ini tidak dipakai untuk impor berikutnya. Versi lain yang aktif dan sesuai periode dapat menjadi penggantinya. Snapshot penilaian lama dan audit tetap disimpan.`)) return;
          button.disabled = true; status.textContent = 'Menghapus versi konfigurasi…';
          try {
            await api(`/api/skp-assessment/indicator-config/${encodeURIComponent(row.id)}`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify({actor,reason})});
            status.textContent = `${row.indicator_code} v${row.version} berhasil dihapus. Audit tersimpan.`;
            await loadConfigs();
          } catch(error) { status.textContent = error.message; }
          finally { if (button.isConnected) button.disabled = false; }
        };
      });
    }
    async function saveConfig(status) {
      const payload = { indicator_code: root.querySelector('#cfgIndicator').value, display_name: root.querySelector('#cfgIndicator').value, target_mode: root.querySelector('#cfgMode').value, target_value: root.querySelector('#cfgTarget').value, reaches_min_percent: root.querySelector('#cfgThreshold').value, unit: root.querySelector('#cfgUnit').value, effective_from: root.querySelector('#cfgFrom').value, effective_to: root.querySelector('#cfgTo').value, scope_type: root.querySelector('#cfgScope').value, scope_value: root.querySelector('#cfgScopeValue').value, meeting_document: root.querySelector('#cfgDocument').value, legal_basis: 'Keputusan internal penilaian indikator', created_by: root.querySelector('#cfgActor').value, status };
      await api('/api/skp-assessment/indicator-config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      EVKIN.toast(`Versi konfigurasi ${status === 'APPROVED' ? 'diaktifkan' : 'disimpan sebagai draft'}.`, 'success'); await loadConfigs();
    }
    root.querySelector('#cfgDraft').onclick = () => saveConfig('DRAFT').catch(showError);
    root.querySelector('#cfgApprove').onclick = () => saveConfig('APPROVED').catch(showError);
    root.querySelector('#cfgPeriod').onchange = () => loadConfigs().catch(showError);
    root.querySelector('#cfgMode').onchange = event => { root.querySelector('#cfgTarget').disabled = event.target.value !== 'FIXED'; };
    await loadConfigs();
  }
  async function commitImport(root) {
    if (!view.preview) return;
    const button = root.querySelector('#skpCommit');
    try {
      button.disabled = true;
      const payload = { ...view.preview.payload, confirmed: true, imported_by: root.querySelector('#skpImporter').value.trim() };
      if (payload.import_mode === 'FINAL') {
        if (!payload.imported_by) throw new Error('Nama petugas wajib diisi.');
        if (!window.confirm(`Konfirmasi HASIL FINAL SKP periode ${payload.assessment_period}: ${view.preview.result.valid_count} baris valid langsung disetujui, ${view.preview.result.rejected_count} ditolak. Data SKP lama pada NIP yang sama akan diganti. Tanda - / tidak bisa dinilai / tidak membuat SKP mengikuti aturan potongan beruntun. Lanjutkan?`)) return;
        payload.final_confirmed = true;
      }
      const result = await api('/api/skp-assessment/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (payload.import_mode === 'FINAL') {
        view.preview = null;
        EVKIN.toast(`${result.imported} hasil final SKP disetujui dan dihitung.`, 'success');
        EVKIN.tukinAnnualMod.openPeriod(payload.assessment_period);
        return;
      }
      EVKIN.toast(`${result.imported} data SKP disimpan untuk direview.`, 'success');
      view.tab = 'classification'; view.preview = null; shell(root); bindShell(root); await renderTab(root);
    } catch (error) { showError(error); } finally { if (button.isConnected) button.disabled = false; }
  }

  function listPanel(root, mode) {
    const reviewing = mode === 'review';
    root.querySelector('#skpPanel').innerHTML = `
      <section class="card">
        <div class="ta-section-head"><div><h3>${reviewing ? 'Review dan Persetujuan' : 'Klasifikasi dan Rekomendasi'}</h3><p class="muted">${reviewing ? 'Periksa sumber, rekomendasi, alasan, dan eviden sebelum menyetujui nilai final.' : 'Filter indikator lalu tetapkan rekomendasi untuk banyak SDM sekaligus.'}</p></div></div>
        <div class="form-row skp-filter-row">
          <div><label>Periode</label><input id="skpListPeriod" type="month" value="${esc(view.period)}"></div>
          <div><label>Cari</label><input id="skpSearch" placeholder="NIP atau nama"></div>
          <div><label>Status review</label><select id="skpReviewFilter"><option value="">Semua</option>${['PENDING_REVIEW','RECOMMENDED','RETURNED','APPROVED'].map(v => `<option>${v}</option>`).join('')}</select></div>
          <div><label>Indikator</label><select id="skpIndicator"><option value="">Semua</option><option value="hek">HEK</option><option value="verkom">Verkom</option><option value="graduasi">Graduasi</option><option value="p2k2">P2K2</option></select></div>
          <div><label>Kondisi</label><select id="skpIndicatorStatus"><option value="">Semua</option>${['MENCAPAI','KURANG','TIDAK_ADA','BELUM_DINILAI'].map(v => `<option>${v}</option>`).join('')}</select></div>
          <div class="skp-filter-action"><button id="skpApplyFilter" class="btn btn-secondary">Terapkan Filter</button></div>
        </div>
      </section>
      <div id="skpStats" class="stat-grid"></div>
      <section class="card">
        <div class="skp-bulk-box">
          ${reviewing ? `<div><label>Predikat final (opsional)</label><select id="skpFinalPredicate"><option value="">Gunakan rekomendasi</option>${predicateOptions()}</select></div><div><label>Nama penyetuju</label><input id="skpApprover" value="EVKIN"></div><div class="skp-wide"><label>Catatan review/pengembalian</label><input id="skpReviewNotes" placeholder="Wajib jika dikembalikan"></div><div class="actions-row"><button id="skpApprove" class="btn btn-success">Setujui Terpilih</button><button id="skpReturn" class="btn btn-danger">Kembalikan</button></div>`
            : `<div><label>Rekomendasi predikat</label><select id="skpRecommendation">${predicateOptions()}</select></div>${indicatorEditors()}<div><label>Tanggal rapat</label><input id="skpMeetingDate" type="date"></div><div><label>Nomor dokumen rapat</label><input id="skpMeetingDocument" placeholder="BA/NOTULEN/..."></div><div class="skp-wide"><label>Alasan keputusan</label><input id="skpReason" placeholder="Contoh: Verkom tidak mencapai target setelah mempertimbangkan HEK dan indikator lain"></div><div><label>Referensi eviden</label><input id="skpEvidence" placeholder="Nomor/lokasi dokumen"></div><div><label>Nama reviewer</label><input id="skpReviewer" value="EVKIN"></div><div class="actions-row"><button id="skpRecommend" class="btn btn-primary">Rekam Keputusan untuk Data Terpilih</button></div>`}
        </div>
        <div id="skpList"><div class="muted">Memuat data…</div></div>
        <details><summary>Kelola / hapus data SKP</summary>
          <p>Penghapusan hanya untuk periode terbuka. Sumber impor dan audit tetap disimpan. Hasil Tukin terkait perlu direview ulang. Pembatalan batch hanya menghapus penilaian yang masih berasal dari batch tersebut, bukan memulihkan versi sebelum impor.</p>
          <div class="form-row"><div><label>Nama petugas</label><input id="skpDeleteActor"></div><div><label>Alasan penghapusan</label><input id="skpDeleteReason"></div></div>
          <div class="actions-row"><button id="skpDeleteSelected" class="btn btn-danger">Hapus SKP Terpilih</button><button id="skpResetPeriod" class="btn btn-danger">Reset SKP Per Periode</button></div>
          <div class="form-row"><div><label>Batch impor pada periode ini</label><select id="skpDeleteBatch"><option value="">Muat daftar batch terlebih dahulu</option></select></div><button id="skpLoadBatches" class="btn btn-secondary">Muat Batch Impor</button><button id="skpCancelBatch" class="btn btn-danger">Batalkan Batch Impor</button></div>
          <div id="skpRemovalStatus" role="status"></div>
          <div class="form-row"><div><label>NIP untuk melihat audit (termasuk yang dihapus)</label><input id="skpDeletedAuditNip"></div><button id="skpDeletedAudit" class="btn btn-secondary">Lihat Audit NIP</button></div>
        </details>
      </section>`;
    root.querySelector('#skpDeleteSelected').onclick = () => removeSkp(root, 'selected', reviewing);
    root.querySelector('#skpDeletedAudit').onclick = () => showAudit(root, root.querySelector('#skpDeletedAuditNip').value.trim());
    root.querySelector('#skpResetPeriod').onclick = () => removeSkp(root, 'period', reviewing);
    root.querySelector('#skpCancelBatch').onclick = () => removeSkp(root, 'batch', reviewing);
    root.querySelector('#skpLoadBatches').onclick = async () => {
      try {
        const period = root.querySelector('#skpListPeriod').value;
        const result = await api('/api/skp-assessment/import-batches?assessment_period='+encodeURIComponent(period));
        root.querySelector('#skpDeleteBatch').innerHTML = '<option value="">Pilih batch</option>'+result.batches.map(batch=>`<option value="${esc(batch.id)}" ${batch.status==='CANCELLED'?'disabled':''}>${esc(batch.source_file)} · ${esc(batch.created_at)} · ${batch.current_rows} penilaian aktif · ${esc(batch.status)} · ${esc(batch.id)}</option>`).join('');
      } catch(error) { showError(error); }
    };
    root.querySelector('#skpApplyFilter').onclick = () => { view.page = 1; loadRows(root, reviewing).catch(showError); };
    root.querySelector('#skpListPeriod').onchange = event => { view.period = event.target.value; view.year = Number(view.period.slice(0, 4)); view.page = 1; loadRows(root, reviewing).catch(showError); };
    if (reviewing) {
      root.querySelector('#skpApprove').onclick = () => submitReview(root, 'APPROVE');
      root.querySelector('#skpReturn').onclick = () => submitReview(root, 'RETURN');
    } else root.querySelector('#skpRecommend').onclick = () => submitRecommendation(root);
  }
  function predicateOptions() { return ['Sangat Baik','Baik','Butuh Perbaikan','Kurang','Sangat Kurang'].map(value => `<option>${value}</option>`).join(''); }

  async function removeSkp(root, mode, reviewing) {
    const status = root.querySelector('#skpRemovalStatus');
    const buttons = ['#skpDeleteSelected','#skpResetPeriod','#skpCancelBatch'].map(id=>root.querySelector(id));
    if (buttons.some(button=>button.disabled)) return;
    buttons.forEach(button=>button.disabled=true);
    try {
      const payload = {mode, assessment_period:root.querySelector('#skpListPeriod').value,
        nips:[...view.selected], batch_id:root.querySelector('#skpDeleteBatch').value,
        actor:root.querySelector('#skpDeleteActor').value.trim(), reason:root.querySelector('#skpDeleteReason').value.trim()};
      if (!payload.actor || !payload.reason) throw new Error('Isi nama petugas dan alasan terlebih dahulu.');
      status.textContent = 'Memeriksa cakupan dan status periode...';
      const preview = await api('/api/skp-assessment/removal/preview', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if (!preview.count && mode !== 'batch') throw new Error('Tidak ada penilaian yang akan dihapus.');
      if (!confirm(`${mode==='period'?'RESET SELURUH SKP PERIODE':mode==='batch'?'BATALKAN BATCH IMPOR':'HAPUS SKP TERPILIH'} ${payload.assessment_period}\n${preview.count} penilaian (${preview.approved_count} sudah disetujui) akan dihapus.\nSumber/audit tetap disimpan. Hasil Tukin terkait ditahan untuk review ulang.\nLanjutkan?`)) {status.textContent='Tindakan dibatalkan; tidak ada perubahan.';return;}
      status.textContent = 'Menghapus penilaian dan mencatat audit. Tunggu sampai proses selesai...';
      const result = await api('/api/skp-assessment/removal/confirm', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,confirmed:true,preview_token:preview.preview_token})});
      status.textContent = `${result.deleted} penilaian dihapus. Audit tersimpan. Hasil Tukin terkait perlu direview ulang.`;
      view.selected.clear(); await loadRows(root,reviewing);
      root.querySelector('#skpDeleteBatch').innerHTML='<option value="">Muat ulang daftar batch</option>';
    } catch(error) {status.textContent=error.message;showError(error);}
    finally {buttons.forEach(button=>button.disabled=false);}
  }
  function indicatorEditors() {
    return ['HEK','Verkom','Graduasi','P2K2'].map(label => `<div><label>${label}</label><select id="skpEdit${label}"><option value="">Tidak diubah</option><option>MENCAPAI</option><option>KURANG</option><option>TIDAK_ADA</option><option>BELUM_DINILAI</option></select></div>`).join('');
  }
  async function loadRows(root, reviewing) {
    const params = new URLSearchParams({ assessment_period: root.querySelector('#skpListPeriod').value, q: root.querySelector('#skpSearch').value.trim(), review_status: root.querySelector('#skpReviewFilter').value, indicator: root.querySelector('#skpIndicator').value, indicator_status: root.querySelector('#skpIndicatorStatus').value, page: view.page, per_page: 100 });
    const data = await api('/api/skp-assessment/rows?' + params.toString()); view.rows = data.rows || []; view.pages = data.pages || 1; view.selected.clear();
    const s = data.summary || {};
    root.querySelector('#skpStats').innerHTML = [['Total',s.total,'users','blue'],['Disetujui',s.approved,'badge-check','green'],['Menunggu Review',s.pending,'clock-3','yellow'],['Tidak Membuat',s.not_submitted,'file-x','red'],['Kurang/Sangat Kurang',s.low_predicate,'trending-down','red']].map(item => `<div class="stat-card ${item[3]}"><div class="stat-icon"><i data-lucide="${item[2]}"></i></div><div><div class="stat-val">${Number(item[1] || 0).toLocaleString('id-ID')}</div><div class="stat-label">${item[0]}</div></div></div>`).join('');
    const indicatorCell = (row, code) => `${pill(row[code + '_status'])}<br><span class="muted">${esc(row[code + '_actual'] ?? '—')}/${esc(row[code + '_target'] ?? '—')}</span>`;
    root.querySelector('#skpList').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th><input id="skpAll" type="checkbox"></th><th>SDM</th><th>Sumber</th><th>Rekomendasi</th><th>Final</th><th>HEK</th><th>Verkom</th><th>Graduasi</th><th>P2K2</th><th>Alasan/Eviden</th><th>Status</th><th>Audit</th></tr></thead><tbody>${view.rows.map(row => `<tr><td><input class="skp-check" type="checkbox" value="${esc(row.nip)}"></td><td><b>${esc(row.nama || '-')}</b><br><span class="muted">${esc(row.nip)}</span></td><td>${esc(row.source_predicate || row.report_status)}</td><td>${esc(row.recommended_predicate || '-')}</td><td>${esc(row.final_predicate || '-')}</td><td>${indicatorCell(row,'hek')}</td><td>${indicatorCell(row,'verkom')}</td><td>${indicatorCell(row,'graduasi')}</td><td>${indicatorCell(row,'p2k2')}</td><td>${esc(row.recommendation_reason || '-')}<br><span class="muted">${esc(row.evidence_ref || '')}</span></td><td>${pill(row.review_status)}</td><td><button class="btn btn-sm btn-ghost skp-audit" data-nip="${esc(row.nip)}">Lihat</button></td></tr>`).join('') || '<tr><td colspan="12">Belum ada data sesuai filter.</td></tr>'}</tbody></table></div><div class="ta-pager"><span>Halaman ${data.page} dari ${data.pages} · ${data.total} SDM</span><div><button id="skpPrev" class="btn btn-sm btn-secondary" ${data.page <= 1 ? 'disabled' : ''}>Sebelumnya</button> <button id="skpNext" class="btn btn-sm btn-secondary" ${data.page >= data.pages ? 'disabled' : ''}>Berikutnya</button></div></div><div id="skpAuditDetail"></div>`;
    const all = root.querySelector('#skpAll');
    all.onchange = () => root.querySelectorAll('.skp-check').forEach(box => { box.checked = all.checked; toggleSelection(box); });
    root.querySelectorAll('.skp-check').forEach(box => box.onchange = () => toggleSelection(box));
    root.querySelectorAll('.skp-audit').forEach(button => button.onclick = () => showAudit(root, button.dataset.nip));
    root.querySelector('#skpPrev').onclick = () => { view.page--; loadRows(root, reviewing).catch(showError); };
    root.querySelector('#skpNext').onclick = () => { view.page++; loadRows(root, reviewing).catch(showError); };
    if (window.lucide) lucide.createIcons();
  }
  function toggleSelection(box) { if (box.checked) view.selected.add(box.value); else view.selected.delete(box.value); }
  async function submitRecommendation(root) {
    try {
      const nips = [...view.selected]; if (!nips.length) throw new Error('Pilih minimal satu SDM.');
      const meetingDate = root.querySelector('#skpMeetingDate').value; const documentNumber = root.querySelector('#skpMeetingDocument').value.trim();
      if (!meetingDate || !documentNumber) throw new Error('Tanggal dan nomor dokumen rapat wajib diisi agar keputusan terdokumentasi.');
      const payload = { assessment_period: view.period, nips, recommended_predicate: root.querySelector('#skpRecommendation').value, reason: root.querySelector('#skpReason').value, evidence_ref: root.querySelector('#skpEvidence').value, reviewed_by: root.querySelector('#skpReviewer').value, meeting_date: meetingDate, document_number: documentNumber, hek_status: root.querySelector('#skpEditHEK').value, verkom_status: root.querySelector('#skpEditVerkom').value, graduasi_status: root.querySelector('#skpEditGraduasi').value, p2k2_status: root.querySelector('#skpEditP2K2').value };
      const result = await api('/api/skp-assessment/recommend', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      EVKIN.toast(`${result.updated} penilaian diperbarui.`, 'success'); await loadRows(root, false);
    } catch (error) { showError(error); }
  }
  async function submitReview(root, action) {
    try {
      const nips = [...view.selected]; if (!nips.length) throw new Error('Pilih minimal satu SDM.');
      const payload = { assessment_period: view.period, nips, action, final_predicate: root.querySelector('#skpFinalPredicate').value, approved_by: root.querySelector('#skpApprover').value, notes: root.querySelector('#skpReviewNotes').value };
      const result = await api('/api/skp-assessment/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      EVKIN.toast(`${result.updated} penilaian ${action === 'APPROVE' ? 'disetujui' : 'dikembalikan'}.`, 'success'); await loadRows(root, true);
    } catch (error) { showError(error); }
  }
  async function showAudit(root, nip) {
    try {
      const data = await api(`/api/skp-assessment/audit/${encodeURIComponent(view.period)}/${encodeURIComponent(nip)}`);
      const a = data.assessment || {nip, assessment_period:view.period, review_status:'DIHAPUS'}; const target = root.querySelector('#skpAuditDetail');
      const detailMetric = code => `${esc(a[code + '_actual'] ?? '—')} / ${esc(a[code + '_target'] ?? '—')} · ${esc(a[code + '_achievement_pct'] ?? '—')}% · ${esc(a[code + '_status'] || 'BELUM_DINILAI')}<br><span class="muted">Pokja: ${esc(a[code + '_pokja_recommendation'] || '—')}</span>`;
      target.innerHTML = `<div class="skp-audit-card"><div class="ta-section-head"><div><h3>Dokumentasi · ${esc(a.nama || a.nip)}</h3><p class="muted">${esc(a.nip)} · ${esc(a.assessment_period)} · Batch rapat: ${esc(a.meeting_batch_id || 'belum ada')}</p></div><button id="skpCloseAudit" class="btn btn-sm btn-ghost">Tutup</button></div><div class="skp-audit-grid"><div><b>Sumber</b><span>${esc(a.source_predicate || '-')}</span></div><div><b>Rekomendasi</b><span>${esc(a.recommended_predicate || '-')}</span></div><div><b>Final</b><span>${esc(a.final_predicate || '-')}</span></div><div><b>Status</b><span>${esc(a.review_status)}</span></div><div><b>Alasan</b><span>${esc(a.recommendation_reason || '-')}</span></div><div><b>Eviden</b><span>${esc(a.evidence_ref || '-')}</span></div></div><h4>Capaian Indikator</h4><div class="skp-audit-grid"><div><b>HEK</b><span>${detailMetric('hek')}</span></div><div><b>Verkom</b><span>${detailMetric('verkom')}</span></div><div><b>Graduasi</b><span>${detailMetric('graduasi')}</span></div><div><b>P2K2</b><span>${detailMetric('p2k2')}</span></div></div><h4>Riwayat Keputusan</h4><div class="table-wrap"><table class="data-table sm"><thead><tr><th>Waktu</th><th>Aksi</th><th>Dari</th><th>Menjadi</th><th>Alasan</th><th>Petugas</th></tr></thead><tbody>${(data.audit || []).map(e => `<tr><td>${esc(e.created_at)}</td><td>${esc(e.action)}</td><td>${esc(e.old_value || '-')}</td><td>${esc(e.new_value || '-')}</td><td>${esc(e.reason || '-')}</td><td>${esc(e.actor || '-')}</td></tr>`).join('')}</tbody></table></div></div>`;
      target.querySelector('#skpCloseAudit').onclick = () => { target.innerHTML = ''; };
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) { showError(error); }
  }

  async function exceptionPanel(root) {
    root.querySelector('#skpPanel').innerHTML = `
      <section class="card"><div class="ta-section-head"><div><h3>Hukdis dan Keputusan Kondisi</h3><p class="muted">Catat keputusan satu kali di sini. Efek pembayaran otomatis tersinkron ke Pengelolaan Tukin; predikat SKP tidak berubah kecuali rekomendasi predikat dipilih dan kemudian disetujui pada tahap Review.</p></div></div>
        <div class="form-row"><div><label>Jenis kondisi</label><select id="cdCode"><option value="HUKDIS">Hukuman Disiplin</option><option value="LAINNYA">Kondisi Lainnya</option></select></div><div><label>Tanggal mulai</label><input id="cdStart" type="date"></div><div><label>Tanggal selesai</label><input id="cdEnd" type="date"></div><div><label>Efek ke SKP</label><select id="cdSkpEffect"><option value="NONE">Tidak mengubah predikat</option><option value="RECOMMEND_PREDICATE">Rekomendasikan predikat</option></select></div><div><label>Predikat rekomendasi</label><select id="cdPredicate" disabled><option>Sangat Baik</option><option>Baik</option><option>Butuh Perbaikan</option><option>Kurang</option><option>Sangat Kurang</option></select></div><div><label>Efek pembayaran</label><select id="cdPaymentEffect"><option value="HOLD">HOLD / tahan verifikasi</option><option value="UNPAID">Tidak dibayarkan</option><option value="NONE">Tidak mengubah pembayaran</option></select></div></div>
        <div class="form-row"><div class="skp-wide"><label>Alasan / dasar keputusan</label><input id="cdReason" placeholder="Uraian hasil verifikasi atau rapat"></div><div><label>Nomor dokumen</label><input id="cdDocument" placeholder="Nomor SK/surat/berita acara"></div><div><label>Referensi eviden</label><input id="cdEvidence" placeholder="Lokasi/nomor berkas bukti"></div><div><label>Disetujui oleh</label><input id="cdApprover" value="EVKIN"></div></div>
        <div class="actions-row"><button id="cdSave" class="btn btn-primary"><i data-lucide="shield-check"></i> Terapkan ke SDM Terpilih</button></div>
      </section>
      <section class="card"><div class="ta-section-head"><div><h3>Pengecualian Resmi Penilaian SKP</h3><p class="muted">Gunakan hanya berdasarkan dokumen sah. Pengecualian mencegah status “Tidak Bisa Dinilai” diperlakukan sebagai tidak membuat SKP.</p></div></div>
        <div class="form-row"><div><label>Periode</label><input id="exPeriod" type="month" value="${esc(view.period)}"></div><div><label>Jenis</label><select id="exCode"><option value="CUTI_MELAHIRKAN">Cuti Melahirkan</option><option value="TUGAS_BELAJAR">Tugas Belajar</option><option value="MENINGGAL">Meninggal Dunia</option><option value="LAINNYA_RESMI">Lainnya Resmi</option></select></div><div><label id="exStartLabel">Tanggal mulai</label><input id="exStart" type="date"></div><div id="exEndWrap"><label>Tanggal selesai</label><input id="exEnd" type="date"></div><div><label>Disetujui oleh</label><input id="exApprover" value="EVKIN"></div><div class="skp-wide"><label>Alasan</label><input id="exReason" placeholder="Alasan pengecualian"></div><div class="skp-wide"><label>Referensi eviden</label><input id="exEvidence" placeholder="Nomor surat/dokumen wajib"></div></div>
        <div id="exDeathPayment" class="hidden"><div class="alert info"><i data-lucide="shield-check"></i><span>SKP bulan meninggal dibebaskan. Pembayaran default ditahan untuk review dan transaksi baru dihentikan mulai bulan berikutnya.</span></div><div class="form-row"><div><label>Keputusan pembayaran bulan kejadian</label><select id="exPaymentDecision"><option value="HOLD_REVIEW">Tahan untuk verifikasi</option><option value="NORMAL_ACCOUNT">Bayarkan ke rekening pegawai</option><option value="UNPAID">Tidak dibayarkan berdasarkan keputusan</option></select></div><div class="skp-wide"><label>Catatan keputusan pembayaran</label><input id="exPaymentNotes" placeholder="Dasar keputusan pengelola keuangan"></div><div><label><input id="exPayToHeir" type="checkbox"> Pembayaran kepada ahli waris</label></div></div>
          <div id="exHeirFields" class="form-row hidden"><div><label>Nama ahli waris</label><input id="exHeirName"></div><div><label>Hubungan</label><input id="exHeirRelationship" placeholder="Suami/Istri/Anak/dll."></div><div><label>Bank</label><input id="exHeirBank"></div><div><label>No. rekening</label><input id="exHeirAccount"></div><div><label>Nama pemilik rekening</label><input id="exHeirHolder"></div><div class="skp-wide"><label>Dokumen ahli waris</label><input id="exHeirDocument" placeholder="Nomor surat keterangan ahli waris"></div></div></div>
        <div class="actions-row"><button id="exSave" class="btn btn-primary">Terapkan ke SDM Terpilih</button></div>
      </section><section class="card"><div class="ta-section-head"><div><h3>Pilih SDM</h3><p class="muted">Pilihan ini digunakan oleh formulir keputusan kondisi maupun pengecualian resmi di atas.</p></div></div><div id="exCandidates"></div></section><section class="card"><h3>Riwayat Hukdis dan Keputusan Kondisi</h3><div id="cdHistory"></div><h3 style="margin-top:22px">Riwayat Pengecualian Periode</h3><div id="exHistory"></div></section>`;
    async function load() {
      view.period = root.querySelector('#exPeriod').value; view.selected.clear();
      const [data, history, decisions] = await Promise.all([
        api(`/api/skp-assessment/rows?assessment_period=${encodeURIComponent(view.period)}&page=1&per_page=500`),
        api(`/api/skp-assessment/exceptions?assessment_period=${encodeURIComponent(view.period)}`),
        api(`/api/skp-assessment/conditions?assessment_period=${encodeURIComponent(view.period)}`),
      ]);
      root.querySelector('#exCandidates').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th><input id="exAll" type="checkbox"></th><th>SDM</th><th>Status Laporan</th><th>Predikat Sumber</th><th>Status Review</th></tr></thead><tbody>${(data.rows || []).map(row => `<tr><td><input class="ex-check" type="checkbox" value="${esc(row.nip)}"></td><td><b>${esc(row.nama)}</b><br><span class="muted">${esc(row.nip)}</span></td><td>${pill(row.report_status)}</td><td>${esc(row.source_predicate || '-')}</td><td>${pill(row.review_status)}</td></tr>`).join('') || '<tr><td colspan="5">Belum ada data SKP untuk periode ini.</td></tr>'}</tbody></table></div>`;
      root.querySelector('#exHistory').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>NIP</th><th>Jenis</th><th>Tanggal</th><th>Keputusan Pembayaran</th><th>Penerima</th><th>Alasan/Eviden</th><th>Penyetuju</th></tr></thead><tbody>${(history.rows || []).map(row => `<tr><td>${esc(row.nip)}</td><td>${esc(row.exception_code)}</td><td>${esc(row.death_date || row.start_date || '—')}${row.end_date ? ` s.d. ${esc(row.end_date)}` : ''}</td><td>${row.exception_code === 'MENINGGAL' ? pill(row.payment_decision || 'HOLD_REVIEW') : '—'}</td><td>${row.pay_to_heir ? `<b>Ahli waris</b><br>${esc(row.heir_name)} · ${esc(row.heir_relationship)}` : row.exception_code === 'MENINGGAL' ? 'Rekening pegawai/menunggu keputusan' : '—'}</td><td>${esc(row.reason)}<br><span class="muted">${esc(row.evidence_ref)}</span></td><td>${esc(row.approved_by)}</td></tr>`).join('') || '<tr><td colspan="7">Belum ada pengecualian.</td></tr>'}</tbody></table></div>`;
      root.querySelector('#cdHistory').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>SDM</th><th>Kondisi</th><th>Efek SKP</th><th>Efek Pembayaran</th><th>Dokumen/Eviden</th><th>Keputusan</th><th>Sinkron Tukin</th></tr></thead><tbody>${(decisions.rows || []).map(row => `<tr><td><b>${esc(row.nama || '-')}</b><br><span class="muted">${esc(row.nip)}</span></td><td>${esc(row.condition_code)}<br><span class="muted">${esc(row.start_date || '—')} s.d. ${esc(row.end_date || '—')}</span></td><td>${row.skp_effect === 'RECOMMEND_PREDICATE' ? `Rekomendasi ${esc(row.recommended_predicate)}` : 'Predikat tetap'}</td><td>${pill(row.payment_effect)}</td><td>${esc(row.document_number)}<br><span class="muted">${esc(row.evidence_ref)}</span></td><td>${esc(row.reason)}<br><span class="muted">${esc(row.approved_by)} · ${esc(row.approved_at)}</span></td><td>${pill(row.synced_to_tukin ? 'TERSINKRON' : 'MENUNGGU DATA FINAL')}</td></tr>`).join('') || '<tr><td colspan="7">Belum ada keputusan kondisi.</td></tr>'}</tbody></table></div>`;
      const all = root.querySelector('#exAll'); if (all) all.onchange = () => root.querySelectorAll('.ex-check').forEach(box => { box.checked = all.checked; toggleSelection(box); });
      root.querySelectorAll('.ex-check').forEach(box => box.onchange = () => toggleSelection(box));
    }
    root.querySelector('#exPeriod').onchange = () => load().catch(showError);
    function toggleDeathFields() {
      const deceased = root.querySelector('#exCode').value === 'MENINGGAL';
      root.querySelector('#exDeathPayment').classList.toggle('hidden', !deceased);
      root.querySelector('#exEndWrap').classList.toggle('hidden', deceased);
      root.querySelector('#exStartLabel').textContent = deceased ? 'Tanggal meninggal' : 'Tanggal mulai';
      if (deceased) root.querySelector('#exEnd').value = '';
      else {
        root.querySelector('#exPayToHeir').checked = false;
        root.querySelector('#exHeirFields').classList.add('hidden');
        root.querySelector('#exPaymentDecision').disabled = false;
      }
    }
    root.querySelector('#exCode').onchange = toggleDeathFields;
    root.querySelector('#cdSkpEffect').onchange = event => {
      root.querySelector('#cdPredicate').disabled = event.target.value !== 'RECOMMEND_PREDICATE';
    };
    root.querySelector('#cdSave').onclick = async () => {
      try {
        if (!view.selected.size) throw new Error('Pilih minimal satu SDM.');
        const payload = { assessment_period:view.period, nips:[...view.selected], condition_code:root.querySelector('#cdCode').value, start_date:root.querySelector('#cdStart').value || null, end_date:root.querySelector('#cdEnd').value || null, skp_effect:root.querySelector('#cdSkpEffect').value, recommended_predicate:root.querySelector('#cdPredicate').value, payment_effect:root.querySelector('#cdPaymentEffect').value, reason:root.querySelector('#cdReason').value, document_number:root.querySelector('#cdDocument').value, evidence_ref:root.querySelector('#cdEvidence').value, approved_by:root.querySelector('#cdApprover').value };
        const result = await api('/api/skp-assessment/conditions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        EVKIN.toast(`${result.updated} keputusan disimpan; ${result.synced_to_tukin} tersinkron ke Tukin.`, 'success'); await load();
      } catch (error) { showError(error); }
    };
    root.querySelector('#exPayToHeir').onchange = event => {
      root.querySelector('#exHeirFields').classList.toggle('hidden', !event.target.checked);
      root.querySelector('#exPaymentDecision').disabled = event.target.checked;
    };
    root.querySelector('#exSave').onclick = async () => {
      try {
        if (!view.selected.size) throw new Error('Pilih minimal satu SDM.');
        const payload = { assessment_period:view.period, nips:[...view.selected], exception_code:root.querySelector('#exCode').value, start_date:root.querySelector('#exStart').value, end_date:root.querySelector('#exEnd').value, reason:root.querySelector('#exReason').value, evidence_ref:root.querySelector('#exEvidence').value, approved_by:root.querySelector('#exApprover').value, payment_decision:root.querySelector('#exPaymentDecision').value, payment_notes:root.querySelector('#exPaymentNotes').value, pay_to_heir:root.querySelector('#exPayToHeir').checked, heir_name:root.querySelector('#exHeirName').value, heir_relationship:root.querySelector('#exHeirRelationship').value, heir_bank_name:root.querySelector('#exHeirBank').value, heir_account_number:root.querySelector('#exHeirAccount').value, heir_account_holder:root.querySelector('#exHeirHolder').value, heir_document_ref:root.querySelector('#exHeirDocument').value };
        const result = await api('/api/skp-assessment/exceptions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        EVKIN.toast(`${result.updated} pengecualian tercatat. Tetap lakukan review final.`, 'success'); await load();
      } catch (error) { showError(error); }
    };
    toggleDeathFields();
    await load();
  }

  async function annualPanel(root) {
    root.querySelector('#skpPanel').innerHTML = `<section class="card"><div class="ta-section-head"><div><h3>Rekap SKP Januari–Desember</h3><p class="muted">Matriks per SDM, ringkasan Semester I/II, dan seluruh bulan tidak membuat SKP.</p></div><div class="ta-filter"><input id="skpAnnualSearch" placeholder="Cari NIP atau nama"><select id="skpYear">${[2025,2026,2027].map(y => `<option ${y === view.year ? 'selected' : ''}>${y}</option>`).join('')}</select><button id="skpAnnualApply" class="btn btn-secondary">Terapkan</button></div></div><div id="skpAnnualMatrix"><div class="muted">Memuat rekap…</div></div></section><section class="card"><div class="ta-section-head"><div><h3>Aturan Tiga Bulan Tidak Membuat SKP</h3><p class="muted">Aturan pembayaran diterapkan otomatis dan tidak dapat diubah dari konfigurasi.</p></div></div><div class="alert warning"><i data-lucide="shield-alert"></i><span><b>Bulan pertama:</b> potongan komponen SKP 35%. <b>Bulan kedua:</b> potongan komponen SKP 70%. <b>Bulan ketiga dan seterusnya secara berturut-turut:</b> Tukin tidak dibayarkan (<b>UNPAID</b>) sampai SDM kembali membuat SKP pada bulan penilaian berikutnya.</span></div></section>`;
    async function loadAnnual() {
      const year = Number(root.querySelector('#skpYear').value); view.year = year;
      const data = await api(`/api/skp-assessment/annual?year=${year}&q=${encodeURIComponent(root.querySelector('#skpAnnualSearch').value.trim())}`);
      root.querySelector('#skpAnnualMatrix').innerHTML = `<div class="table-wrap ta-matrix-wrap"><table class="data-table sm ta-matrix"><thead><tr><th>NIP/Nama</th>${MONTHS.map((m,i) => `<th class="${i === 6 ? 'semester-cut' : ''}">${m}</th>`).join('')}<th>Sem I</th><th>Sem II</th><th>Tidak Membuat</th></tr></thead><tbody>${(data.rows || []).map(person => `<tr><td><b>${esc(person.nama || '-')}</b><br><span class="muted">${esc(person.nip)}</span></td>${person.months.map((m,i) => `<td class="${i === 6 ? 'semester-cut' : ''}">${m.predicate ? `<b>${esc(m.predicate.slice(0,12))}</b><br>${pill(m.review_status)}` : '—'}</td>`).join('')}<td>${person.semester_1.approved}/6 disetujui<br>${person.semester_1.low} nilai rendah</td><td>${person.semester_2.approved}/6 disetujui<br>${person.semester_2.low} nilai rendah</td><td>${esc(person.not_submitted_months.join(', ') || '—')}</td></tr>`).join('') || '<tr><td colspan="16">Belum ada data.</td></tr>'}</tbody></table></div>`;
    }
    root.querySelector('#skpAnnualApply').onclick = () => loadAnnual().catch(showError);
    await loadAnnual();
  }

  function bindShell() { if (window.lucide) lucide.createIcons(); }
  async function renderTab(root) {
    if (view.tab === 'import') importPanel(root);
    else if (view.tab === 'configuration') await configurationPanel(root);
    else if (view.tab === 'classification') { listPanel(root, 'classification'); await loadRows(root, false); }
    else if (view.tab === 'review') { listPanel(root, 'review'); await loadRows(root, true); }
    else if (view.tab === 'exceptions') await exceptionPanel(root);
    else await annualPanel(root);
    if (window.lucide) lucide.createIcons();
  }

  EVKIN.skpAssessmentMod = {
    render(root) { shell(root); bindShell(root); renderTab(root).catch(showError); }
  };
})();
