/* Canonical Master SDM: effective-dated identity, Tukin profile, bank data, and audit history. */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util;
  const state = { page: 1, pages: 1, q: '', active: '', workbook: null, file: null, rows: [], previewed: false, previewToken: '' };

  const esc = value => U.esc(String(value == null ? '' : value));
  const money = value => Number(value || 0).toLocaleString('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 });
  const today = () => new Date().toISOString().slice(0, 10);
  const baseUrl = path => new URL(path, EVKIN.exportBackend.apiBase).toString();

  async function ensureBackend() {
    if (!EVKIN.exportBackend) throw new Error('Backend EVKIN belum tersedia.');
    if (!EVKIN.exportBackend.enabled && EVKIN.exportBackend.activate) await EVKIN.exportBackend.activate();
  }

  async function api(path, options) {
    await ensureBackend();
    const response = await fetch(baseUrl(path), { cache: 'no-store', ...(options || {}) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Permintaan Master SDM gagal');
    return data;
  }

  const jsonPost = (path, payload) => api(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
  });

  function shell(root) {
    root.innerHTML = `
      <div class="module-head">
        <div><h2>Master SDM Bersama</h2><p class="muted">Satu sumber identitas untuk absensi, SKP, dan Tukin—dengan histori bertanggal efektif dan snapshot final per bulan.</p></div>
        <div class="actions-row"><button id="smReconcile" class="btn btn-secondary"><i data-lucide="scan-search"></i> Cek Workflow</button><button id="smDeactivateAll" class="btn btn-ghost"><i data-lucide="user-x"></i> Nonaktifkan Semua</button></div>
      </div>
      <div class="alert info"><i data-lucide="shield-check"></i><span>Perubahan tidak menimpa histori pembayaran. Saat final Tukin dibuat, jabatan, besaran Tukin, status kelayakan, dan rekening dibekukan sebagai snapshot periode tersebut. SDM yang keluar cukup dinonaktifkan—bukan dihapus.</span></div>

      <div id="smStats" class="stat-grid"></div>
      <div class="sm-master-grid">
        <section class="card">
          <div class="ta-section-head"><div><h3>Impor & Perbarui Massal</h3><p class="muted">Satu sheet dapat memuat Master SDM dan kolom FLAG TENDIK bulanan. Sistem mencari baris header secara otomatis.</p></div></div>
          <div class="form-row">
            <div><label>File Excel/CSV</label><input id="smFile" type="file" accept=".xlsx,.xls,.csv"></div>
            <div><label>Sheet</label><select id="smSheet" disabled><option>Pilih file</option></select></div>
            <div><label>Tanggal efektif</label><input id="smEffective" type="date" max="${today()}" value="${today()}"></div>
            <div><label>Disetujui oleh</label><input id="smApprover" value="Administrator EVKIN"></div>
          </div>
          <div class="actions-row"><a class="btn btn-secondary" href="assets/templates/Template_Master_SDM.xlsx" download><i data-lucide="download"></i> Download Template</a><button id="smPreview" class="btn btn-secondary" disabled><i data-lucide="list-checks"></i> Preview Perubahan</button><button id="smCommit" class="btn btn-primary" disabled><i data-lucide="database-zap"></i> Konfirmasi & Simpan</button><span id="smImportState" class="muted"></span></div>
          <div id="smPreviewResult"></div>
        </section>

        <section class="card">
          <div class="ta-section-head"><div><h3>Tambah / Ubah Satu SDM</h3><p class="muted">Kolom yang dikosongkan saat mengubah data tidak akan menghapus nilai yang sudah ada.</p></div></div>
          <div class="sm-form-grid">
            <div><label>NIP *</label><input id="smNip"></div><div><label>Nama</label><input id="smNama"></div>
            <div><label>Jabatan formal</label><input id="smJabatan"></div><div><label>Unit kerja</label><input id="smUnit"></div>
            <div><label>KD Anak Satker</label><input id="smSatker"></div><div><label>Jenis SDM</label><input id="smJenis" placeholder="Pendamping/Tendik"></div>
            <div><label>Provinsi</label><input id="smProvinsi"></div><div><label>Kabupaten/Kota</label><input id="smKabupaten"></div>
            <div><label>Kelas jabatan</label><input id="smKelas" type="number" min="1"></div><div><label>Tukin bruto</label><input id="smTukin" type="number" min="0"></div>
            <div><label>Penugasan sementara</label><select id="smTempType"><option value="">Tidak diubah</option><option value="SDM PKH">SDM PKH</option><option value="TENDIK">Tendik</option></select></div><div><label>Berlaku mulai</label><input id="smTempMonth" type="month" value="${today().slice(0, 7)}"></div>
            <div><label>Detail penugasan Tendik</label><input id="smTempDetail" placeholder="Contoh: Walih Asuh"></div>
            <div><label>Bank</label><input id="smBank"></div><div><label>No. rekening</label><input id="smRekening"></div>
            <div><label>Pemilik rekening</label><input id="smPemilik"></div><div><label>Kelayakan Tukin</label><select id="smEligible"><option value="">Tidak diubah</option><option value="YA">Berhak</option><option value="TIDAK">Tidak berhak</option></select></div>
            <div><label>Wilayah</label><select id="sm3T"><option value="">Tidak diubah</option><option value="REGULER">Reguler</option><option value="3T">3T</option></select></div><div><label>Alasan tidak berhak</label><input id="smReason"></div>
          </div>
          <div class="actions-row"><button id="smSaveOne" class="btn btn-primary"><i data-lucide="save"></i> Preview & Simpan</button><button id="smClear" class="btn btn-ghost">Bersihkan</button></div>
        </section>
      </div>

      <section class="card">
        <div class="ta-section-head"><div><h3>Daftar Master Aktif & Historis</h3><p class="muted">Gunakan Detail untuk melihat histori jabatan formal, penugasan sementara, profil Tukin, rekening, dan snapshot pembayaran.</p></div>
          <div class="ta-filter"><input id="smSearch" placeholder="Cari NIP, nama, atau jabatan"><select id="smActive"><option value="">Semua status</option><option value="true">Aktif</option><option value="false">Nonaktif</option></select><button id="smSearchBtn" class="btn btn-secondary">Terapkan</button></div>
        </div>
        <div id="smTable"><div class="muted">Memuat Master SDM…</div></div><div id="smPager" class="ta-pager"></div>
      </section>
      <section id="smIssues" class="card hidden"></section>
      <section id="smDetail" class="card hidden"></section>`;
  }

  function stats(root, data) {
    const rows = data.rows || [];
    const active = rows.filter(row => row.active).length;
    root.querySelector('#smStats').innerHTML = [
      ['Total SDM', data.total || 0, 'users', 'blue'],
      ['Aktif di halaman', active, 'user-check', 'green'],
      ['Perlu validasi', data.open_issues || 0, 'triangle-alert', data.open_issues ? 'red' : 'gray'],
      ['Sumber data', 'DuckDB', 'database', 'gray']
    ].map(item => `<div class="stat-card ${item[3]}"><div class="stat-icon"><i data-lucide="${item[2]}"></i></div><div><div class="stat-val">${esc(item[1])}</div><div class="stat-label">${item[0]}</div></div></div>`).join('');
  }

  async function loadList(root) {
    const params = new URLSearchParams({ page: String(state.page), per_page: '25' });
    if (state.q) params.set('q', state.q);
    if (state.active) params.set('active', state.active);
    const data = await api(`/api/shared-master?${params}`);
    state.pages = data.pages || 1;
    stats(root, data);
    root.querySelector('#smTable').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>SDM</th><th>Jabatan Formal</th><th>Penugasan Saat Ini</th><th>Profil Tukin</th><th>Rekening</th><th>Status</th><th>Aksi</th></tr></thead><tbody>${(data.rows || []).map(row => `
      <tr><td><strong>${esc(row.nama || 'Tanpa nama')}</strong><small>${esc(row.nip)}</small></td><td>${esc(row.jabatan || '—')}<small>${esc(row.unit || row.kabupaten_kota || '')}</small></td><td>${esc(row.temporary_assignment_type || row.status_tendik || '—')}<small>${esc(row.temporary_assignment_detail || row.jabatan_osdm || '')}${row.temporary_assignment_effective_month ? ` · sejak ${esc(row.temporary_assignment_effective_month)}` : ''}</small></td><td>${money(row.tukin_gross)}<small>Kelas ${esc(row.kelas_jabatan || '—')} · ${row.wilayah_3t ? '3T' : 'Reguler'}</small></td><td>${esc(row.bank_name || '—')}<small>${esc(row.account_number || 'Belum ada')}</small></td><td><span class="pill ${row.active ? 'green' : 'gray'}">${row.active ? 'AKTIF' : 'NONAKTIF'}</span><small>Versi ${esc(row.master_version)}</small></td><td><div class="actions-row"><button class="btn btn-sm btn-secondary sm-detail" data-nip="${esc(row.nip)}">Detail</button><button class="btn btn-sm ${row.active ? 'btn-ghost' : 'btn-primary'} sm-active" data-nip="${esc(row.nip)}" data-active="${row.active ? 'false' : 'true'}">${row.active ? 'Nonaktifkan' : 'Aktifkan'}</button></div></td></tr>`).join('') || '<tr><td colspan="7" class="muted">Belum ada Master SDM.</td></tr>'}</tbody></table></div>`;
    root.querySelector('#smPager').innerHTML = `<button class="btn btn-ghost" id="smPrev" ${state.page <= 1 ? 'disabled' : ''}>← Sebelumnya</button><span>Halaman ${state.page} / ${state.pages} · ${data.total || 0} SDM</span><button class="btn btn-ghost" id="smNext" ${state.page >= state.pages ? 'disabled' : ''}>Berikutnya →</button>`;
    root.querySelector('#smPrev').onclick = () => { state.page--; loadList(root).catch(showError); };
    root.querySelector('#smNext').onclick = () => { state.page++; loadList(root).catch(showError); };
    root.querySelectorAll('.sm-detail').forEach(button => button.onclick = () => showDetail(root, button.dataset.nip));
    root.querySelectorAll('.sm-active').forEach(button => button.onclick = () => setActive(root, button.dataset.nip, button.dataset.active === 'true'));
    if (window.lucide) lucide.createIcons();
  }

  function historyTable(title, rows, columns) {
    return `<div class="sm-history"><h4>${title}</h4><div class="table-wrap"><table class="data-table sm"><thead><tr>${columns.map(col => `<th>${col[0]}</th>`).join('')}</tr></thead><tbody>${(rows || []).map(row => `<tr>${columns.map(col => `<td>${esc(row[col[1]])}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${columns.length}" class="muted">Belum ada histori.</td></tr>`}</tbody></table></div></div>`;
  }

  async function showDetail(root, nip) {
    try {
      const data = await api(`/api/shared-master/${encodeURIComponent(nip)}`);
      const p = data.person;
      const box = root.querySelector('#smDetail'); box.classList.remove('hidden');
      box.innerHTML = `<div class="ta-section-head"><div><h3>${esc(p.nama || 'SDM')} <span class="pill ${p.active ? 'green' : 'gray'}">${p.active ? 'AKTIF' : 'NONAKTIF'}</span></h3><p class="muted">NIP ${esc(p.nip)} · Master versi ${esc(p.master_version)} · ${esc(p.jabatan || 'Tanpa jabatan')}</p></div><button id="smCloseDetail" class="btn btn-ghost">Tutup</button></div>
        <div class="sm-detail-summary"><div><span>Tukin saat ini</span><strong>${money(p.tukin_gross)}</strong></div><div><span>Rekening</span><strong>${esc(p.bank_name || '—')} ${esc(p.account_number || '')}</strong></div><div><span>Unit</span><strong>${esc(p.unit || '—')}</strong></div><div><span>Kelayakan</span><strong>${p.eligible === false ? 'Tidak berhak' : 'Berhak'}</strong></div></div>
        ${historyTable('Histori Penempatan', data.assignments, [['Berlaku','valid_from'],['Sampai','valid_to'],['Jabatan','jabatan'],['Unit','unit'],['Dasar','change_reason']])}
        ${historyTable('Histori Penugasan Sementara', data.temporary_assignments, [['Berlaku mulai','effective_month'],['Klasifikasi','assignment_type'],['Detail','assignment_detail'],['Nilai sumber','raw_value'],['Sumber','source_file'],['Penyetuju','approved_by']])}
        ${historyTable('Histori Profil Tukin', data.profiles, [['Berlaku','valid_from'],['Sampai','valid_to'],['Kelas','kelas_jabatan'],['Tukin','tukin_gross'],['3T','wilayah_3t'],['Dasar','change_reason']])}
        ${historyTable('Histori Rekening', data.banks, [['Berlaku','valid_from'],['Sampai','valid_to'],['Bank','bank_name'],['Rekening','account_number'],['Pemilik','account_holder']])}
        ${historyTable('Snapshot Final Tukin', data.snapshots, [['Penilaian','assessment_period'],['Penugasan','temporary_assignment_type'],['Detail','temporary_assignment_detail'],['Tukin bruto','tukin_gross'],['Dibayar','paid_amount'],['Status','payment_status'],['Versi master','master_version']])}
        ${historyTable('Audit Perubahan', data.changes, [['Waktu','created_at'],['Field','field_name'],['Lama','old_value'],['Baru','new_value'],['Efektif','effective_date'],['Penyetuju','reviewed_by']])}`;
      box.querySelector('#smCloseDetail').onclick = () => box.classList.add('hidden');
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) { showError(error); }
  }

  async function setActive(root, nip, active) {
    const action = active ? 'mengaktifkan kembali' : 'menonaktifkan';
    if (!confirm(`Yakin ${action} NIP ${nip}? Histori pembayaran tetap disimpan.`)) return;
    const reason = prompt(`Alasan ${action} NIP ${nip}:`);
    if (!reason || !reason.trim()) return EVKIN.toast('Alasan perubahan status wajib diisi.', 'error');
    const approvedBy = root.querySelector('#smApprover').value.trim();
    if (!approvedBy) return EVKIN.toast('Identitas penyetuju wajib diisi.', 'error');
    try {
      await jsonPost(`/api/shared-master/${encodeURIComponent(nip)}/active`, { active, reason: reason.trim(), approved_by: approvedBy, effective_date: root.querySelector('#smEffective').value });
      EVKIN.toast(`NIP ${nip} berhasil ${active ? 'diaktifkan' : 'dinonaktifkan'}.`, 'success');
      await Promise.all([loadList(root), EVKIN.refreshMasterPegawaiFromBackend ? EVKIN.refreshMasterPegawaiFromBackend() : Promise.resolve()]);
    } catch (error) { showError(error); }
  }

  function workbookRows() {
    if (!state.workbook) return [];
    const sheetName = document.querySelector('#smSheet').value;
    const worksheet = state.workbook.Sheets[sheetName];
    const matrix = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '', raw: false });
    const clean = value => String(value == null ? '' : value).toLowerCase().replace(/[^a-z0-9]/g, '');
    const headerRow = matrix.findIndex(row => (row || []).some(value => ['nip', 'nomorindukpegawai'].includes(clean(value))));
    if (headerRow < 0) throw new Error('Baris header tidak ditemukan. Pastikan terdapat kolom NIP.');
    return XLSX.utils.sheet_to_json(worksheet, { defval: '', raw: false, range: headerRow });
  }

  function renderPreview(root, result) {
    const assignmentErrors = (result.assignment_rejections || []).concat((result.assignment_invalid_headers || []).map(header => ({ period: 'HEADER', reason: `Header tidak valid/duplikat: ${header}` })));
    root.querySelector('#smPreviewResult').innerHTML = `<div class="sm-preview-summary"><span class="pill blue">${result.new_count} SDM baru</span><span class="pill yellow">${result.changed_count} Master berubah</span><span class="pill gray">${result.unchanged_count} Master tetap</span><span class="pill ${result.rejected_count ? 'red' : 'green'}">${result.rejected_count} Master ditolak</span></div>
      <div class="sm-preview-summary"><span class="pill blue">${result.assignment_new_count || 0} penugasan awal</span><span class="pill yellow">${result.assignment_changed_count || 0} perubahan penugasan</span><span class="pill gray">${result.assignment_continued_count || 0} diteruskan</span><span class="pill ${assignmentErrors.length ? 'red' : 'green'}">${assignmentErrors.length} masalah penugasan</span></div>
      <h4>Preview Master SDM</h4><div class="table-wrap sm-preview-table"><table class="data-table sm"><thead><tr><th>Baris</th><th>NIP</th><th>Nama</th><th>Status</th><th>Field berubah</th></tr></thead><tbody>${(result.preview || []).slice(0, 100).map(row => `<tr><td>${row.row}</td><td>${esc(row.nip)}</td><td>${esc(row.nama)}</td><td>${esc(row.status)}</td><td>${esc((row.changed_fields || []).join(', '))}</td></tr>`).join('')}</tbody></table></div>
      <h4>Preview Penugasan Sementara</h4><div class="table-wrap sm-preview-table"><table class="data-table sm"><thead><tr><th>Baris</th><th>NIP</th><th>Periode</th><th>Nilai sumber</th><th>Sebelumnya</th><th>Menjadi</th><th>Status</th></tr></thead><tbody>${(result.assignment_preview || []).slice(0, 150).map(row => `<tr><td>${row.row}</td><td>${esc(row.nip)}</td><td>${esc(row.period)}</td><td>${esc(row.source_value)}</td><td>${esc(row.previous_type || '—')}</td><td>${esc(row.assignment_type)}${row.assignment_detail ? ` · ${esc(row.assignment_detail)}` : ''}</td><td>${esc(row.status)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">Tidak ada kolom FLAG TENDIK atau tidak ada perubahan eksplisit.</td></tr>'}</tbody></table></div>
      ${assignmentErrors.length ? `<div class="alert danger"><span><strong>Impor belum dapat disimpan.</strong><br>${assignmentErrors.slice(0, 20).map(item => `${esc(item.nip || '')} ${esc(item.period || '')}: ${esc(item.reason)}`).join('<br>')}</span></div>` : ''}`;
  }

  async function previewImport(root) {
    try {
      state.rows = workbookRows(); state.previewed = false; state.previewToken = '';
      if (!state.rows.length) throw new Error('Sheet tidak berisi data.');
      const result = await jsonPost('/api/shared-master/preview', { rows: state.rows, effective_date: root.querySelector('#smEffective').value });
      renderPreview(root, result);
      const hasErrors = result.rejected_count || result.assignment_rejected_count || result.assignment_invalid_header_count;
      state.previewed = !hasErrors; state.previewToken = hasErrors ? '' : result.preview_token; root.querySelector('#smCommit').disabled = !!hasErrors;
      root.querySelector('#smImportState').textContent = `${result.valid_count} baris valid siap dikonfirmasi.`;
    } catch (error) { showError(error); }
  }

  async function commitImport(root) {
    if (!state.previewed) return;
    if (!confirm(`Simpan ${state.rows.length} baris dengan tanggal efektif ${root.querySelector('#smEffective').value}?`)) return;
    try {
      const approvedBy = root.querySelector('#smApprover').value.trim();
      if (!approvedBy) throw new Error('Identitas penyetuju wajib diisi.');
      const result = await jsonPost('/api/shared-master/commit', { rows: state.rows, effective_date: root.querySelector('#smEffective').value, source_file: state.file.name, approved_by: approvedBy, confirmed: true, preview_token: state.previewToken });
      EVKIN.toast(`${result.committed} baris Master SDM dan ${result.assignment_committed || 0} perubahan penugasan tersimpan.`, 'success');
      state.previewed = false; state.previewToken = ''; root.querySelector('#smCommit').disabled = true;
      await Promise.all([loadList(root), EVKIN.refreshMasterPegawaiFromBackend ? EVKIN.refreshMasterPegawaiFromBackend() : Promise.resolve()]);
    } catch (error) { showError(error); }
  }

  function manualRow(root) {
    const row = {
      nip: root.querySelector('#smNip').value.trim(), nama: root.querySelector('#smNama').value.trim(),
      jabatan: root.querySelector('#smJabatan').value.trim(), unit: root.querySelector('#smUnit').value.trim(),
      kdAnakSatker: root.querySelector('#smSatker').value.trim(), jenisSdm: root.querySelector('#smJenis').value.trim(),
      provinsi: root.querySelector('#smProvinsi').value.trim(), kabupatenKota: root.querySelector('#smKabupaten').value.trim(),
      kelasJabatan: root.querySelector('#smKelas').value, tukin: root.querySelector('#smTukin').value,
      bank: root.querySelector('#smBank').value.trim(), noRekening: root.querySelector('#smRekening').value.trim(),
      namaPemilikRekening: root.querySelector('#smPemilik').value.trim(), berhakTukin: root.querySelector('#smEligible').value,
      wilayah3T: root.querySelector('#sm3T').value, alasanTidakBerhak: root.querySelector('#smReason').value.trim()
    };
    const tempType = root.querySelector('#smTempType').value;
    const tempMonth = root.querySelector('#smTempMonth').value;
    if (tempType && tempMonth) {
      const [year, month] = tempMonth.split('-').map(Number);
      const monthNames = ['JANUARI','FEBRUARI','MARET','APRIL','MEI','JUNI','JULI','AGUSTUS','SEPTEMBER','OKTOBER','NOVEMBER','DESEMBER'];
      const detail = root.querySelector('#smTempDetail').value.trim();
      row[`FLAG TENDIK ${monthNames[month - 1]} ${year}`] = tempType === 'SDM PKH' ? '-' : (detail || 'TENDIK');
    }
    // Empty fields mean "leave the current value unchanged". Reguler and
    // eligibility are explicit non-empty options when they must be changed.
    return Object.fromEntries(Object.entries(row).filter(([key, value]) =>
      value !== '' || key === 'nip'
    ));
  }

  function clearManual(root) { root.querySelectorAll('.sm-form-grid input:not([type="month"])').forEach(input => { input.value = ''; }); root.querySelector('#smEligible').value = ''; root.querySelector('#sm3T').value = ''; root.querySelector('#smTempType').value = ''; }

  async function saveOne(root) {
    const row = manualRow(root); if (!row.nip) return EVKIN.toast('NIP wajib diisi.', 'error');
    try {
      const preview = await jsonPost('/api/shared-master/preview', { rows: [row], effective_date: root.querySelector('#smEffective').value });
      const item = preview.preview[0];
      if (!confirm(`${item.status}: ${row.nip} ${row.nama}. Field berubah: ${(item.changed_fields || []).join(', ') || 'tidak ada'}. Simpan?`)) return;
      const approvedBy = root.querySelector('#smApprover').value.trim();
      if (!approvedBy) throw new Error('Identitas penyetuju wajib diisi.');
      await jsonPost('/api/shared-master/commit', { rows: [row], effective_date: root.querySelector('#smEffective').value, source_file: 'INPUT_MANUAL', approved_by: approvedBy, confirmed: true, preview_token: preview.preview_token });
      EVKIN.toast(`Master SDM ${row.nip} tersimpan.`, 'success'); clearManual(root);
      await Promise.all([loadList(root), EVKIN.refreshMasterPegawaiFromBackend ? EVKIN.refreshMasterPegawaiFromBackend() : Promise.resolve()]);
    } catch (error) { showError(error); }
  }

  async function reconcile(root) {
    try {
      const result = await jsonPost('/api/shared-master/reconcile', {});
      const issues = await api('/api/shared-master/validation?status=OPEN&per_page=100');
      const box = root.querySelector('#smIssues'); box.classList.remove('hidden');
      box.innerHTML = `<div class="ta-section-head"><div><h3>Hasil Validasi Workflow</h3><p class="muted">${result.observations} identitas diperiksa; ${issues.total} masalah terbuka.</p></div><button id="smCloseIssues" class="btn btn-ghost">Tutup</button></div><div class="table-wrap"><table class="data-table sm"><thead><tr><th>Severity</th><th>NIP</th><th>Sumber</th><th>Masalah</th><th>Nilai sumber</th><th>Nilai master</th></tr></thead><tbody>${(issues.rows || []).map(row => `<tr><td><span class="pill ${row.severity === 'ERROR' ? 'red' : 'yellow'}">${esc(row.severity)}</span></td><td>${esc(row.nip)}</td><td>${esc(row.source_table)}</td><td>${esc(row.details)}</td><td>${esc(row.source_value)}</td><td>${esc(row.master_value)}</td></tr>`).join('') || '<tr><td colspan="6">Tidak ada masalah.</td></tr>'}</tbody></table></div>`;
      box.querySelector('#smCloseIssues').onclick = () => box.classList.add('hidden');
      await loadList(root);
    } catch (error) { showError(error); }
  }

  function invalidatePreview(root) {
    state.previewed = false; state.previewToken = '';
    root.querySelector('#smCommit').disabled = true;
    root.querySelector('#smImportState').textContent = state.file ? 'Data berubah; lakukan preview ulang.' : '';
  }

  async function deactivateAll(root) {
    const approvedBy = root.querySelector('#smApprover').value.trim();
    if (!approvedBy) return EVKIN.toast('Identitas penyetuju wajib diisi.', 'error');
    const reason = prompt('Alasan menonaktifkan seluruh SDM aktif:');
    if (!reason || !reason.trim()) return;
    const confirmation = prompt('Ketik persis: NONAKTIFKAN SEMUA SDM');
    if (confirmation !== 'NONAKTIFKAN SEMUA SDM') return EVKIN.toast('Konfirmasi tidak sesuai.', 'error');
    try {
      const result = await jsonPost('/api/shared-master/admin/deactivate-all', {
        confirmation, reason: reason.trim(), approved_by: approvedBy, effective_date: root.querySelector('#smEffective').value
      });
      EVKIN.toast(`${result.deactivated} SDM dinonaktifkan. Histori tetap dapat dipulihkan.`, 'success');
      await Promise.all([loadList(root), EVKIN.refreshMasterPegawaiFromBackend ? EVKIN.refreshMasterPegawaiFromBackend() : Promise.resolve()]);
    } catch (error) { showError(error); }
  }

  function bind(root) {
    const file = root.querySelector('#smFile'); const sheet = root.querySelector('#smSheet');
    file.onchange = async () => {
      state.file = file.files && file.files[0]; invalidatePreview(root);
      if (!state.file) return;
      try {
        state.workbook = XLSX.read(await state.file.arrayBuffer(), { type: 'array', cellDates: false });
        sheet.innerHTML = state.workbook.SheetNames.map(name => `<option>${esc(name)}</option>`).join(''); sheet.disabled = false;
        root.querySelector('#smPreview').disabled = false; root.querySelector('#smImportState').textContent = `${state.workbook.SheetNames.length} sheet ditemukan.`;
      } catch (error) { showError(error); }
    };
    sheet.onchange = () => { invalidatePreview(root); root.querySelector('#smPreviewResult').innerHTML = ''; };
    root.querySelector('#smEffective').onchange = () => invalidatePreview(root);
    root.querySelector('#smApprover').oninput = () => invalidatePreview(root);
    root.querySelector('#smPreview').onclick = () => previewImport(root);
    root.querySelector('#smCommit').onclick = () => commitImport(root);
    root.querySelector('#smSaveOne').onclick = () => saveOne(root);
    root.querySelector('#smClear').onclick = () => clearManual(root);
    root.querySelector('#smSearchBtn').onclick = () => { state.q = root.querySelector('#smSearch').value.trim(); state.active = root.querySelector('#smActive').value; state.page = 1; loadList(root).catch(showError); };
    root.querySelector('#smSearch').onkeydown = event => { if (event.key === 'Enter') root.querySelector('#smSearchBtn').click(); };
    root.querySelector('#smReconcile').onclick = () => reconcile(root);
    root.querySelector('#smDeactivateAll').onclick = () => deactivateAll(root);
  }

  function showError(error) { console.error(error); EVKIN.toast(error.message || String(error), 'error'); }

  EVKIN.masterSdmMod = {
    render(root) {
      shell(root); bind(root); loadList(root).catch(showError);
      if (window.lucide) lucide.createIcons();
    }
  };
})();
