/* EVKIN Tukin Annual Management
   Histori bulanan, SKP, kondisi khusus, matriks semester, dan eviden harian. */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util;
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  const view = { year: 2026, page: 1, pages: 1, q: '', workbook: null, file: null, request: 0 };

  function esc(value) { return U.esc(String(value == null ? '' : value)); }
  function money(value) {
    if (value === null || value === undefined || value === '') return 'Belum tersedia';
    return Number(value || 0).toLocaleString('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 });
  }
  function num(value) { return Number(value || 0).toLocaleString('id-ID', { maximumFractionDigits: 0 }); }
  function baseUrl(path) { return new URL(path, EVKIN.exportBackend.apiBase).toString(); }
  async function api(path, options) {
    const response = await fetch(baseUrl(path), { cache: 'no-store', ...(options || {}) });
    const type = response.headers.get('content-type') || '';
    const data = type.includes('json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error((data && data.detail) || data || 'Permintaan gagal');
    return data;
  }
  function nextMonth(period) {
    if (!/^\d{4}-\d{2}$/.test(period || '')) return '';
    const parts = period.split('-').map(Number);
    return parts[1] === 12 ? `${parts[0] + 1}-01` : `${parts[0]}-${String(parts[1] + 1).padStart(2, '0')}`;
  }
  function statusPill(status) {
    const value = String(status || 'BELUM ADA').toUpperCase();
    const color = value.includes('PAID') && !value.includes('UNPAID') ? 'green'
      : value.includes('UNPAID') || value.includes('TIDAK') ? 'red'
        : value.includes('REVIEW') ? 'yellow' : value.includes('LOCK') ? 'blue' : 'gray';
    return `<span class="pill ${color}">${esc(value.replaceAll('_', ' '))}</span>`;
  }
  function predicateLabel(month) {
    if (!month || !month.period) return '<span class="ta-empty">–</span>';
    const pred = month.predicate || month.report_status || 'Data tersedia';
    const bad = /kurang|missing|tidak/i.test(pred);
    return `<button class="ta-month-cell ${bad ? 'risk' : ''}" type="button" title="${esc(pred)} · dibayar ${money(month.paid)}">
      <strong>${esc(String(pred).replace('NOT_SUBMITTED_VERIFIED', 'Tidak SKP').slice(0, 14))}</strong>
      <span>${num(month.paid)}</span>
    </button>`;
  }

  function shell(el) {
    const active = view.requestedPeriod || EVKIN.state.month || '2026-08';
    view.year = Number(String(active).slice(0, 4)) || 2026;
    el.innerHTML = `
      <div class="module-head">
        <div><h2>Pengelolaan Tukin Tahunan</h2><p class="muted">Basis data final per SDM: nilai SKP 70%, absensi 30%, pembayaran, kondisi khusus, dan eviden harian.</p></div>
        <div class="actions-row"><button id="taDownloadAnnual" class="btn btn-success"><i data-lucide="file-spreadsheet"></i> Download Rekap 1 Tahun</button><button id="taResetModule" class="btn btn-danger"><i data-lucide="trash-2"></i> Hapus Data Pengelolaan Tukin</button></div>
      </div>

      <div class="alert info"><i data-lucide="info"></i><span><strong>Periode penilaian berbeda dari pembayaran.</strong> Contoh: SKP/absensi Agustus 2026 dicatat sebagai <b>2026-08</b> dan dibayarkan pada <b>2026-09</b>. Histori lama diimpor sekali; bulan berjalan dapat ditangkap langsung dari workflow.</span></div>

      <section class="card ta-overview-card">
       <div class="ta-section-head"><div><h3>Ringkasan Pengelolaan Tukin</h3><p class="muted">Ikhtisar data dan status proses untuk tahun yang sedang dipilih.</p></div><span id="taOverviewYear" class="pill blue">${view.year}</span></div>
       <div id="taDashboard"><div class="muted">Memuat ringkasan…</div></div>
       <div id="taWorkflow" class="ta-workflow"><div class="muted">Memuat alur status…</div></div>
      </section>

      <section class="card ta-basis">
        <h3>Dasar Tukin — SKP 70% dan Absensi 30%</h3>
        <p class="muted">Peserta Final Absensi dipasangkan dengan Master SDM dan SKP disetujui berdasarkan NIP dan periode. Data belum lengkap tetap terlihat, dengan nominal final kosong. Hasil ini merupakan dasar review pembayaran.</p>
        <div class="form-row"><div><label for="taCombinedPeriod">Periode penilaian</label><input id="taCombinedPeriod" type="month" value="${esc(active)}"></div><div><label for="taCombinedScope">Cakupan peserta</label><select id="taCombinedScope"><option value="workflow">Final Absensi workflow aktif</option><option value="attendance">Final Absensi termasuk histori bulan ini</option><option value="all">Seluruh Master SDM dan sumber</option></select></div><div><label for="taCombinedSearch">Cari NIP/nama</label><input type="text" id="taCombinedSearch"></div></div>
        <div class="actions-row"><button id="taCombinedLoad" class="btn btn-primary">Hitung Gabungan</button><button id="taCombinedExport" class="btn btn-success" disabled>Excel Dasar Tukin</button><button id="taCombinedSkp" class="btn btn-secondary">Impor / Review SKP</button></div>
        <div id="taCombinedResult" role="status">Klik Hitung Gabungan untuk memuat data periode.</div>
        <div id="taCombinedAdjustment" class="hidden"></div>
      </section>

      <div class="ta-control-grid">
        <section class="card ta-import-card">
          <h3>Impor Histori Tukin dan Absensi</h3>
          <div class="form-row">
            <div><label>Jenis data</label><select id="taSource"><option value="FINAL">Final Tukin</option><option value="ATTENDANCE_DAILY">Eviden Absensi Harian</option></select></div>
            <div><label>Periode penilaian</label><input id="taAssessment" type="month" value="${esc(active)}"></div>
            <div><label>Periode pembayaran</label><input id="taPayment" type="month" value="${esc(nextMonth(active))}"></div>
          </div>
          <div class="form-row">
            <div><label>File Excel sumber</label><input id="taFile" type="file" accept=".xlsx,.xls,.csv"></div>
            <div class="sheet-source-control"><label>Sheet sumber yang dibaca</label><select id="taSheet" disabled><option value="">Pilih file Excel terlebih dahulu</option></select><small>Hanya satu sheet terpilih yang akan disimpan.</small></div>
          </div>
          <div id="taSheetMeta" class="sheet-source-meta empty"><i data-lucide="table-2"></i><span><b>Belum ada sheet dipilih</b><small>Pilih file, kemudian periksa sheet aktif sebelum menyimpan.</small></span></div>
          <div class="actions-row"><a id="taTemplate" class="btn btn-secondary" href="assets/templates/Template_Final_Tukin_Historis.xlsx" download><i data-lucide="download"></i> Download Template</a><button id="taImport" class="btn btn-primary" disabled><i data-lucide="database-zap"></i> Simpan Sheet Terpilih</button><span id="taImportState" class="muted">Nilai SKP dikelola melalui menu Penilaian SKP.</span></div>
        </section>

        <section class="card ta-live-card">
          <h3>Bulan Berjalan</h3>
          <p class="muted">Sinkronkan final absensi dan eviden harian dari workflow aktif. Penilaian SKP yang sudah APPROVED tetap dipertahankan dan tidak ditimpa oleh sinkronisasi ulang.</p>
          <div class="form-row"><div><label>Penilaian</label><input id="taLiveAssessment" type="month" value="${esc(active)}"></div><div><label>Pembayaran</label><input id="taLivePayment" type="month" value="${esc(nextMonth(active))}"></div></div>
          <div class="actions-row"><button id="taCapture" class="btn btn-success"><i data-lucide="combine"></i> Sinkronkan Final Absensi</button><button id="taDownloadFinal" class="btn btn-secondary"><i data-lucide="download"></i> Download Final Bulan</button></div>
        </section>
      </div>

      <section class="card">
        <div class="ta-section-head"><div><h3>Kondisi Tersinkron dari Penilaian SKP</h3><p class="muted">Bagian ini hanya menampilkan hasil keputusan. Hukdis dan kondisi keputusan dicatat pada menu <b>Penilaian SKP → Kondisi & Pengecualian</b>; wilayah 3T tetap berasal dari Master SDM.</p></div></div>
        <div class="alert info"><i data-lucide="lock-keyhole"></i><span>Keputusan tidak dapat diedit dari Pengelolaan Tukin agar tidak terjadi input ganda. Efek HOLD/tidak dibayarkan diterapkan otomatis saat data final periode tersedia.</span></div>
        <div id="taSyncedConditions"><div class="muted">Memuat kondisi tersinkron…</div></div>
      </section>

      <section class="card">
        <div class="ta-section-head"><div><h3>Kelengkapan Periode</h3><p class="muted">Pastikan Final, SKP, dan eviden harian tersedia sebelum periode dikunci.</p></div><select id="taPeriodYear"><option>${view.year}</option></select></div>
        <div class="form-row ta-approval-fields"><div><label for="taApprovalActor">Petugas approval</label><input id="taApprovalActor" maxlength="150" placeholder="Nama petugas"></div><div><label for="taApprovalReason">Alasan/status</label><input id="taApprovalReason" maxlength="500" placeholder="Catatan perubahan status"></div></div>
        <div id="taPeriods"><div class="muted">Memuat periode…</div></div>
      </section>
      <section class="card">
        <div class="ta-section-head"><div><h3>Hasil Hitungan</h3><p class="muted">Hasil Final Workflow yang tersimpan permanen di database. Penghapusan hanya menyentuh tabel hasil final; Master SDM dan source data tetap aman.</p></div></div>
        <div id="taFinalResults"><div class="muted">Memuat hasil hitungan…</div></div>
      </section>

      <section class="card">
        <div class="ta-section-head"><div><h3>Matriks Tukin per SDM · Semester I & II</h3><p class="muted">Setiap sel menampilkan predikat/status SKP dan nominal yang dibayarkan. Klik SDM untuk membuka rincian.</p></div>
          <div class="ta-filter"><input id="taSearch" type="text" placeholder="Cari NIP atau nama"><select id="taYear">${[2025, 2026, 2027].map(y => `<option ${y === view.year ? 'selected' : ''}>${y}</option>`).join('')}</select><button id="taSearchBtn" class="btn btn-secondary">Terapkan</button></div>
        </div>
        <div id="taMatrix"><div class="muted">Memuat rekap tahunan…</div></div>
        <div id="taPager" class="ta-pager"></div>
      </section>
      <section id="taDetail" class="card hidden"></section>`;
  }

  async function loadPeriods(root) {
    const data = await api(`/api/tukin/periods?year=${view.year}`);
    const rows = data.periods || [];
    view.periodRows = rows;
    const overviewYear = root.querySelector('#taOverviewYear');
    if (overviewYear) overviewYear.textContent = view.year;
    root.querySelector('#taPeriods').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>Penilaian</th><th>Dibayar</th><th>Semester</th><th>Final</th><th>SKP</th><th>SDM dengan Eviden</th><th>Sumber</th><th>Status</th><th>Ubah Status</th><th>Aksi</th></tr></thead><tbody>${rows.map(row => `<tr><td><b>${esc(row.assessment_period)}</b></td><td>${esc(row.payment_period)}</td><td>${row.semester}</td><td>${num(row.final_count)}</td><td>${num(row.skp_count)}</td><td>${num(row.daily_people_count)}</td><td>${esc(row.source_mode)}</td><td>${statusPill(row.status)}<br><small>${esc(statusLabel(row.status))}</small></td><td><div class="ta-status-control"><select data-status-for="${esc(row.assessment_period)}">${['DRAFT','REVIEW','APPROVED','LOCKED','PAID','HISTORICAL_LOCKED'].map(status => `<option value="${status}" ${status === row.status ? 'selected' : ''}>${statusLabel(status)}</option>`).join('')}</select><button class="btn btn-sm btn-primary ta-status-save" data-period="${esc(row.assessment_period)}">Simpan</button></div></td><td><button class="btn btn-sm btn-secondary ta-period-audit" data-period="${esc(row.assessment_period)}">Audit</button> <button class="btn btn-sm btn-secondary ta-final-download" data-period="${esc(row.assessment_period)}">Excel</button></td></tr>`).join('') || '<tr><td colspan="10">Belum ada periode tersimpan.</td></tr>'}</tbody></table></div>`;
    root.querySelectorAll('.ta-final-download').forEach(button => button.onclick = () => download(`/api/tukin/export/final?assessment_period=${encodeURIComponent(button.dataset.period)}`, `FINAL_TUKIN_${button.dataset.period}.xlsx`));
    root.querySelectorAll('.ta-status-save').forEach(button => button.onclick = async () => {
      try {
        const select = root.querySelector(`[data-status-for="${button.dataset.period}"]`);
        await api('/api/tukin/periods/status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assessment_period: button.dataset.period, status: select.value, actor: root.querySelector('#taApprovalActor').value, reason: root.querySelector('#taApprovalReason').value }) });
        EVKIN.toast(`Status ${button.dataset.period} diperbarui.`, 'success'); await refresh(root);
      } catch (error) { showError(error); }
    });
    root.querySelectorAll('.ta-period-audit').forEach(button => button.onclick = () => showPeriodAudit(root, button.dataset.period));
  }

  const STATUS_LABELS = {
    DRAFT: 'Draft',
    REVIEW: 'Review',
    APPROVED: 'Disetujui',
    LOCKED: 'Dikunci',
    PAID: 'Dibayar',
    HISTORICAL_LOCKED: 'Arsip Terkunci',
  };
  function statusLabel(status) { return STATUS_LABELS[String(status || '').toUpperCase()] || String(status || 'Belum ada').replaceAll('_', ' '); }

  async function showPeriodAudit(root, period) {
    const panel = root.querySelector('#taCombinedAdjustment');
    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="muted">Memuat audit status periode…</div>';
    try {
      const data = await api(`/api/tukin/periods/${encodeURIComponent(period)}/audit`);
      panel.innerHTML = `<h4>Audit status periode · ${esc(period)}</h4>${(data.rows || []).length ? `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>Waktu</th><th>Dari</th><th>Ke</th><th>Petugas</th><th>Alasan</th></tr></thead><tbody>${data.rows.map(row => `<tr><td>${esc(row.created_at)}</td><td>${esc(statusLabel(row.old_status))}</td><td>${esc(statusLabel(row.new_status))}</td><td>${esc(row.actor)}</td><td>${esc(row.reason)}</td></tr>`).join('')}</tbody></table></div>` : '<p>Belum ada riwayat status.</p>'}`;
    } catch (error) { panel.textContent = error.message; }
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function loadConditions(root) {
    const data = await api(`/api/tukin/conditions?year=${view.year}`);
    const rows = data.rows || [];
    root.querySelector('#taSyncedConditions').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>Periode</th><th>SDM</th><th>Kondisi</th><th>Efek</th><th>Alasan</th><th>Dokumen/Eviden</th><th>Sumber</th></tr></thead><tbody>${rows.map(row => `<tr><td>${esc(row.assessment_period)}</td><td><b>${esc(row.nama || '-')}</b><br><span class="muted">${esc(row.nip)}</span></td><td>${esc(row.condition_code)}</td><td>${statusPill(row.effect_type)}</td><td>${esc(row.reason || '-')}</td><td>${esc(row.evidence_ref || '-')}<br><span class="muted">${esc(row.approved_by || '-')} · ${esc(row.approved_at || '-')}</span></td><td>${esc(row.condition_source)}</td></tr>`).join('') || '<tr><td colspan="7">Belum ada keputusan kondisi yang tersinkron.</td></tr>'}</tbody></table></div>`;
  }

  async function loadFinalResults(root) {
    const data = await api(`/api/tukin/final-results/runs?year=${view.year}`);
    const rows = data.runs || [];
    root.querySelector('#taFinalResults').innerHTML = `<div class="table-wrap"><table class="data-table sm"><thead><tr><th>Run ID</th><th>Periode</th><th>SDM</th><th>Tukin Bruto</th><th>Pot. Absensi</th><th>Pot. SKP</th><th>Total Potongan</th><th>Final Tukin</th><th>Aksi</th></tr></thead><tbody>${rows.map(row => `<tr><td><strong>${esc(row.run_id)}</strong></td><td>${esc(row.assessment_period)}</td><td>${num(row.jumlah_sdm)}</td><td>${money(row.total_tukin_bruto)}</td><td>${money(row.total_potongan_absen)}</td><td>${money(row.total_potongan_skp)}</td><td>${money(row.total_potongan)}</td><td>${money(row.total_final_tukin)}</td><td><button class="btn btn-sm btn-danger ta-delete-final-run" data-period="${esc(row.assessment_period)}">Hapus Run</button></td></tr>`).join('') || '<tr><td colspan="9">Belum ada hasil final tersimpan.</td></tr>'}</tbody></table></div>`;
    root.querySelectorAll('.ta-delete-final-run').forEach(button => button.onclick = async () => {
      const period = button.dataset.period;
      const actor = prompt('Nama petugas yang menghapus:');
      if (!actor) return;
      const reason = prompt('Alasan penghapusan:');
      if (!reason) return;
      if (prompt(`Ketik HAPUS FINAL ${period} untuk konfirmasi:`) !== `HAPUS FINAL ${period}`) return;
      try {
        const result = await api(`/api/tukin/final-results/runs/${encodeURIComponent(period)}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actor, reason, confirmation: `HAPUS FINAL ${period}` }) });
        EVKIN.toast(`${num(result.deleted)} hasil final berhasil dihapus.`, 'success');
        await refresh(root);
      } catch (error) { showError(error); }
    });
  }

  function kpi(root, data) {
    const a = data.aggregate || {};
    const periods = view.periodRows || [];
    const reviewPeriods = periods.filter(row => ['DRAFT', 'REVIEW'].includes(String(row.status || '').toUpperCase())).length;
    const missingSkp = periods.filter(row => Number(row.skp_count || 0) === 0).length;
    const missingFinal = periods.filter(row => Number(row.final_count || 0) === 0).length;
    const cards = [
      ['Total SDM', num(a.people), 'users', 'blue'],
      ['Periode perlu review', num(reviewPeriods), 'clipboard-check', reviewPeriods ? 'yellow' : 'green'],
      ['Periode tanpa SKP', num(missingSkp), 'target', missingSkp ? 'red' : 'green'],
      ['Periode tanpa Final', num(missingFinal), 'file-warning', missingFinal ? 'red' : 'green'],
      ['Tukin Bruto', money(a.gross), 'wallet-cards', 'gray'],
      ['Total Potongan', money(Number(a.skp_deduction || 0) + Number(a.attendance_deduction || 0)), 'scaling', 'yellow'],
      ['Dibayarkan', money(a.paid), 'badge-check', 'green'],
      ['Bulan Tidak Dibayar', num(a.unpaid_months), 'circle-off', a.unpaid_months ? 'red' : 'green']
    ];
    root.querySelector('#taDashboard').innerHTML = `<div class="stat-grid">${cards.map(item => `<div class="stat-card ${item[3]}"><div class="stat-icon"><i data-lucide="${item[2]}"></i></div><div><div class="stat-val ${String(item[1]).length > 18 ? 'small' : ''}">${esc(item[1])}</div><div class="stat-label">${item[0]}</div></div></div>`).join('')}</div>`;
    const workflow = ['DRAFT', 'REVIEW', 'APPROVED', 'LOCKED', 'PAID'];
    root.querySelector('#taWorkflow').innerHTML = `<div class="ta-workflow-title">Alur status periode</div><div class="ta-workflow-steps">${workflow.map((status, index) => {
      const count = periods.filter(row => String(row.status || '').toUpperCase() === status).length;
      return `<div class="ta-workflow-step ${count ? 'has-data' : ''}"><span class="ta-workflow-index">${index + 1}</span><div><strong>${statusLabel(status)}</strong><small>${num(count)} periode</small></div>${index < workflow.length - 1 ? '<span class="ta-workflow-arrow">→</span>' : ''}</div>`;
    }).join('')}</div><small class="muted">Gunakan perubahan status secara berurutan setelah data periode selesai divalidasi.</small>`;
    if (window.lucide) lucide.createIcons();
  }

  async function loadAnnual(root) {
    const request = ++view.request;
    root.querySelector('#taMatrix').innerHTML = '<div class="muted">Memuat rekap tahunan…</div>';
    const params = new URLSearchParams({ year: view.year, page: view.page, per_page: 40, q: view.q });
    const data = await api('/api/tukin/annual?' + params.toString());
    if (request !== view.request) return;
    view.pages = data.pages || 1; kpi(root, data);
    const rows = data.rows || [];
    root.querySelector('#taMatrix').innerHTML = `<div class="table-wrap ta-matrix-wrap"><table class="data-table sm ta-matrix"><thead><tr><th>NIP / Nama</th>${MONTHS.map((m, i) => `<th class="${i === 6 ? 'semester-cut' : ''}">${m}</th>`).join('')}<th>Sem I</th><th>Sem II</th><th>Total Dibayar</th></tr></thead><tbody>${rows.map(person => `<tr><td><button class="ta-person" data-nip="${esc(person.nip)}"><b>${esc(person.nama || '-')}</b><span>${esc(person.nip)}</span></button></td>${person.months.map((month, i) => `<td class="${i === 6 ? 'semester-cut' : ''}">${predicateLabel(month)}</td>`).join('')}<td>${money(person.semester_1.paid)}</td><td>${money(person.semester_2.paid)}</td><td><b>${money(person.summary.paid)}</b></td></tr>`).join('') || '<tr><td colspan="16">Belum ada data untuk tahun/filter ini.</td></tr>'}</tbody></table></div>`;
    root.querySelectorAll('.ta-person').forEach(button => button.onclick = () => showDetail(root, button.dataset.nip));
    root.querySelector('#taPager').innerHTML = `<span>Halaman ${view.page} dari ${view.pages} · ${num(data.total)} SDM</span><div><button id="taPrev" class="btn btn-sm btn-secondary" ${view.page <= 1 ? 'disabled' : ''}>Sebelumnya</button> <button id="taNext" class="btn btn-sm btn-secondary" ${view.page >= view.pages ? 'disabled' : ''}>Berikutnya</button></div>`;
    root.querySelector('#taPrev').onclick = () => { view.page--; loadAnnual(root).catch(showError); };
    root.querySelector('#taNext').onclick = () => { view.page++; loadAnnual(root).catch(showError); };
    if (window.lucide) lucide.createIcons();
  }

  async function showDetail(root, nip) {
    const target = root.querySelector('#taDetail');
    target.classList.remove('hidden'); target.innerHTML = '<div class="muted">Memuat detail SDM…</div>';
    const data = await api(`/api/tukin/people/${encodeURIComponent(nip)}?year=${view.year}`);
    const p = data.person; const daily = data.daily || []; const conditions = data.conditions || [];
    const death = data.death; const deathAudit = data.death_audit || [];
    const deathSection = death ? `<div class="alert warning"><i data-lucide="shield-alert"></i><span><strong>Siklus SDM meninggal dunia tercatat.</strong><br>Tanggal meninggal: ${esc(death.death_date)} · transaksi baru dihentikan mulai ${esc(death.stop_effective_period)} · keputusan bulan kejadian: ${esc(String(death.payment_decision || 'HOLD_REVIEW').replaceAll('_', ' '))}.${death.pay_to_heir ? `<br>Penerima opsional: ahli waris ${esc(death.heir_name)} (${esc(death.heir_relationship)}) · ${esc(death.heir_bank_name)} ${esc(death.heir_account_number)} · dokumen ${esc(death.heir_document_ref)}` : '<br>Tidak menggunakan opsi pembayaran ahli waris.'}${deathAudit.length ? `<br>Jejak perubahan: ${num(deathAudit.length)} catatan; terakhir oleh ${esc(deathAudit[deathAudit.length - 1].actor || 'EVKIN')} pada ${esc(deathAudit[deathAudit.length - 1].created_at || '-')}.` : ''}</span></div>` : '';
    target.innerHTML = `<div class="ta-section-head"><div><h3>Detail Tukin · ${esc(p.nama || p.nip)}</h3><p class="muted">${esc(p.nip)} · ${esc(p.jabatan || '-')} · Rekening ${esc(p.bank_name || '-')} ${esc(p.account_number || '')}</p></div><button id="taCloseDetail" class="btn btn-sm btn-ghost">Tutup</button></div>
      <div class="stat-grid"><div class="stat-card blue"><div><div class="stat-val small">${money(p.summary.gross)}</div><div class="stat-label">Tukin Bruto 1 Tahun</div></div></div><div class="stat-card yellow"><div><div class="stat-val small">${money(p.summary.skp_deduction)}</div><div class="stat-label">Potongan SKP</div></div></div><div class="stat-card red"><div><div class="stat-val small">${money(p.summary.attendance_deduction)}</div><div class="stat-label">Potongan Absensi</div></div></div><div class="stat-card green"><div><div class="stat-val small">${money(p.summary.paid)}</div><div class="stat-label">Dibayarkan</div></div></div></div>
      ${deathSection}
      <h3>Rincian Bulanan</h3><div class="table-wrap"><table class="data-table sm"><thead><tr><th>Penilaian</th><th>Pembayaran</th><th>Predikat/Status</th><th>Bruto</th><th>Pot. SKP</th><th>Pot. Absen</th><th>Dibayarkan</th><th>Status</th><th>Penerima</th><th>Kondisi/Alasan</th></tr></thead><tbody>${p.months.filter(m => m.period).map(m => `<tr><td>${esc(m.period)}</td><td>${esc(m.payment_period)}</td><td>${esc(m.predicate || m.report_status)}</td><td>${money(m.gross)}</td><td>${money(m.skp_deduction)} (${Number(m.skp_rate || 0).toFixed(2)}%)</td><td>${money(m.attendance_deduction)} (${Number(m.attendance_rate || 0).toFixed(2)}%)</td><td><b>${money(m.paid)}</b></td><td>${statusPill(m.payment_status)}</td><td>${m.recipient_type === 'HEIR' ? `<b>Ahli waris</b><br>${esc(m.recipient_name)} · ${esc(m.recipient_bank_name)} ${esc(m.recipient_account_number)}` : m.death_record_id ? `Rekening pegawai<br>${esc(m.recipient_bank_name || m.bank_name)} ${esc(m.recipient_account_number || m.account_number)}` : '—'}</td><td>${esc(m.special_conditions || m.payment_reason || '-')}</td></tr>`).join('')}</tbody></table></div>
      <h3 style="margin-top:22px">Kondisi Khusus</h3><div class="table-wrap"><table class="data-table sm"><thead><tr><th>Periode</th><th>Kondisi</th><th>Rentang</th><th>Efek</th><th>Alasan</th><th>Eviden</th></tr></thead><tbody>${conditions.map(c => `<tr><td>${esc(c.assessment_period)}</td><td>${esc(c.condition_code)}</td><td>${esc(c.start_date || '-')} s.d. ${esc(c.end_date || '-')}</td><td>${esc(c.effect_type)}</td><td>${esc(c.reason || '-')}</td><td>${esc(c.evidence_ref || '-')}</td></tr>`).join('') || '<tr><td colspan="6">Tidak ada kondisi khusus.</td></tr>'}</tbody></table></div>
      <h3 style="margin-top:22px">Eviden Absensi Harian</h3><div class="table-wrap ta-daily"><table class="data-table sm"><thead><tr><th>Periode</th><th>Tanggal</th><th>Hari</th><th>Masuk</th><th>Pulang</th><th>Jenis</th><th>Status</th><th>Potongan</th><th>Alasan</th><th>Eviden</th></tr></thead><tbody>${daily.map(d => `<tr><td>${esc(d.assessment_period)}</td><td>${esc(d.work_date)}</td><td>${esc(d.day_name)}</td><td>${esc(d.check_in)}</td><td>${esc(d.check_out)}</td><td>${esc(d.attendance_type)}</td><td>${esc(d.attendance_status)}</td><td>${Number(d.reduction_rate || 0).toFixed(2)}%</td><td>${esc(d.reason || '-')}</td><td>${esc(d.evidence_ref || '-')}</td></tr>`).join('') || '<tr><td colspan="10">Eviden harian belum diimpor/ditangkap.</td></tr>'}</tbody></table></div>`;
    target.querySelector('#taCloseDetail').onclick = () => target.classList.add('hidden');
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function download(path, filename) {
    try {
      const response = await fetch(baseUrl(path));
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || 'Unduhan gagal'); }
      const blob = await response.blob(); const link = document.createElement('a');
      link.href = URL.createObjectURL(blob); link.download = filename; document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (error) { showError(error); }
  }
  function showError(error) { EVKIN.toast(error && error.message ? error.message : String(error), 'error'); }

  function bind(root) {
    const updateSheetMeta = () => {
      const select = root.querySelector('#taSheet'); const meta = root.querySelector('#taSheetMeta');
      if (!view.workbook || !view.file || !select.value) {
        meta.classList.add('empty'); meta.classList.remove('warning'); meta.innerHTML = '<i data-lucide="table-2"></i><span><b>Belum ada sheet dipilih</b><small>Pilih file, kemudian periksa sheet aktif sebelum menyimpan.</small></span>';
        return;
      }
      const sheet = view.workbook.Sheets[select.value];
      const rows = XLSX.utils.sheet_to_json(sheet, { defval:'', raw:false });
      const range = XLSX.utils.decode_range(sheet['!ref'] || 'A1:A1');
      const matrix = XLSX.utils.sheet_to_json(sheet, { header:1, defval:'', raw:false });
      const headers = (matrix[0] || []).map(value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, ''));
      const hasNip = headers.includes('nip'); const ready = hasNip && rows.length > 0;
      meta.classList.remove('empty'); meta.classList.toggle('warning', !ready);
      if (!hasNip) meta.innerHTML = `<i data-lucide="triangle-alert"></i><span><b>Sheet aktif: ${esc(select.value)} — bukan sheet data</b><small>Kolom NIP tidak ditemukan. Pilih sheet data, bukan sheet petunjuk.</small></span>`;
      else if (!rows.length) meta.innerHTML = `<i data-lucide="triangle-alert"></i><span><b>Sheet aktif: ${esc(select.value)} — belum berisi data</b><small>${esc(view.file.name)} · format kolom terdeteksi · isi minimal satu baris SDM.</small></span>`;
      else meta.innerHTML = `<i data-lucide="circle-check-big"></i><span><b>Sheet aktif: ${esc(select.value)}</b><small>${esc(view.file.name)} · ${rows.length.toLocaleString('id-ID')} baris data · ${range.e.c + 1} kolom</small></span>`;
      root.querySelector('#taImport').disabled = !ready;
      if (window.lucide) lucide.createIcons();
    };
    root.querySelector('#taAssessment').onchange = e => { root.querySelector('#taPayment').value = nextMonth(e.target.value); };
    root.querySelector('#taLiveAssessment').onchange = e => { root.querySelector('#taLivePayment').value = nextMonth(e.target.value); };
    root.querySelector('#taSource').onchange = e => {
      const daily = e.target.value === 'ATTENDANCE_DAILY';
      const link = root.querySelector('#taTemplate');
      link.href = daily ? 'assets/templates/Template_Eviden_Absensi_Harian.xlsx' : 'assets/templates/Template_Final_Tukin_Historis.xlsx';
    };
    root.querySelector('#taFile').onchange = async e => {
      view.file = e.target.files && e.target.files[0]; view.workbook = null;
      const select = root.querySelector('#taSheet');
      root.querySelector('#taImport').disabled = true;
      if (!view.file) { select.disabled = true; select.innerHTML = '<option value="">Pilih file Excel terlebih dahulu</option>'; updateSheetMeta(); return; }
      try {
        const bytes = await view.file.arrayBuffer();
        view.workbook = XLSX.read(bytes, { type: 'array', cellDates: true });
        select.innerHTML = view.workbook.SheetNames.map((name, index) => `<option value="${esc(name)}">${index + 1}. ${esc(name)}</option>`).join(''); select.disabled = false;
        root.querySelector('#taImportState').textContent = `${view.workbook.SheetNames.length} sheet ditemukan; sheet pertama dipilih otomatis.`;
        updateSheetMeta();
      } catch (error) {
        select.disabled = true; select.innerHTML = '<option value="">File tidak dapat dibaca</option>'; updateSheetMeta(); showError(error);
      }
    };
    root.querySelector('#taSheet').onchange = updateSheetMeta;
    root.querySelector('#taImport').onclick = async () => {
      if (!view.workbook || !view.file) return EVKIN.toast('Pilih file Excel terlebih dahulu.', 'error');
      const button = root.querySelector('#taImport'); const info = root.querySelector('#taImportState');
      try {
        const assessment = root.querySelector('#taAssessment').value;
        const payment = root.querySelector('#taPayment').value;
        if (nextMonth(assessment) !== payment) throw new Error('Periode pembayaran harus satu bulan setelah periode penilaian.');
        button.disabled = true; info.textContent = 'Membaca dan mengirim data…';
        const sheetName = root.querySelector('#taSheet').value;
        // raw:false preserves long NIP/account identifiers as the displayed text;
        // the backend normalizes localized percentages and Rupiah strings safely.
        const rows = XLSX.utils.sheet_to_json(view.workbook.Sheets[sheetName], { defval: '', raw: false });
        if (!rows.length) throw new Error('Sheet terpilih tidak berisi data');
        const result = await api('/api/tukin/history/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_type: root.querySelector('#taSource').value, assessment_period: root.querySelector('#taAssessment').value, payment_period: root.querySelector('#taPayment').value, source_file: view.file.name, rows }) });
        info.textContent = `${num(result.imported)} tersimpan, ${num(result.rejected)} ditolak`;
        EVKIN.toast('Histori Tukin berhasil disimpan.', 'success'); await refresh(root);
      } catch (error) { info.textContent = 'Impor gagal'; showError(error); } finally { button.disabled = false; }
    };
    root.querySelector('#taCapture').onclick = async () => {
      const button = root.querySelector('#taCapture');
      try {
        const assessment = root.querySelector('#taLiveAssessment').value;
        const payment = root.querySelector('#taLivePayment').value;
        if (nextMonth(assessment) !== payment) throw new Error('Periode pembayaran harus satu bulan setelah periode penilaian.');
        button.disabled = true;
        const result = await api('/api/tukin/periods/capture-live', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ assessment_period: assessment, payment_period: payment }) });
        EVKIN.toast(`${num(result.captured)} final absensi disinkronkan; SKP approved dipertahankan.`, 'success'); await refresh(root);
      }
      catch (error) { showError(error); } finally { button.disabled = false; }
    };
    root.querySelector('#taSearchBtn').onclick = () => { view.year = Number(root.querySelector('#taYear').value); view.q = root.querySelector('#taSearch').value.trim(); view.page = 1; refresh(root).catch(showError); };
    root.querySelector('#taSearch').onkeydown = e => { if (e.key === 'Enter') root.querySelector('#taSearchBtn').click(); };
    root.querySelector('#taDownloadAnnual').onclick = () => download(`/api/tukin/export/annual?year=${view.year}`, `REKAP_TUKIN_${view.year}.xlsx`);
    root.querySelector('#taResetModule').onclick = async () => {
      try { await EVKIN.resetModuleData('pengelolaan_tukin', 'Pengelolaan Tukin', [], () => refresh(root)); }
      catch (error) { showError(error); }
    };
    root.querySelector('#taDownloadFinal').onclick = () => { const p = root.querySelector('#taLiveAssessment').value; download(`/api/tukin/export/final?assessment_period=${encodeURIComponent(p)}`, `FINAL_TUKIN_${p}.xlsx`); };
  }

  async function loadCombined(root, page = 1) {
    const button = root.querySelector('#taCombinedLoad');
    const area = root.querySelector('#taCombinedResult');
    button.disabled = true;
    root.querySelector('#taCombinedExport').disabled = true;
    view.combinedSnapshot = null;
    const request = view.combinedRequest = (view.combinedRequest || 0) + 1;
    view.adjustmentRequest = (view.adjustmentRequest || 0) + 1;
    root.querySelector('#taCombinedAdjustment').classList.add('hidden');
    area.textContent = 'Memasangkan Master SDM, SKP disetujui, dan Final Absensi...';
    try {
      const period = root.querySelector('#taCombinedPeriod').value;
      const query = root.querySelector('#taCombinedSearch').value.trim();
      const scope = root.querySelector('#taCombinedScope').value;
      const data = await api(`/api/tukin/combined?assessment_period=${encodeURIComponent(period)}&scope=${scope}&page=${page}&q=${encodeURIComponent(query)}`);
      if (request !== view.combinedRequest) return;
      view.combinedSnapshot = {period, scope, fingerprint:data.fingerprint};
      root.querySelector('#taCombinedExport').disabled = false;
      area.innerHTML = `<p>${num(data.summary.total)} SDM · ${num(data.summary.complete)} lengkap · ${num(data.summary.review)} perlu review. Hasil pencarian: ${num(data.total)}.</p>
        <p class="muted">Potongan dihitung dari komponen masing-masing, lalu dibulatkan ke rupiah. Penyesuaian positif menambah hasil; negatif mengurangi. Ekspor memuat seluruh peserta pada cakupan terpilih, termasuk yang perlu review.</p>
        ${!data.summary.total ? '<div class="alert info">Belum ada peserta pada cakupan ini. Selesaikan Final Absensi untuk periode terpilih, atau pilih cakupan histori jika menggunakan hasil bulanan tersimpan.</div>' : ''}
        <div class="table-wrap"><table class="data-table sm"><thead><tr><th>NIP / Nama</th><th>Bruto / Sumber</th><th>Predikat SKP</th><th>Pot. SKP %</th><th>Pot. Absensi %</th><th>Nominal SKP</th><th>Nominal Absensi</th><th>Total Potongan</th><th>Hasil Hitungan</th><th>Penyesuaian</th><th>Final Dasar Tukin</th><th>Status / Validasi</th><th>Tindakan</th></tr></thead><tbody>${data.rows.map((row,index)=>`<tr><td>${esc(row.nip)}<br>${esc(row.nama)}<br><small>${esc(row.attendance_source)}</small></td><td>${money(row.tukin_gross)}<br><small>${esc(row.tukin_gross_source || 'Belum tersedia')}</small></td><td>${esc(row.predicate_skp || 'Belum tersedia')}</td><td>${row.skp_rate == null ? '—' : esc(row.skp_rate)}</td><td>${row.attendance_rate == null ? '—' : esc(row.attendance_rate)}</td><td>${money(row.skp_deduction)}</td><td>${money(row.attendance_deduction)}</td><td>${money(row.total_deduction)}</td><td>${money(row.calculated_entitlement)}</td><td>${money(row.manual_adjustment)}<br><small>${esc(row.adjustment_reason)}</small></td><td><strong>${money(row.final_tukin)}</strong></td><td>${esc(row.payment_status)}<br>${esc(row.issues)}</td><td><button class="btn btn-secondary" data-detail="${index}">Rincian</button> <button class="btn btn-secondary" data-adjust="${index}" ${(row.payable_estimate == null && !row.adjustment_reason) || !row.attendance_participant || row.period_locked ? 'disabled' : ''}>Penyesuaian</button><button class="btn btn-secondary" data-adjust-audit="${index}">Audit</button></td></tr>`).join('')}</tbody></table></div>
        <div class="actions-row"><button id="taCombinedPrev" class="btn btn-secondary" ${page<=1?'disabled':''}>Sebelumnya</button><span>Halaman ${page} / ${Math.max(1,Math.ceil(data.total/50))}</span><button id="taCombinedNext" class="btn btn-secondary" ${page*50>=data.total?'disabled':''}>Berikutnya</button></div>`;
      root.querySelector('#taCombinedPrev').onclick = () => loadCombined(root,page-1);
      root.querySelector('#taCombinedNext').onclick = () => loadCombined(root,page+1);
      area.querySelectorAll('[data-adjust]').forEach(btn => { btn.onclick = () => editCombinedAdjustment(root, data.rows[Number(btn.dataset.adjust)], period, page); });
      area.querySelectorAll('[data-adjust-audit]').forEach(btn => { btn.onclick = () => showCombinedAudit(root, data.rows[Number(btn.dataset.adjustAudit)], period); });
      area.querySelectorAll('[data-detail]').forEach(btn => { btn.onclick = () => showCombinedDetail(root, data.rows[Number(btn.dataset.detail)]); });
    } catch(error) { if (request === view.combinedRequest) area.textContent = 'Gabungan gagal dimuat: '+error.message; }
    finally { if (request === view.combinedRequest) button.disabled = false; }
  }

  function showCombinedDetail(root, row) {
    const panel = root.querySelector('#taCombinedAdjustment');
    panel.classList.remove('hidden');
    panel.innerHTML = `<h4>Rincian perhitungan · ${esc(row.nip)} · ${esc(row.nama)}</h4>
      <div class="table-wrap"><table class="data-table sm"><tbody>
      <tr><th>Tukin bruto</th><td>${money(row.tukin_gross)}<br><small>Sumber: ${esc(row.tukin_gross_source || 'Belum tersedia')}</small></td><th>Status data</th><td>${esc(row.status)}</td></tr>
      <tr><th>Komponen SKP (70%)</th><td>${money(row.skp_component)} · potongan ${row.skp_rate == null ? '—' : esc(row.skp_rate) + '%'}</td><th>Predikat SKP</th><td>${esc(row.predicate_skp || 'Belum tersedia')}</td></tr>
      <tr><th>Potongan SKP</th><td>${money(row.skp_deduction)}</td><th>Komponen absensi (30%)</th><td>${money(row.attendance_component)} · potongan ${row.attendance_rate == null ? '—' : esc(row.attendance_rate) + '%'}</td></tr>
      <tr><th>Potongan absensi</th><td>${money(row.attendance_deduction)}</td><th>Total potongan</th><td>${money(row.total_deduction)}</td></tr>
      <tr><th>Hasil perhitungan</th><td>${money(row.calculated_entitlement)}</td><th>Penyesuaian manual</th><td>${money(row.manual_adjustment)}<br>${esc(row.adjustment_reason || 'Tidak ada')}</td></tr>
      <tr><th>Final dasar Tukin</th><td><strong>${money(row.final_tukin)}</strong></td><th>Status pembayaran</th><td>${esc(row.payment_status)}<br>${esc(row.issues || 'Tidak ada masalah')}</td></tr>
      </tbody></table></div><button class="btn btn-secondary" id="taDetailClose">Tutup</button>`;
    panel.querySelector('#taDetailClose').onclick = () => panel.classList.add('hidden');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function editCombinedAdjustment(root, row, period, page) {
    view.adjustmentRequest = (view.adjustmentRequest || 0) + 1;
    const panel = root.querySelector('#taCombinedAdjustment');
    panel.classList.remove('hidden');
    panel.innerHTML = `<h4>Penyesuaian · ${esc(row.nip)} · ${esc(row.nama)}</h4>
      <p>Hasil sebelum penyesuaian: <b>${money(row.payable_estimate)}</b>. Final harus berada antara Rp0 dan ${money(row.tukin_gross)}. Isi 0 untuk membatalkan penyesuaian sebelumnya; alasan tetap dicatat.</p>
      <form id="taAdjustmentForm"><div class="form-row"><div><label for="taAdjustmentAmount">Penyesuaian rupiah (+ / −)</label><input id="taAdjustmentAmount" name="amount" type="number" step="1" required ${row.payable_estimate == null ? 'readonly value="0"' : `min="${-row.payable_estimate}" max="${row.tukin_gross-row.payable_estimate}" value="${esc(row.manual_adjustment || 0)}"`}></div><div><label for="taAdjustmentActor">Nama petugas</label><input id="taAdjustmentActor" name="actor" required maxlength="150"></div></div>
      <label for="taAdjustmentReason">Alasan dan rujukan penyesuaian</label><textarea id="taAdjustmentReason" name="reason" required maxlength="2000">${esc(row.adjustment_reason)}</textarea>
      <p id="taAdjustmentPreview"></p><div class="actions-row"><button type="submit" class="btn btn-primary">Simpan Penyesuaian</button><button type="button" id="taAdjustmentCancel" class="btn btn-secondary">Tutup</button></div><p id="taAdjustmentMessage" role="status"></p></form>`;
    const form = panel.querySelector('form');
    const amount = form.elements.namedItem('amount');
    const updatePreview = () => { panel.querySelector('#taAdjustmentPreview').textContent = row.payable_estimate == null ? 'Data ditahan/belum lengkap. Hanya pembatalan penyesuaian lama yang diperbolehkan; nominal final tetap mengikuti validasi sumber.' : 'Final setelah penyesuaian: '+money(Number(row.payable_estimate)+Number(amount.value)); };
    amount.oninput = updatePreview; updatePreview();
    panel.querySelector('#taAdjustmentCancel').onclick = () => panel.classList.add('hidden');
    form.onsubmit = async event => {
      event.preventDefault();
      const submit = form.querySelector('[type="submit"]'); submit.disabled = true;
      try {
        await api('/api/tukin/combined/adjustment', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
          assessment_period:period, nip:row.nip, amount:amount.value,
          actor:form.elements.namedItem('actor').value, reason:form.elements.namedItem('reason').value, expected:row.edit_token
        })});
        EVKIN.toast('Penyesuaian dan audit berhasil disimpan.', 'success');
        await loadCombined(root,page);
      } catch(error) { panel.querySelector('#taAdjustmentMessage').textContent = error.message; }
      finally { submit.disabled = false; }
    };
    panel.scrollIntoView({behavior:'smooth',block:'nearest'});
  }

  async function showCombinedAudit(root, row, period) {
    const request = view.adjustmentRequest = (view.adjustmentRequest || 0) + 1;
    const panel = root.querySelector('#taCombinedAdjustment');
    panel.classList.remove('hidden'); panel.textContent = 'Memuat audit penyesuaian…';
    try {
      const data = await api(`/api/tukin/combined/adjustment/audit?assessment_period=${encodeURIComponent(period)}&nip=${encodeURIComponent(row.nip)}`);
      if (request !== view.adjustmentRequest) return;
      panel.innerHTML = `<h4>Audit penyesuaian · ${esc(row.nip)} · ${esc(row.nama)}</h4>${data.rows.length ? '<div class="table-wrap"><table class="data-table"><thead><tr><th>Waktu</th><th>Petugas</th><th>Sebelum</th><th>Sesudah</th><th>Alasan</th></tr></thead><tbody>'+data.rows.map(item=>`<tr><td>${esc(item.created_at)}</td><td>${esc(item.actor)}</td><td>${money(item.old_value ? item.old_value.amount : 0)}</td><td>${money(item.new_value.amount)}</td><td>${esc(item.new_value.reason)}</td></tr>`).join('')+'</tbody></table></div>' : '<p>Belum ada perubahan penyesuaian.</p>'}`;
    } catch(error) { if (request === view.adjustmentRequest) panel.textContent = error.message; }
  }

  async function refresh(root) {
    view.periodRows = [];
    await loadPeriods(root);
    await Promise.all([loadFinalResults(root), loadAnnual(root), loadConditions(root)]);
  }

  EVKIN.tukinAnnualMod = {
    openPeriod(period) { view.requestedPeriod = period; EVKIN.go('tukin-annual'); },
    render(el) {
      shell(el); bind(el);
      el.querySelector('#taCombinedLoad').onclick = () => loadCombined(el);
      ['#taCombinedPeriod','#taCombinedScope'].forEach(selector => {
        el.querySelector(selector).onchange = () => loadCombined(el);
      });
      el.querySelector('#taCombinedSkp').onclick = () => EVKIN.go('skp-assessment');
      el.querySelector('#taCombinedExport').onclick = async () => {
        const button = el.querySelector('#taCombinedExport');
        button.disabled = true;
        try {
          const period = el.querySelector('#taCombinedPeriod').value;
          const scope = el.querySelector('#taCombinedScope').value;
          if (!view.combinedSnapshot || view.combinedSnapshot.period !== period || view.combinedSnapshot.scope !== scope) throw new Error('Klik Hitung Gabungan untuk periode dan cakupan ini sebelum ekspor.');
          await download(`/api/tukin/combined/export?assessment_period=${encodeURIComponent(period)}&scope=${scope}&expected=${encodeURIComponent(view.combinedSnapshot.fingerprint)}`, `DASAR_TUKIN_${period}.xlsx`);
        }
        catch(error) { showError(error); }
        finally { button.disabled = false; }
      };
      refresh(el).catch(showError); if (window.lucide) lucide.createIcons();
    }
  };
})();
