/* EVKIN ABSENSI v3.1 - harian.js */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util, S = EVKIN.state, C = EVKIN.calc;
  const mod = EVKIN.harianMod = {};
  let nipSearch = '', monthFilter = '';

  mod.process = async function (options = {}) {
    if (mod.processing) throw new Error('Hitung Harian masih berjalan. Tunggu sampai selesai.');
    mod.processing = true;
    try {
    if (S.workflowLoadError) throw new Error(S.workflowLoadError);
    if (EVKIN.importMod && EVKIN.importMod.saving) throw new Error('Tunggu penyimpanan impor selesai.');
    const source = S.data, timeMode = S.timeMode;
    const recs = S.data.filter(d => !d.deleted && d.tanggal && d.nip);
    if (!recs.length) throw new Error('Tidak ada record valid pada bulan terpilih. Periksa periode dan pemulihan data impor.');
    if (EVKIN.progress) EVKIN.progress({title: 'Hitung Harian', percent: 0, message: `Menyiapkan ${recs.length} record...`});
    const master = await EVKIN.lookupWorkflowMaster(recs.map(row => row.nip));
    const ctx = C.buildContext();
    ctx.pegByNip = Object.fromEntries(master);
    const daily = [];
    for (let offset = 0; offset < recs.length; offset += 500) {
      for (const record of recs.slice(offset, offset + 500)) {
        try { daily.push(C.computeRecord(record, ctx, timeMode)); }
        catch (error) { throw new Error(`Gagal menghitung baris ${daily.length + 1}: ${error.message}`); }
      }
      if (options.onProgress) options.onProgress(daily.length, recs.length);
      if (EVKIN.progress) EVKIN.progress({title: 'Hitung Harian', percent: Math.round(daily.length / recs.length * 100), message: `Menghitung ${daily.length} dari ${recs.length} record...`});
      if (offset + 500 < recs.length) await new Promise(resolve => setTimeout(resolve, 0));
    }
    if (S.data !== source || S.timeMode !== timeMode) throw new Error('Periode atau mode berubah selama perhitungan. Hitung ulang.');
    S.daily = daily;
    if (EVKIN.assertDailyCoverage) EVKIN.assertDailyCoverage();
    S.dailyComplete = true;
    if (EVKIN.db && EVKIN.db.saveDaily) {
      EVKIN.db.saveDaily(S.daily).catch((err) => console.warn('Gagal simpan harian ke IndexedDB:', err));
    }
    EVKIN.invalidateFrom('harian', {save:false});
    EVKIN.auditMod.logStage('harian', 'PROCESSED:' + S.daily.length);
    if (options.sync !== false) {
      try { await EVKIN.syncBackendWorkflow(undefined, {derivedOnly:true}); }
      catch (error) { throw new Error('Hasil harian sudah dihitung, tetapi gagal disimpan: ' + error.message); }
    }
    if (EVKIN.progress) EVKIN.progress({title: 'Hitung Harian', percent: 100, message: `${S.daily.length} record selesai dan tersimpan.`, state: 'done'});
    return S.daily;
    } finally { mod.processing = false; }
  };

  mod.render = function (el) {
    if (!EVKIN.stepUnlocked('harian')) { el.innerHTML = locked('Selesaikan Import & Konfigurasi terlebih dahulu.'); return; }
    const months = (S.importStats && S.importStats.months) || [];
    // Auto-select first month if S.month not set or invalid
    if (!S.month || !months.includes(S.month)) {
      S.month = months.length > 0 ? months[0] : '';
    }
    if (monthFilter && !months.includes(monthFilter)) monthFilter = '';
    const monthOpts = '<option value="">Semua bulan</option>' + months.map(m => `<option value="${m}" ${monthFilter === m ? 'selected' : ''}>${U.monthLabel(m)}</option>`).join('');
    el.innerHTML = `
      <div class="module-head"><div><h2>③ Hitung Harian</h2><p class="muted">Metode ditentukan otomatis dari Master Jabatan.</p></div><div>${EVKIN.stepDone('harian') ? '<span class="pill green">✓ Selesai</span>' : '<span class="pill gray">Belum dihitung</span>'}</div></div>
      <div class="card">
        <div class="form-row">
          <div><label>Filter bulan tampilan</label><select id="hMonth" data-testid="harian-month">${monthOpts}</select></div>
          <div><label>Mode Waktu</label><select id="hMode" data-testid="harian-mode">
            <option value="original" ${S.timeMode === 'original' ? 'selected' : ''}>Original</option>
            <option value="wib" ${S.timeMode === 'wib' ? 'selected' : ''}>Normalisasi WIB (Kurangi WITA/WIT)</option>
            <option value="wib-add" ${S.timeMode === 'wib-add' ? 'selected' : ''}>Normalisasi WIB (Tambah WIT/WITA)</option></select></div>
          <div style="align-self:flex-end"><button class="btn btn-primary" id="btnHitung" data-testid="harian-run"><i data-lucide="calculator"></i> Hitung Semua Data Impor</button></div>
        </div>
        <p class="muted">Seluruh record valid dihitung untuk semua bulan impor. Hari efektif bulan aktif (${U.monthLabel(S.month)}): <b>${EVKIN.configMod.effectiveDays(S.month)}</b> hari</p>
      </div>
      <div class="alert info">${S.data.filter(r => !r.deleted).length} record impor aktif · ${S.daily.length} hasil Harian seluruh bulan · ${(S.importStats && S.importStats.rejectedRows) || 0} baris sumber ditolak (NIP/tanggal tidak valid).</div>
      <div id="harianResult">${S.daily.length ? resultView() : '<div class="alert info">Belum ada data. Klik <b>Hitung Harian</b>.</div>'}</div>
    `;
    el.querySelector('#hMonth').onchange = (e) => { monthFilter = e.target.value; if (monthFilter) S.month = monthFilter; S.harianPage = 0; EVKIN.go('harian'); };
    el.querySelector('#hMode').onchange = (e) => { S.timeMode = e.target.value; EVKIN.invalidateFrom('config'); EVKIN.go('harian'); };
    const nipInput = el.querySelector('#harianNipSearch');
    if (nipInput) nipInput.oninput = (e) => { nipSearch = e.target.value.trim().toLowerCase(); S.harianPage = 0; EVKIN.go('harian'); };
    el.querySelector('#btnHitung').onclick = async () => {
      const button = el.querySelector('#btnHitung');
      button.disabled = true;
      el.querySelector('#hMonth').disabled = true;
      el.querySelector('#hMode').disabled = true;
      button.textContent = 'Membaca Master SDM dan menghitung...';
      try { await mod.process({onProgress:(done,total) => {button.textContent = `Menghitung ${done}/${total}...`;}}); EVKIN.toast('Hitung harian selesai dan tersimpan: ' + S.daily.length + ' record'); EVKIN.go('harian'); }
      catch (ex) { if (EVKIN.progress) EVKIN.progress({title: 'Hitung Harian gagal', message: ex.message, state: 'error'}); EVKIN.toast(ex.message, 'error'); el.querySelector('#harianResult').innerHTML = `<div class="alert error" role="alert">${U.esc(ex.message)}</div>`; }
      finally { button.disabled = false; button.textContent = 'Hitung Semua Data Impor'; el.querySelector('#hMonth').disabled = false; el.querySelector('#hMode').disabled = false; }
    };

    // Pagination handlers untuk Hitung Harian
    const ITEMS_PER_PAGE = 10;
    const totalPages = Math.ceil(filteredDaily().length / ITEMS_PER_PAGE);
    const btnHarianPrev = el.querySelector('#harianPrev');
    const btnHarianNext = el.querySelector('#harianNext');
    if (btnHarianPrev) btnHarianPrev.onclick = () => { S.harianPage = Math.max(0, S.harianPage - 1); EVKIN.save(); EVKIN.go('harian'); };
    if (btnHarianNext) btnHarianNext.onclick = () => { S.harianPage = Math.min(totalPages - 1, S.harianPage + 1); EVKIN.save(); EVKIN.go('harian'); };

    if (window.lucide) lucide.createIcons();
  };

  function resultView() {
    const ITEMS_PER_PAGE = 10;
    const d = filteredDaily();
    const tot = d.reduce((a, x) => a + x.totalHarian, 0);
    const totalPages = Math.ceil(d.length / ITEMS_PER_PAGE);
    let currentPage = Math.max(0, Math.min(S.harianPage, totalPages - 1));
    S.harianPage = currentPage;

    const startIdx = currentPage * ITEMS_PER_PAGE;
    const endIdx = startIdx + ITEMS_PER_PAGE;
    const pageData = d.slice(startIdx, endIdx);

    const head = ['NIP', 'Nama', 'Jabatan', 'Tgl Kerja', 'Hari', 'Tanggal/Jam Masuk', 'Tanggal/Jam Pulang', 'Durasi', 'Zona', 'Normalisasi', 'Metode', 'Jenis', 'Jadwal', 'Status', 'Libur', 'Cuti', 'Dup', 'Lengkap', 'Terlmbt', 'Plg Cpt', 'Durasi%', 'Tdk Lgkp', 'Total', 'Flag'];
    const rows = pageData.map(x => `<tr class="${x.flags.length ? 'row-flag' : ''}">
      <td>${U.esc(x.nip)}</td><td>${U.esc(x.nama)}</td><td>${U.esc(x.jabatan)}</td><td>${U.esc(x.tanggal)}</td><td>${U.esc(x.hari)}</td>
      <td>${U.esc((x.tanggalMasuk || x.tanggal) + (x.masukAt ? ' ' + x.masukAt.slice(11) : ' ' + x.jamMasuk))}</td><td>${U.esc((x.tanggalPulang || x.tanggal) + (x.pulangAt ? ' ' + x.pulangAt.slice(11) : ' ' + x.jamPulang))}</td><td>${U.esc(x.durasi)}</td><td>${U.esc(x.zona)}</td><td>${U.esc(x.jamNormalisasi)}</td>
      <td><span class="pill ${x.metode === 'durasi' ? 'blue' : 'gray'}">${x.metode === 'durasi' ? 'Durasi' : 'Reguler'}</span></td>
      <td>${U.esc(x.jenis)}</td><td>${U.esc(x.statusJadwal || '-')}</td><td>${U.esc(x.statusAbsensi || '-')}</td><td>${x.statusHariLibur.startsWith('Ya') ? '<span class="pill yellow">Libur</span>' : '-'}</td>
      <td>${U.esc(x.statusCuti)}</td><td>${x.statusDuplikasi ? '<span class="pill red">Dup</span>' : '-'}</td>
      <td>${x.statusLengkap === 'Tidak Lengkap' ? '<span class="pill red">Tidak</span>' : (x.statusLengkap || '-')}</td>
      <td>${x.potKeterlambatan || ''}</td><td>${x.potPulangCepat || ''}</td><td>${x.potDurasi || ''}</td><td>${x.potTidakLengkap || ''}</td>
      <td><b>${x.totalHarian}%</b></td><td class="err small">${U.esc(x.flags.join(', '))}</td></tr>`).join('');

    const paginationInfo = `<div style="text-align: center; margin: 12px 0; font-size: 13px; color: #666;">
      <strong>Data ${startIdx + 1}–${Math.min(endIdx, d.length)} dari ${d.length} record</strong> |
      <strong>Halaman ${currentPage + 1} dari ${totalPages}</strong>
    </div>`;

    const paginationButtons = `<div style="display: flex; gap: 8px; justify-content: center; margin-top: 12px; flex-wrap: wrap;">
      <button class="btn btn-secondary" id="harianPrev" ${currentPage === 0 ? 'disabled' : ''}>
        <i data-lucide="chevron-left"></i> Sebelumnya
      </button>
      <button class="btn btn-secondary" id="harianNext" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>
        Berikutnya <i data-lucide="chevron-right"></i>
      </button>
    </div>`;

    return `<div class="card"><h3>Hasil Harian — ${U.monthLabel(S.month)} <span class="muted">(${d.length} record)</span></h3>
      <div class="filter-bar"><input type="search" id="harianNipSearch" placeholder="Cari NIP..." value="${U.esc(nipSearch)}" data-testid="harian-nip-search" /></div>
      <p class="muted">Total potongan harian terkumpul: <b>${U.round2(tot)}%</b> (akan direkap per SDM).</p>
      <div class="table-wrap"><table class="data-table sm" data-testid="harian-table"><thead><tr>${head.map(h => '<th>' + h + '</th>').join('')}</tr></thead><tbody>${rows}</tbody></table></div>
      ${paginationInfo}
      ${paginationButtons}
      <div class="actions-row"><button class="btn btn-ghost" onclick="EVKIN.go('config')"><i data-lucide="arrow-left"></i> Kembali</button>
      <button class="btn btn-primary" onclick="EVKIN.go('semifinal')">Lanjut: Semi Final <i data-lucide="arrow-right"></i></button></div></div>`;
  }

  function filteredDaily() {
    const rows = monthFilter ? S.daily.filter(x => (x.monthKey || x.bulan || String(x.tanggalKey || '').slice(0,7)) === monthFilter) : S.daily;
    return nipSearch ? rows.filter(x => String(x.nip || '').toLowerCase().includes(nipSearch)) : rows;
  }
  function locked(m) { return `<div class="module-head"><h2>③ Hitung Harian <span class="pill gray">🔒 Terkunci</span></h2></div><div class="alert warn">${m}</div>`; }
})();
