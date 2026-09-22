/* EVKIN ABSENSI v3.1 - config.js */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util, M = EVKIN.master, S = EVKIN.state;
  const mod = EVKIN.configMod = {};

  mod.effectiveAuto = function (monthKey) {
    const cfg = (S.config = EVKIN.normalizeConfig ? EVKIN.normalizeConfig(S.config) : (S.config || EVKIN.defaultConfig()));
    if (!monthKey) return 0;
    const [y, m] = monthKey.split('-').map(Number);
    const holidays = Array.isArray(cfg.holidays) ? cfg.holidays : [];
    const hol = new Set(holidays.map(h => h.d));
    let n = 0;
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    for (let d = 1; d <= days; d++) {
      const key = `${y}-${U.pad(m)}-${U.pad(d)}`;
      const w = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
      if (w !== 0 && w !== 6 && !hol.has(key)) n++;
    }
    return n;
  };

  mod.effectiveDays = function (monthKey) {
    const c = (S.config = EVKIN.normalizeConfig ? EVKIN.normalizeConfig(S.config) : (S.config || EVKIN.defaultConfig()));
    return c.effectiveDaysMode === 'manual' ? (+c.effectiveDaysManual || 0) : mod.effectiveAuto(monthKey);
  };

  mod.render = function (el) {
    const c = (S.config = EVKIN.normalizeConfig ? EVKIN.normalizeConfig(S.config) : (S.config || EVKIN.defaultConfig()));
    const months = (S.importStats && S.importStats.months) || [];
    const monthOpts = months.map(m => `<option value="${m}" ${S.month === m ? 'selected' : ''}>${U.monthLabel(m)}</option>`).join('');
    el.innerHTML = `
      <div class="module-head"><div><h2>② Konfigurasi</h2><p class="muted">Wajib diselesaikan sebelum Hitung Harian.</p></div>
        <div>${badge('config')}</div></div>

      <div class="config-tabs">
        <button class="ctab active" data-tab="kalender">Kalender & Hari Efektif</button>
        <button class="ctab" data-tab="jabatan">Master Jabatan</button>
        <button class="ctab" data-tab="jam">Jam Dasar & Flexi</button>
        <button class="ctab" data-tab="potongan">Aturan Potongan</button>
        <button class="ctab" data-tab="zona">Zona & Cuti</button>
      </div>

      <div class="ctab-body" id="tab-kalender">
        <div class="card">
          <h3>Mode Hari Efektif</h3>
          <div class="form-row">
            <label><input type="radio" name="effMode" value="auto" ${c.effectiveDaysMode === 'auto' ? 'checked' : ''} data-testid="eff-mode-auto"/> Otomatis (dari kalender)</label>
            <label><input type="radio" name="effMode" value="manual" ${c.effectiveDaysMode === 'manual' ? 'checked' : ''} data-testid="eff-mode-manual"/> Manual (override)</label>
          </div>
          <div class="form-row">
            <div><label>Bulan Acuan</label><select id="effMonth" data-testid="eff-month">${monthOpts || '<option value="">- import dulu -</option>'}</select></div>
            <div><label>Hari Efektif Otomatis</label><input type="text" id="effAuto" value="${mod.effectiveAuto(S.month)}" readonly /></div>
            <div><label>Hari Efektif Manual</label><input type="number" id="effManual" value="${c.effectiveDaysManual}" data-testid="eff-manual" /></div>
          </div>
          <p class="muted">Hari efektif otomatis = jumlah hari Senin–Jumat non-libur pada bulan acuan.</p>
        </div>
        <div class="card">
          <h3>Hari Libur / Kalender Kerja <span class="muted">(bawaan 2026, dapat diedit)</span></h3>
          <div class="form-row">
            <div><label>Tanggal</label><input type="date" id="holDate" data-testid="holiday-date"/></div>
            <div style="flex:2"><label>Keterangan</label><input type="text" id="holName" placeholder="mis. Cuti Bersama" data-testid="holiday-name"/></div>
            <div style="align-self:flex-end"><button class="btn btn-secondary" id="addHol" data-testid="add-holiday">+ Tambah</button></div>
          </div>
          <div class="table-wrap" style="max-height:260px;overflow:auto">
            <table class="data-table"><thead><tr><th>Tanggal</th><th>Keterangan</th><th></th></tr></thead>
            <tbody id="holBody">${holRows()}</tbody></table>
          </div>
        </div>
      </div>

      <div class="ctab-body hidden" id="tab-jabatan">
        <div class="card">
          <h3>Master Jabatan</h3>
          <p class="muted">Metode <b>Durasi Aktual</b> untuk Wali Asuh/Wali Asrama/Satpam. Metode <b>Reguler</b> untuk jabatan lainnya. Shift hanya sebagai flag, bukan dasar potongan.</p>
          <div class="form-row">
            <div style="flex:2"><label>Nama Jabatan</label><input type="text" id="jabName" data-testid="jab-name"/></div>
            <div><label>Metode</label><select id="jabMethod" data-testid="jab-method"><option value="reguler">Reguler</option><option value="durasi">Durasi Aktual</option></select></div>
            <div style="align-self:flex-end"><button class="btn btn-secondary" id="addJab" data-testid="add-jab">+ Tambah</button></div>
          </div>
          <div class="table-wrap"><table class="data-table"><thead><tr><th>Jabatan</th><th>Metode</th><th></th></tr></thead>
          <tbody id="jabBody">${jabRows()}</tbody></table></div>
        </div>
      </div>

      <div class="ctab-body hidden" id="tab-jam">
        <div class="card">
          <h3>Jam Dasar (Reguler)</h3>
          <div class="form-row">
            <div><label>Senin–Kamis Masuk</label><input type="time" id="sk_masuk" value="${c.jamDasar.senKam.masuk}"/></div>
            <div><label>Senin–Kamis Pulang</label><input type="time" id="sk_pulang" value="${c.jamDasar.senKam.pulang}"/></div>
            <div><label>Jumat Masuk</label><input type="time" id="jm_masuk" value="${c.jamDasar.jumat.masuk}"/></div>
            <div><label>Jumat Pulang</label><input type="time" id="jm_pulang" value="${c.jamDasar.jumat.pulang}"/></div>
          </div>
        </div>
        <div class="card">
          <h3>Flexi Time</h3>
          <label><input type="checkbox" id="fxEnabled" ${c.flexi.enabled ? 'checked' : ''} data-testid="flexi-enabled"/> Aktifkan Flexi Time</label>
          <div class="form-row" style="margin-top:12px">
            <div><label>Masuk mulai</label><input type="time" id="fx_start" value="${c.flexi.masukStart}"/></div>
            <div><label>Masuk s/d</label><input type="time" id="fx_end" value="${c.flexi.masukEnd}"/></div>
            <div><label>Kompensasi Sen–Kam (pulang &gt;)</label><input type="time" id="fx_sk" value="${c.flexi.kompensasiSenKam}"/></div>
            <div><label>Kompensasi Jumat (pulang &gt;)</label><input type="time" id="fx_jm" value="${c.flexi.kompensasiJumat}"/></div>
          </div>
          <p class="muted">Jika masuk 07:31–08:00 dan pulang melebihi batas kompensasi, keterlambatan tidak dipotong.</p>
        </div>
      </div>

      <div class="ctab-body hidden" id="tab-potongan">
        <div class="card">
          <h3>Tarif Keterlambatan</h3>${tierTable('ket')}
        </div>
        <div class="card">
          <h3>Tarif Pulang Cepat</h3>${tierTable('psw')}
        </div>
        <div class="card">
          <h3>Durasi Aktual (Wali Asuh/Asrama/Satpam)</h3>
          <div class="form-row"><div><label>Minimum Durasi (jam)</label><input type="number" step="0.5" id="minDur" value="${c.minDurasiJam}"/></div></div>
          <ul class="rule-list">
            <li>≥ 7,5 jam = 0%</li><li>Kurang ≤30 mnt = 0,5%</li><li>Kurang ≤1 jam = 1%</li>
            <li>Kurang ≤1,5 jam = 1,5%</li><li>Kurang ≤2 jam = 2%</li><li>≤5 jam = 3%</li>
          </ul>
        </div>
        <div class="card">
          <h3>Lainnya</h3>
          <div class="form-row">
            <div><label>Potongan Absensi Tidak Lengkap (%)</label><input type="number" step="0.5" id="potTL" value="${c.potonganTidakLengkap}"/></div>
            <div><label>Potongan per Hari Kurang (%)</label><input type="number" step="0.5" id="potHK" value="${c.potonganHariKurangPerHari}"/></div>
          </div>
          <label>Jenis absensi bebas potongan (pisah koma)</label>
          <input type="text" id="jenisNo" value="${U.esc(c.jenisNoPotongan.join(', '))}" data-testid="jenis-no"/>
        </div>
      </div>

      <div class="ctab-body hidden" id="tab-zona">
        <div class="card">
          <h3>Zona Waktu</h3>
          <p class="muted">Zona dideteksi otomatis dari Provinsi. Data sumber tidak ditimpa — jam normalisasi disimpan di kolom terpisah.</p>
          <p>Mode waktu dipilih saat Hitung Harian: <b>Original</b> (tanpa normalisasi), <b>Normalisasi WIB - Kurangi</b> (kurangi jam WITA/WIT ke WIB), atau <b>Normalisasi WIB - Tambah</b> (tambah jam WIT/WITA sebagai WIB).</p>
        </div>
        <div class="card">
          <h3>Periode Cuti / Sakit</h3>
          <div class="form-row">
            <input type="file" id="leaveImportFile" accept=".xlsx,.xls,.csv" hidden />
            <button class="btn btn-secondary" id="importLeave" type="button"><i data-lucide="upload"></i> Import Periode Cuti / Sakit</button>
            <span class="muted">Kolom: NIP, Nama, Jenis, Mulai, Selesai</span>
          </div>
          <div class="form-row">
            <div><label>NIP</label><input type="text" id="lvNip" data-testid="leave-nip"/></div>
            <div><label>Nama</label><input type="text" id="lvNama"/></div>
            <div><label>Jenis</label><input type="text" id="lvJenis" placeholder="Cuti Melahirkan"/></div>
            <div><label>Mulai</label><input type="date" id="lvMulai"/></div>
            <div><label>Selesai</label><input type="date" id="lvSelesai"/></div>
            <div style="align-self:flex-end"><button class="btn btn-secondary" id="addLeave" data-testid="add-leave">+ Tambah</button></div>
          </div>
          <div class="table-wrap"><table class="data-table"><thead><tr><th>NIP</th><th>Nama</th><th>Jenis</th><th>Mulai</th><th>Selesai</th><th></th></tr></thead>
          <tbody id="lvBody">${leaveRows()}</tbody></table></div>
        </div>
      </div>

      <div class="actions-row">
        <button class="btn btn-ghost" id="backBtn"><i data-lucide="arrow-left"></i> Kembali</button>
        <button class="btn btn-primary" id="saveConfig" data-testid="save-config"><i data-lucide="save"></i> Simpan & Selesaikan Konfigurasi</button>
      </div>
      <div id="cfgMsg"></div>
    `;
    bind(el);
  };

  EVKIN.masterSdmMod = {
    render: function (el) {
      const list = EVKIN.getMasterPegawaiList ? EVKIN.getMasterPegawaiList() : (S.config.masterPegawai || []);
      const query = (el.__masterSdmQuery || '').trim().toLowerCase();
      const filtered = list.filter((p) => !query || [p.nip, p.nama, p.jabatan].some((v) => String(v || '').toLowerCase().includes(query)));
      const rows = filtered.map((p) => {
        const sourceIdx = list.findIndex((row) => String(row.nip).trim() === String(p.nip).trim() && String(row.nama).trim() === String(p.nama).trim() && String(row.jabatan).trim() === String(p.jabatan).trim());
        return `
        <tr>
          <td>${U.esc(p.nip)}</td>
          <td>${U.esc(p.nama)}</td>
          <td>${U.esc(p.jabatan)}</td>
          <td>${U.fmtRupiah(p.tukin)}</td>
          <td>
            <button class="btn btn-ghost" data-edit-sdm="${sourceIdx >= 0 ? sourceIdx : 0}">Edit</button>
            <button class="link-del" data-del-sdm="${sourceIdx >= 0 ? sourceIdx : 0}">Hapus</button>
          </td>
        </tr>`;
      }).join('') || '<tr><td colspan="5" class="muted">Belum ada data master SDM.</td></tr>';

      el.innerHTML = `
        <div class="module-head">
          <div>
            <h2>Master SDM</h2>
            <p class="muted">Database master SDM terintegrasi dengan workflow EVKIN.</p>
          </div>
          <div>${badge('master-sdm')}</div>
        </div>

        <div class="card">
          <div class="form-row" style="justify-content:space-between; align-items:center;">
            <h3 style="margin:0;">Master SDM (NIP, Nama, Jabatan, Tukin Bruto)</h3>
            <span class="pill ${EVKIN.exportBackend && EVKIN.exportBackend.enabled ? 'green' : 'gray'}">${EVKIN.exportBackend && EVKIN.exportBackend.enabled ? 'Auto-sync aktif' : 'Auto-sync nonaktif'}</span>
          </div>
          <p class="muted">Data SDM ini tersimpan di DuckDB master database dan dipakai secara langsung di workflow final, rekap, dan export Excel.</p>

          <div class="form-row">
            <input type="file" id="masterSdmFile" accept=".xlsx,.xls,.csv" hidden />
            <button class="btn btn-secondary" id="masterSdmPick" type="button"><i data-lucide="upload"></i> Unggah Master SDM</button>
            <button class="btn btn-ghost" id="masterSdmReset" type="button">Reset Master SDM</button>
          </div>

          <div class="form-row" style="margin-top:12px;">
            <div style="flex: 2;"><label>Cari SDM</label><input type="search" id="masterSdmSearch" value="${U.esc(el.__masterSdmQuery || '')}" placeholder="Cari NIP / nama / jabatan" /></div>
            <div><label>NIP</label><input type="text" id="masterSdmNip" /></div>
            <div><label>Nama</label><input type="text" id="masterSdmNama" /></div>
            <div><label>Jabatan</label><input type="text" id="masterSdmJabatan" /></div>
            <div><label>Tukin Bruto</label><input type="number" id="masterSdmTukin" min="0" /></div>
            <div style="align-self:flex-end"><button class="btn btn-primary" id="masterSdmSave" type="button">Simpan</button></div>
          </div>

          <div class="table-wrap" style="margin-top:12px;max-height:360px;overflow:auto">
            <table class="data-table">
              <thead><tr><th>NIP</th><th>Nama</th><th>Jabatan</th><th>Tukin Bruto</th><th>Aksi</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      `;

      const persistMasterPegawai = (list) => {
        S.config.masterPegawai = list;
        const syncNow = async () => {
          try {
            if (EVKIN.exportBackend && EVKIN.exportBackend.enabled) {
              const response = await fetch(new URL('/api/master-sdm', EVKIN.exportBackend.apiBase).toString(), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rows: list })
              });
              if (response.ok) {
                if (typeof EVKIN.syncBackendWorkflow === 'function') {
                  await EVKIN.syncBackendWorkflow().catch(() => {});
                }
                return;
              }
            }
            if (EVKIN.syncMasterDatabase) {
              await EVKIN.syncMasterDatabase(list).catch((err) => console.warn('Gagal sinkron master SDM ke database master:', err));
            } else if (EVKIN.saveMasterPegawaiToBackend) {
              await EVKIN.saveMasterPegawaiToBackend(list).catch((err) => console.warn('Gagal simpan master SDM ke database master:', err));
            } else {
              EVKIN.save();
            }
          } catch (err) {
            console.warn('Persist master SDM gagal:', err);
          }
        };
        syncNow();
      };

      const rerender = () => {
        el.__masterSdmQuery = el.__masterSdmQuery || '';
        EVKIN.masterSdmMod.render(el);
      };

      function buildPegawaiWorker(aoa, onReady) {
        const source = `
          self.onmessage = function (event) {
            const { aoa } = event.data || {};
            try {
              if (!aoa || aoa.length < 2) {
                self.postMessage({ error: 'File SDM kosong' });
                return;
              }
              const headers = aoa[0].map(x => String(x).trim());
              const idx = {};
              headers.forEach((h, i) => {
                const n = String(h).toLowerCase().replace(/[^a-z0-9]/g, '');
                if (['nip'].includes(n)) idx.nip = i;
                else if (['nama', 'namapegawai'].includes(n)) idx.nama = i;
                else if (['jabatan', 'posisi'].includes(n)) idx.jabatan = i;
                else if (['tukin', 'tukinbruto', 'tunjangankinerja', 'bruto'].includes(n)) idx.tukin = i;
              });
              if (idx.nip === undefined) {
                self.postMessage({ error: 'Kolom NIP tidak ditemukan' });
                return;
              }
              const list = [];
              aoa.slice(1).forEach((r) => {
                const nip = String(r[idx.nip] || '').trim();
                if (!nip) return;
                list.push({
                  nip,
                  nama: idx.nama !== undefined ? String(r[idx.nama] || '').trim() : '',
                  jabatan: idx.jabatan !== undefined ? String(r[idx.jabatan] || '').trim() : '',
                  tukin: idx.tukin !== undefined ? (parseFloat(String(r[idx.tukin]).replace(/[^0-9.-]/g, '')) || 0) : 0
                });
              });
              self.postMessage({ list });
            } catch (error) {
              self.postMessage({ error: error.message || 'Gagal memproses master SDM' });
            }
          };
        `;
        const blob = new Blob([source], { type: 'application/javascript' });
        const worker = new Worker(URL.createObjectURL(blob));
        worker.onmessage = (event) => {
          const { error, list } = event.data || {};
          URL.revokeObjectURL(worker._url || '');
          worker.terminate();
          if (error) return onReady(new Error(error));
          onReady(null, list);
        };
        worker.onerror = () => {
          worker.terminate();
          onReady(new Error('Worker master SDM gagal diproses'));
        };
        worker._url = URL.createObjectURL(blob);
        worker.postMessage({ aoa });
      }

      const parseFile = (file) => {
        const reader = new FileReader();
        reader.onload = (evt) => {
          try {
            let aoa = [];
            const buffer = evt.target.result;
            const ext = file.name.split('.').pop().toLowerCase();
            if (ext === 'csv') {
              const text = new TextDecoder('utf-8').decode(buffer);
              aoa = U.csvToAoa ? U.csvToAoa(text) : text.trim() ? text.split(/\r?\n/).map(r => r.split(',')) : [];
            } else {
              const wb = XLSX.read(buffer, { type: 'array' });
              const sheet = wb.Sheets[wb.SheetNames[0]];
              aoa = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: false, defval: '' });
            }
            buildPegawaiWorker(aoa, (err, list) => {
              if (err) return EVKIN.toast(err.message || 'Gagal parsing master SDM', 'error');
              persistMasterPegawai(list);
              EVKIN.toast('Master SDM berhasil diimport', 'success');
              rerender();
            });
          } catch (error) {
            EVKIN.toast(error.message || 'Gagal membaca file master SDM', 'error');
          }
        };
        reader.readAsArrayBuffer(file);
      };

      const pf = el.querySelector('#masterSdmFile');
      el.querySelector('#masterSdmPick').onclick = () => pf.click();
      pf.onchange = () => {
        const file = pf.files && pf.files[0];
        if (file) parseFile(file);
        pf.value = '';
      };

      const searchInput = el.querySelector('#masterSdmSearch');
      if (searchInput) {
        searchInput.oninput = () => {
          el.__masterSdmQuery = searchInput.value || '';
          rerender();
        };
      }

      el.querySelector('#masterSdmReset').onclick = () => {
        persistMasterPegawai([]);
        EVKIN.toast('Master SDM di-reset', 'info');
        rerender();
      };

      el.querySelector('#masterSdmSave').onclick = () => {
        const nip = (el.querySelector('#masterSdmNip').value || '').trim();
        const nama = (el.querySelector('#masterSdmNama').value || '').trim();
        const jabatan = (el.querySelector('#masterSdmJabatan').value || '').trim();
        const tukin = Number(el.querySelector('#masterSdmTukin').value || 0);
        if (!nip) return EVKIN.toast('NIP wajib diisi', 'error');
        const list = [...(S.config.masterPegawai || [])];
        const idx = list.findIndex((p) => String(p.nip).trim() === nip);
        if (idx >= 0) {
          list[idx] = { nip, nama: nama || list[idx].nama, jabatan: jabatan || list[idx].jabatan, tukin: Number.isFinite(tukin) ? tukin : list[idx].tukin };
        } else {
          list.push({ nip, nama, jabatan, tukin: Number.isFinite(tukin) ? tukin : 0 });
        }
        persistMasterPegawai(list);
        EVKIN.toast('Master SDM berhasil disimpan', 'success');
        rerender();
      };

      el.addEventListener('click', (e) => {
        const edit = e.target.closest('[data-edit-sdm]');
        if (edit) {
          const idx = Number(edit.dataset.editSdm);
          const row = (S.config.masterPegawai || [])[idx];
          if (!row) return;
          el.querySelector('#masterSdmNip').value = row.nip || '';
          el.querySelector('#masterSdmNama').value = row.nama || '';
          el.querySelector('#masterSdmJabatan').value = row.jabatan || '';
          el.querySelector('#masterSdmTukin').value = row.tukin || 0;
          el.querySelector('#masterSdmNip').focus();
          return;
        }

        const del = e.target.closest('[data-del-sdm]');
        if (del) {
          const idx = Number(del.dataset.delSdm);
          const list = [...(S.config.masterPegawai || [])];
          list.splice(idx, 1);
          persistMasterPegawai(list);
          EVKIN.toast('Data master SDM dihapus', 'info');
          rerender();
        }
      });

      if (window.lucide) lucide.createIcons();
    }
  };

  function badge(step) {
    if (EVKIN.stepDone(step)) return '<span class="pill green">✓ Selesai</span>';
    return '<span class="pill gray">Belum disimpan</span>';
  }
  function holRows() {
    const holidays = Array.isArray(S.config && S.config.holidays) ? S.config.holidays : [];
    return holidays.slice().sort((a, b) => a.d < b.d ? -1 : 1).map((h, i) =>
      `<tr><td>${U.esc(h.d)}</td><td>${U.esc(h.n)}</td><td><button class="link-del" data-del-hol="${h.d}">Hapus</button></td></tr>`).join('');
  }
  function jabRows() {
    const jabatanMaster = Array.isArray(S.config && S.config.jabatanMaster) ? S.config.jabatanMaster : [];
    return jabatanMaster.map((j, i) =>
      `<tr><td>${U.esc(j.nama)}</td><td><span class="pill ${j.metode === 'durasi' ? 'blue' : 'gray'}">${j.metode === 'durasi' ? 'Durasi Aktual' : 'Reguler'}</span></td>
      <td><button class="link-del" data-del-jab="${i}">Hapus</button></td></tr>`).join('');
  }
  function leaveRows() {
    const leavePeriods = Array.isArray(S.config && S.config.leavePeriods) ? S.config.leavePeriods : [];
    return leavePeriods.map(l =>
      `<tr><td>${U.esc(l.nip)}</td><td>${U.esc(l.nama)}</td><td>${U.esc(l.jenis)}</td><td>${U.esc(l.mulai)}</td><td>${U.esc(l.selesai)}</td>
      <td><button class="link-del" data-del-lv="${l.id}">Hapus</button></td></tr>`).join('') ||
      '<tr><td colspan="6" class="muted">Belum ada periode cuti/sakit.</td></tr>';
  }
  function pegRows() {
    const masterPegawai = Array.isArray(S.config && S.config.masterPegawai) ? S.config.masterPegawai : [];
    return masterPegawai.map((p, i) =>
      `<tr>
        <td>${U.esc(p.nip)}</td>
        <td>${U.esc(p.nama)}</td>
        <td>${U.esc(p.jabatan)}</td>
        <td>${U.fmtRupiah(p.tukin)}</td>
        <td>
          <button class="btn btn-ghost" data-edit-peg="${i}">Edit</button>
          <button class="link-del" data-del-peg="${i}">Hapus</button>
        </td>
      </tr>`).join('') ||
      '<tr><td colspan="5" class="muted">Belum ada data master pegawai.</td></tr>';
  }
  function tierTable(kind) {
    const tiers = kind === 'ket' ? (Array.isArray(S.config && S.config.keterlambatanTiers) ? S.config.keterlambatanTiers : []) : (Array.isArray(S.config && S.config.pulangCepatTiers) ? S.config.pulangCepatTiers : []);
    const rows = tiers.map((t, i) =>
      `<tr><td><input type="number" data-tier="${kind}" data-idx="${i}" data-f="max" value="${t.max}"/></td>
       <td><input type="number" step="0.25" data-tier="${kind}" data-idx="${i}" data-f="pct" value="${t.pct}"/></td></tr>`).join('');
    return `<table class="data-table tier"><thead><tr><th>Sampai (menit)</th><th>Potongan (%)</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function bind(el) {
    // tabs
   let isDirty = false;
   const setDirty = () => { isDirty = true; };

   el.querySelectorAll('.ctab').forEach(b => b.onclick = () => {
     el.querySelectorAll('.ctab').forEach(x => x.classList.remove('active'));
     b.classList.add('active');
     el.querySelectorAll('.ctab-body').forEach(x => x.classList.add('hidden'));
     el.querySelector('#tab-' + b.dataset.tab).classList.remove('hidden');
     if (window.lucide) lucide.createIcons();
   });

    function persistMasterPegawai(list) {
      S.config.masterPegawai = list;
      if (EVKIN.saveMasterPegawaiToBackend) {
        EVKIN.saveMasterPegawaiToBackend(list).catch((err) => console.warn('Gagal simpan master pegawai ke database master:', err));
      } else {
        EVKIN.save();
      }
    }

    function buildPegawaiWorker(aoa, onReady) {
      const source = `
        self.onmessage = function (event) {
          const { aoa } = event.data || {};
          try {
            if (!aoa || aoa.length < 2) {
              self.postMessage({ error: 'File pegawai kosong' });
              return;
            }
            const headers = aoa[0].map(x => String(x).trim());
            const idx = {};
            headers.forEach((h, i) => {
              const n = String(h).toLowerCase().replace(/[^a-z0-9]/g, '');
              if (['nip'].includes(n)) idx.nip = i;
              else if (['nama', 'namapegawai'].includes(n)) idx.nama = i;
              else if (['jabatan', 'posisi'].includes(n)) idx.jabatan = i;
              else if (['tukin', 'tukinbruto', 'tunjangankinerja', 'bruto'].includes(n)) idx.tukin = i;
            });
            if (idx.nip === undefined) {
              self.postMessage({ error: 'Kolom NIP tidak ditemukan' });
              return;
            }
            const list = [];
            aoa.slice(1).forEach((r) => {
              const nip = String(r[idx.nip] || '').trim();
              if (!nip) return;
              list.push({
                nip,
                nama: idx.nama !== undefined ? String(r[idx.nama] || '').trim() : '',
                jabatan: idx.jabatan !== undefined ? String(r[idx.jabatan] || '').trim() : '',
                tukin: idx.tukin !== undefined ? (parseFloat(String(r[idx.tukin]).replace(/[^0-9.-]/g, '')) || 0) : 0
              });
            });
            self.postMessage({ list });
          } catch (error) {
            self.postMessage({ error: error.message || 'Gagal memproses master pegawai' });
          }
        };
      `;
      const blob = new Blob([source], { type: 'application/javascript' });
      const worker = new Worker(URL.createObjectURL(blob));
      worker.onmessage = (event) => {
        const { error, list } = event.data || {};
        URL.revokeObjectURL(worker._url || '');
        worker.terminate();
        if (error) return onReady(new Error(error));
        onReady(null, list);
      };
      worker.onerror = () => {
        worker.terminate();
        onReady(new Error('Worker master pegawai gagal diproses'));
      };
      worker._url = URL.createObjectURL(blob);
      worker.postMessage({ aoa });
    }

    el.querySelectorAll('[name=effMode]').forEach(r => r.onchange = () => S.config.effectiveDaysMode = el.querySelector('[name=effMode]:checked').value);
    const effMonth = el.querySelector('#effMonth');
    if (effMonth) effMonth.onchange = () => { S.month = effMonth.value; el.querySelector('#effAuto').value = mod.effectiveAuto(S.month); };

    el.querySelector('#addHol').onclick = () => {
      const d = el.querySelector('#holDate').value, n = el.querySelector('#holName').value.trim();
      if (!d) return EVKIN.toast('Isi tanggal libur', 'error');
      if (!S.config.holidays.some(h => h.d === d)) S.config.holidays.push({ d, n: n || 'Libur' });
      setDirty();
      rerender();
    };
    el.querySelector('#addJab').onclick = () => {
      const nm = el.querySelector('#jabName').value.trim(); const mt = el.querySelector('#jabMethod').value;
      if (!nm) return EVKIN.toast('Isi nama jabatan', 'error');
      S.config.jabatanMaster.push({ nama: nm, metode: mt });
      setDirty();
      rerender();
    };
    el.querySelector('#addLeave').onclick = () => {
      const lp = {
        id: U.uid(), nip: el.querySelector('#lvNip').value.trim(), nama: el.querySelector('#lvNama').value.trim(),
        jenis: el.querySelector('#lvJenis').value.trim() || 'Cuti', mulai: el.querySelector('#lvMulai').value, selesai: el.querySelector('#lvSelesai').value
      };
      if (!lp.nip || !lp.mulai || !lp.selesai) return EVKIN.toast('NIP, tanggal mulai & selesai wajib', 'error');
      if (lp.mulai > lp.selesai) return EVKIN.toast('Tanggal mulai tidak boleh lebih besar dari selesai', 'error');
      const overlap = S.config.leavePeriods.some(existing =>
        existing.nip === lp.nip &&
        !(lp.selesai < existing.mulai || lp.mulai > existing.selesai)
      );
      if (overlap) return EVKIN.toast('Periode cuti/sakit sudah ada untuk NIP ini (terjadi overlap)', 'error');
      S.config.leavePeriods.push(lp);
      setDirty();
      rerender();
    };

    const leaveImportFile = el.querySelector('#leaveImportFile');
    const normalizeLeaveHeader = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    const leaveColumn = (headers, aliases) => headers.findIndex((header) => aliases.includes(normalizeLeaveHeader(header)));
    const parseLeaveDate = (value) => {
      const parsed = U.parseDate(value);
      return parsed ? parsed.key : '';
    };
    const importLeavePeriods = (file) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const buffer = event.target.result;
          const extension = file.name.split('.').pop().toLowerCase();
          let matrix;
          if (extension === 'csv') {
            const text = new TextDecoder('utf-8').decode(buffer);
            matrix = U.csvToAoa ? U.csvToAoa(text) : text.trim().split(/\r?\n/).map(row => row.split(','));
          } else {
            const workbook = XLSX.read(buffer, { type: 'array', raw: false });
            const sheet = workbook.Sheets[workbook.SheetNames[0]];
            matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: false, defval: '' });
          }
          if (!matrix || matrix.length < 2) throw new Error('File periode cuti/sakit kosong');
          const headers = matrix[0];
          const indexes = {
            nip: leaveColumn(headers, ['nip', 'nomorpegawai', 'nomorindukpegawai']),
            nama: leaveColumn(headers, ['nama', 'namapegawai']),
            jenis: leaveColumn(headers, ['jenis', 'jeniscuti', 'keterangan', 'status']),
            mulai: leaveColumn(headers, ['mulai', 'tanggalmulai', 'tglmulai', 'start', 'startdate']),
            selesai: leaveColumn(headers, ['selesai', 'tanggalselesai', 'tglselesai', 'end', 'enddate'])
          };
          if (indexes.nip < 0 || indexes.mulai < 0 || indexes.selesai < 0) {
            throw new Error('Kolom wajib NIP, Mulai, dan Selesai tidak ditemukan');
          }

          let imported = 0;
          let skipped = 0;
          const errors = [];
          matrix.slice(1).forEach((row, rowIndex) => {
            const nip = String(row[indexes.nip] || '').trim();
            const mulai = parseLeaveDate(row[indexes.mulai]);
            const selesai = parseLeaveDate(row[indexes.selesai]);
            const jenis = indexes.jenis >= 0 ? String(row[indexes.jenis] || '').trim() : 'Cuti';
            if (!nip || !mulai || !selesai || mulai > selesai) {
              skipped++;
              errors.push(`baris ${rowIndex + 2}: NIP/tanggal tidak valid`);
              return;
            }
            const duplicate = S.config.leavePeriods.some(existing =>
              String(existing.nip).trim() === nip &&
              !(selesai < existing.mulai || mulai > existing.selesai)
            );
            if (duplicate) {
              skipped++;
              errors.push(`baris ${rowIndex + 2}: periode NIP ${nip} overlap`);
              return;
            }
            S.config.leavePeriods.push({
              id: U.uid(),
              nip,
              nama: indexes.nama >= 0 ? String(row[indexes.nama] || '').trim() : '',
              jenis: jenis || 'Cuti',
              mulai,
              selesai
            });
            imported++;
          });
          setDirty();
          rerender();
          const detail = errors.length ? ` ${errors.slice(0, 3).join('; ')}` : '';
          EVKIN.toast(`Import selesai: ${imported} berhasil, ${skipped} dilewati.${detail}`, skipped ? 'warn' : 'success');
        } catch (error) {
          EVKIN.toast(error.message || 'Gagal membaca import periode cuti/sakit', 'error');
        }
      };
      reader.onerror = () => EVKIN.toast('Gagal membaca file periode cuti/sakit', 'error');
      reader.readAsArrayBuffer(file);
    };
    el.querySelector('#importLeave').onclick = () => leaveImportFile.click();
    leaveImportFile.onchange = () => {
      const file = leaveImportFile.files && leaveImportFile.files[0];
      if (file) importLeavePeriods(file);
      leaveImportFile.value = '';
    };

    el.addEventListener('click', (e) => {
      const t = e.target;
      if (t.dataset.delHol) { S.config.holidays = S.config.holidays.filter(h => h.d !== t.dataset.delHol); setDirty(); rerender(); }
      if (t.dataset.delJab !== undefined && t.dataset.delJab !== '') { S.config.jabatanMaster.splice(+t.dataset.delJab, 1); setDirty(); rerender(); }
      if (t.dataset.delLv) { S.config.leavePeriods = S.config.leavePeriods.filter(l => l.id !== t.dataset.delLv); setDirty(); rerender(); }
    });

    // Back button with unsaved warning
    const backBtn = el.querySelector('#backBtn');
    if (backBtn) {
      backBtn.onclick = () => {
        if (isDirty) {
          if (!confirm('Ada perubahan yang belum disimpan. Yakin ingin kembali tanpa menyimpan?')) return;
        }
        EVKIN.go('import');
      };
    }

    // Track form changes
    const trackFormChanges = () => { setDirty(); };
    el.querySelectorAll('input, select').forEach(field => {
      field.addEventListener('change', trackFormChanges);
      field.addEventListener('input', trackFormChanges);
    });

    el.querySelector('#saveConfig').onclick = () => { saveConfig(el); isDirty = false; };
  }

  function readFields(el) {
    const c = (S.config = EVKIN.normalizeConfig ? EVKIN.normalizeConfig(S.config) : (S.config || EVKIN.defaultConfig()));

    // Validasi jam dasar logic
    const skMasuk = el.querySelector('#sk_masuk').value;
    const skPulang = el.querySelector('#sk_pulang').value;
    const jmMasuk = el.querySelector('#jm_masuk').value;
    const jmPulang = el.querySelector('#jm_pulang').value;

    if (skMasuk && skPulang && skMasuk >= skPulang) throw new Error('Jam masuk Sen-Kam harus lebih awal dari pulang');
    if (jmMasuk && jmPulang && jmMasuk >= jmPulang) throw new Error('Jam masuk Jumat harus lebih awal dari pulang');

    // Validasi flexi time
    const fxEnabled = el.querySelector('#fxEnabled').checked;
    if (fxEnabled) {
      const fxStart = el.querySelector('#fx_start').value;
      const fxEnd = el.querySelector('#fx_end').value;
      if (fxStart && fxEnd && fxStart >= fxEnd) throw new Error('Flexi start harus lebih awal dari end');
    }

    c.effectiveDaysManual = +el.querySelector('#effManual').value || 0;
    c.jamDasar.senKam.masuk = skMasuk;
    c.jamDasar.senKam.pulang = skPulang;
    c.jamDasar.jumat.masuk = jmMasuk;
    c.jamDasar.jumat.pulang = jmPulang;
    c.flexi.enabled = fxEnabled;
    c.flexi.masukStart = el.querySelector('#fx_start').value;
    c.flexi.masukEnd = el.querySelector('#fx_end').value;
    c.flexi.kompensasiSenKam = el.querySelector('#fx_sk').value;
    c.flexi.kompensasiJumat = el.querySelector('#fx_jm').value;
    c.minDurasiJam = +el.querySelector('#minDur').value || 7.5;
    c.potonganTidakLengkap = +el.querySelector('#potTL').value || 0;
    c.potonganHariKurangPerHari = +el.querySelector('#potHK').value || 0;
    c.jenisNoPotongan = el.querySelector('#jenisNo').value.split(',').map(s => s.trim()).filter(Boolean);

    // Validasi tier potongan
    el.querySelectorAll('[data-tier]').forEach(inp => {
      const arr = inp.dataset.tier === 'ket' ? c.keterlambatanTiers : c.pulangCepatTiers;
      const val = +inp.value;
      if (val < 0) throw new Error('Potongan tidak boleh negative');
      arr[+inp.dataset.idx][inp.dataset.f] = val;
    });
  }

  function rerender() { readFieldsSafe(); EVKIN.save(); EVKIN.go('config'); }
  function readFieldsSafe() { try { readFields(document.querySelector('#main')); } catch (e) { } }

  async function saveConfig(el) {
    try {
      readFields(el);
      S.config.saved = true;
      EVKIN.invalidateFrom('config', {save:false});
      await EVKIN.syncBackendWorkflow(undefined, {derivedOnly:true});
      EVKIN.toast('Konfigurasi disimpan');
      EVKIN.go('harian');
    } catch (err) {
      EVKIN.toast('Error validasi: ' + err.message, 'error');
    }
  }

  function uploadPegawai(file, el, setDirty) {
    EVKIN.importMod.handleFile(file, (err, aoa) => {
      if (err) return EVKIN.toast(err.message, 'error');
      if (!aoa || aoa.length < 2) return EVKIN.toast('File pegawai kosong', 'error');

      const pegMsg = el.querySelector('#pegMsg');
      if (pegMsg) pegMsg.textContent = 'Memproses master pegawai di worker...';

      const worker = new Worker(URL.createObjectURL(new Blob([`
        self.onmessage = function (event) {
          const { aoa } = event.data || {};
          try {
            const headers = aoa[0].map(x => String(x).trim());
            const idx = {};
            headers.forEach((h, i) => {
              const n = String(h).toLowerCase().replace(/[^a-z0-9]/g, '');
              if (['nip'].includes(n)) idx.nip = i;
              else if (['nama', 'namapegawai'].includes(n)) idx.nama = i;
              else if (['provinsi', 'prov', 'propinsi'].includes(n)) idx.provinsi = i;
              else if (['kabupatenkota', 'kabupaten', 'kabkot', 'kota'].includes(n)) idx.kabupatenKota = i;
              else if (['kdanaksatker', 'kodeanaksatker', 'anaksatker'].includes(n)) idx.kdAnakSatker = i;
              else if (['jabatanosdm', 'jabatanosdm'].includes(n)) idx.jabatanOsdm = i;
              else if (['statustendik', 'status_tendik'].includes(n)) idx.statusTendik = i;
              else if (['jabatan', 'posisi'].includes(n)) idx.jabatan = i;
              else if (['tukin', 'tukinbruto', 'tunjangankinerja', 'bruto'].includes(n)) idx.tukin = i;
            });
            if (idx.nip === undefined) {
              self.postMessage({ error: 'Kolom NIP tidak ditemukan' });
              return;
            }
            const list = [];
            aoa.slice(1).forEach((r) => {
              const nip = String(r[idx.nip] || '').trim();
              if (!nip) return;
              list.push({
                nip,
                nama: idx.nama !== undefined ? String(r[idx.nama] || '').trim() : '',
                provinsi: idx.provinsi !== undefined ? String(r[idx.provinsi] || '').trim() : '',
                kabupatenKota: idx.kabupatenKota !== undefined ? String(r[idx.kabupatenKota] || '').trim() : '',
                kdAnakSatker: idx.kdAnakSatker !== undefined ? String(r[idx.kdAnakSatker] || '').trim() : '',
                jabatanOsdm: idx.jabatanOsdm !== undefined ? String(r[idx.jabatanOsdm] || '').trim() : '',
                statusTendik: idx.statusTendik !== undefined ? String(r[idx.statusTendik] || '').trim() : '',
                jabatan: idx.jabatan !== undefined ? String(r[idx.jabatan] || '').trim() : '',
                tukin: idx.tukin !== undefined ? (parseFloat(String(r[idx.tukin]).replace(/[^0-9.-]/g, '')) || 0) : 0
              });
            });
            self.postMessage({ list });
          } catch (error) {
            self.postMessage({ error: error.message || 'Gagal memproses master pegawai' });
          }
        };
      `], { type: 'application/javascript' })));
      worker.onmessage = async (msg) => {
        const { error, list } = msg.data || {};
        worker.terminate();
        if (error) {
          if (pegMsg) pegMsg.textContent = error;
          return EVKIN.toast(error, 'error');
        }
        S.config.masterPegawai = list;
        try {
          if (EVKIN.saveMasterPegawaiToBackend) {
            await EVKIN.saveMasterPegawaiToBackend(list);
          } else {
            EVKIN.save();
          }
        } catch (saveError) {
          if (pegMsg) pegMsg.textContent = 'Gagal menyimpan master SDM: ' + saveError.message;
          return EVKIN.toast('Gagal menyimpan master SDM: ' + saveError.message, 'error');
        }
        if (setDirty) setDirty();
        EVKIN.toast('Master pegawai: ' + list.length + ' pegawai dimuat');
        if (pegMsg) pegMsg.textContent = 'Master pegawai berhasil dimuat';
        EVKIN.go('config');
      };
      worker.onerror = () => {
        worker.terminate();
        if (pegMsg) pegMsg.textContent = 'Worker gagal memproses file master pegawai';
        EVKIN.toast('Worker gagal memproses file master pegawai', 'error');
      };
      worker.postMessage({ aoa });
    });
  }

  // Override masterSdmMod.render to use server-side pagination/search
  EVKIN.masterSdmMod = EVKIN.masterSdmMod || {};
  EVKIN.masterSdmMod.render = function (el) {
    el.__masterSdmQuery = el.__masterSdmQuery || '';
    el.__masterSdmPage = el.__masterSdmPage || 1;
    el.__masterSdmPerPage = el.__masterSdmPerPage || 25;

    let apiBase = (EVKIN.exportBackend && EVKIN.exportBackend.apiBase)
      ? EVKIN.exportBackend.apiBase
      : 'http://127.0.0.1:8000';

    const ensureBackend = async () => {
      if (!EVKIN.exportBackend) {
        throw new Error('Backend EVKIN belum tersedia. Jalankan START_EVKIN_TOOLS_HTTP.bat.');
      }
      if (!EVKIN.exportBackend.enabled && typeof EVKIN.exportBackend.activate === 'function') {
        try {
          apiBase = await EVKIN.exportBackend.activate(apiBase);
        } catch (error) {
          throw new Error('Backend belum berjalan. Jalankan START_EVKIN_TOOLS_HTTP.bat lalu coba lagi.');
        }
      }
      return apiBase;
    };

    const fetchPage = async (q, page, per_page) => {
      await ensureBackend();
      const url = new URL('/api/master-sdm', apiBase);
      if (q) url.searchParams.set('q', q);
      url.searchParams.set('page', String(page));
      url.searchParams.set('per_page', String(per_page));
      const resp = await fetch(url.toString(), { method: 'GET', cache: 'no-store' });
      if (!resp.ok) throw new Error('Gagal mengambil data master SDM: ' + resp.status);
      return resp.json();
    };

    const fetchAll = async () => {
      const per = 1000;
      const first = await fetchPage('', 1, per);
      let rows = first.rows || [];
      const total_pages = first.total_pages || 1;
      for (let p = 2; p <= total_pages; p++) {
        const part = await fetchPage('', p, per);
        rows = rows.concat(part.rows || []);
      }
      return rows;
    };

    const persistMasterPegawai = async (list) => {
      try {
        const url = new URL('/api/master-sdm', apiBase).toString();
        const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: list }) });
        if (!resp.ok) throw new Error('Gagal menyimpan master SDM ke backend');
        EVKIN.toast('Master SDM tersimpan di backend', 'success');
        // refresh view
        await loadPage(el.__masterSdmPage);
      } catch (err) {
        console.warn(err);
        EVKIN.toast('Gagal menyimpan master SDM: ' + err.message, 'error');
      }
    };

    const makeRowsHtml = (rows) => {
      if (!rows || !rows.length) return '<tr><td colspan="10" class="muted">Belum ada data master SDM.</td></tr>';
      return rows.map((p) => `
        <tr data-nip="${U.esc(p.nip)}">
          <td>${U.esc(p.nip)}</td>
          <td>${U.esc(p.nama)}</td>
          <td>${U.esc(p.provinsi || '')}</td>
          <td>${U.esc(p.kabupatenKota || p.kabupaten || '')}</td>
          <td>${U.esc(p.kdAnakSatker || p.kd_anaksatker || '')}</td>
          <td>${U.esc(p.jabatanOsdm || p.jabatan_osdm || '')}</td>
          <td>${U.esc(p.statusTendik || p.status_tendik || '')}</td>
          <td>${U.esc(p.jabatan)}</td>
          <td>${U.fmtRupiah(p.tukin)}</td>
          <td>
            <button class="btn btn-ghost btn-edit" data-nip="${U.esc(p.nip)}">Edit</button>
            <button class="link-del btn-del" data-nip="${U.esc(p.nip)}">Hapus</button>
          </td>
        </tr>`).join('');
    };

    const renderSkeleton = () => {
      el.innerHTML = `
      <div class="module-head">
        <div>
          <h2>Master SDM</h2>
          <p class="muted">Database master SDM terintegrasi dengan workflow EVKIN.</p>
        </div>
        <div>${badge('master-sdm')}</div>
      </div>

      <div class="card">
        <div class="form-row" style="justify-content:space-between; align-items:center;">
          <h3 style="margin:0;">Master SDM (NIP, Nama, Jabatan, Tukin Bruto)</h3>
          <span class="pill ${EVKIN.exportBackend && EVKIN.exportBackend.enabled ? 'green' : 'gray'}">${EVKIN.exportBackend && EVKIN.exportBackend.enabled ? 'Auto-sync aktif' : 'Auto-sync nonaktif'}</span>
        </div>
        <p class="muted">Data SDM ini tersimpan di DuckDB master database dan dipakai secara langsung di workflow final, rekap, dan export Excel.</p>

        <div class="form-row">
          <input type="file" id="masterSdmFile" accept=".xlsx,.xls,.csv" hidden />
          <button class="btn btn-secondary" id="masterSdmPick" type="button"><i data-lucide="upload"></i> Unggah Master SDM</button>
          <button class="btn btn-ghost" id="masterSdmReset" type="button">Reset Master SDM</button>
        </div>

        <div class="form-row" style="margin-top:12px; flex-wrap:wrap;">
          <div style="flex: 2; min-width: 160px;"><label>Cari SDM</label><input type="search" id="masterSdmSearch" value="${U.esc(el.__masterSdmQuery || '')}" placeholder="Cari NIP / nama / jabatan" /></div>
          <div style="min-width: 140px;"><label>NIP</label><input type="text" id="masterSdmNip" /></div>
          <div style="min-width: 140px;"><label>Nama</label><input type="text" id="masterSdmNama" /></div>
          <div style="min-width: 180px;"><label>Provinsi</label><input type="text" id="masterSdmProvinsi" /></div>
          <div style="min-width: 180px;"><label>Kabupaten/Kota</label><input type="text" id="masterSdmKabupaten" /></div>
          <div style="min-width: 150px;"><label>KD AnakSatker</label><input type="text" id="masterSdmAnakSatker" /></div>
          <div style="min-width: 180px;"><label>Jabatan OSDM</label><input type="text" id="masterSdmJabatanOsdm" /></div>
          <div style="min-width: 180px;"><label>Status Tendik</label><input type="text" id="masterSdmStatusTendik" /></div>
          <div style="min-width: 180px;"><label>Jabatan</label><input type="text" id="masterSdmJabatan" /></div>
          <div style="min-width: 150px;"><label>Tukin Bruto</label><input type="number" id="masterSdmTukin" min="0" /></div>
          <div style="align-self:flex-end"><button class="btn btn-primary" id="masterSdmSave" type="button">Simpan</button></div>
        </div>

        <div class="table-wrap" style="margin-top:12px;max-height:360px;overflow:auto">
          <table class="data-table">
            <thead><tr><th>NIP</th><th>Nama</th><th>Provinsi</th><th>Kab/Kota</th><th>KD AnakSatker</th><th>Jabatan OSDM</th><th>Status Tendik</th><th>Jabatan</th><th>Tukin Bruto</th><th>Aksi</th></tr></thead>
            <tbody id="msBody"><tr><td colspan="10" class="muted">Memuat...</td></tr></tbody>
          </table>
        </div>

        <div class="form-row" style="justify-content:center; margin-top:8px;" id="msPager"></div>
      </div>`;
    };

    let searchTimer = null;
    const loadPage = async (page) => {
      el.__masterSdmPage = page || 1;
      const q = (el.__masterSdmQuery || '').trim();
      const per = el.__masterSdmPerPage || 25;
      const body = el.querySelector('#msBody');
      const pager = el.querySelector('#msPager');
      if (body) body.innerHTML = '<tr><td colspan="5">Memuat...</td></tr>';
      try {
        const json = await fetchPage(q, el.__masterSdmPage, per);
        const rows = json.rows || [];
        const count = json.count || 0;
        const total_pages = json.total_pages || 1;
        if (body) body.innerHTML = makeRowsHtml(rows);
        if (pager) {
          pager.innerHTML = '';
          const prev = document.createElement('button'); prev.className = 'btn btn-ghost'; prev.textContent = '← Prev'; prev.disabled = el.__masterSdmPage <= 1;
          prev.onclick = () => loadPage(el.__masterSdmPage - 1);
          const next = document.createElement('button'); next.className = 'btn btn-ghost'; next.textContent = 'Next →'; next.disabled = el.__masterSdmPage >= total_pages;
          next.onclick = () => loadPage(el.__masterSdmPage + 1);
          const info = document.createElement('div'); info.style.padding = '6px 12px'; info.textContent = `Halaman ${el.__masterSdmPage} / ${total_pages} — ${count} total`;
          pager.appendChild(prev);
          pager.appendChild(info);
          pager.appendChild(next);
        }
      } catch (err) {
        if (body) body.innerHTML = `<tr><td colspan="5" class="muted">Gagal memuat data: ${U.esc(err.message)}</td></tr>`;
      }
      bindActions();
    };

    const bindActions = () => {
      const pick = el.querySelector('#masterSdmPick');
      const pf = el.querySelector('#masterSdmFile');
      if (pick && pf) pick.onclick = () => pf.click();
      if (pf) pf.onchange = () => {
        const file = pf.files && pf.files[0];
        if (file) uploadPegawai(file, el, () => {});
        pf.value = '';
      };

      const resetBtn = el.querySelector('#masterSdmReset');
      if (resetBtn) resetBtn.onclick = () => {
        if (!confirm('Yakin mereset master SDM? Semua data akan dihapus dari backend.')) return;
        persistMasterPegawai([]);
      };

      const search = el.querySelector('#masterSdmSearch');
      if (search) {
        search.oninput = (e) => {
          el.__masterSdmQuery = search.value || '';
          clearTimeout(searchTimer);
          searchTimer = setTimeout(() => loadPage(1), 300);
        };
      }

      const saveBtn = el.querySelector('#masterSdmSave');
      if (saveBtn) saveBtn.onclick = async () => {
        const nip = (el.querySelector('#masterSdmNip').value || '').trim();
        const nama = (el.querySelector('#masterSdmNama').value || '').trim();
        const provinsi = (el.querySelector('#masterSdmProvinsi').value || '').trim();
        const kabupatenKota = (el.querySelector('#masterSdmKabupaten').value || '').trim();
        const kdAnakSatker = (el.querySelector('#masterSdmAnakSatker').value || '').trim();
        const jabatanOsdm = (el.querySelector('#masterSdmJabatanOsdm').value || '').trim();
        const statusTendik = (el.querySelector('#masterSdmStatusTendik').value || '').trim();
        const jabatan = (el.querySelector('#masterSdmJabatan').value || '').trim();
        const tukin = Number(el.querySelector('#masterSdmTukin').value || 0);
        if (!nip) return EVKIN.toast('NIP wajib diisi', 'error');
        const row = {
          nip,
          nama,
          provinsi,
          kabupatenKota,
          kdAnakSatker,
          jabatanOsdm,
          statusTendik,
          jabatan,
          tukin: Number.isFinite(tukin) ? tukin : 0
        };
        try {
          const url = new URL('/api/master-sdm/upsert', apiBase).toString();
          const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows: [row] }) });
          if (!resp.ok) throw new Error('Gagal menyimpan perubahan: ' + resp.status);
          EVKIN.toast('Perubahan pegawai tersimpan', 'success');
          await loadPage(el.__masterSdmPage);
          el.querySelector('#masterSdmNip').value = '';
          el.querySelector('#masterSdmNama').value = '';
          el.querySelector('#masterSdmProvinsi').value = '';
          el.querySelector('#masterSdmKabupaten').value = '';
          el.querySelector('#masterSdmAnakSatker').value = '';
          el.querySelector('#masterSdmJabatanOsdm').value = '';
          el.querySelector('#masterSdmStatusTendik').value = '';
          el.querySelector('#masterSdmJabatan').value = '';
          el.querySelector('#masterSdmTukin').value = '';
        } catch (err) {
          console.warn(err);
          EVKIN.toast('Gagal menyimpan pegawai: ' + err.message, 'error');
        }
      };

      el.querySelectorAll('.btn-edit').forEach(b => b.onclick = async (e) => {
        const nip = b.dataset.nip;
        const list = await fetchAll().catch(() => []);
        const row = list.find(p => String(p.nip) === String(nip));
        if (!row) return EVKIN.toast('Data tidak ditemukan', 'error');
        el.querySelector('#masterSdmNip').value = row.nip || '';
        el.querySelector('#masterSdmNama').value = row.nama || '';
        el.querySelector('#masterSdmProvinsi').value = row.provinsi || '';
        el.querySelector('#masterSdmKabupaten').value = row.kabupatenKota || row.kabupaten || '';
        el.querySelector('#masterSdmAnakSatker').value = row.kdAnakSatker || row.kd_anaksatker || '';
        el.querySelector('#masterSdmJabatanOsdm').value = row.jabatanOsdm || row.jabatan_osdm || '';
        el.querySelector('#masterSdmStatusTendik').value = row.statusTendik || row.status_tendik || '';
        el.querySelector('#masterSdmJabatan').value = row.jabatan || '';
        el.querySelector('#masterSdmTukin').value = row.tukin || 0;
      });

      el.querySelectorAll('.btn-del').forEach(b => b.onclick = async (e) => {
        const nip = b.dataset.nip;
        if (!confirm('Hapus pegawai NIP ' + nip + '?')) return;
        try {
          const url = new URL('/api/master-sdm/delete', apiBase).toString();
          const resp = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nips: [nip] }) });
          if (!resp.ok) throw new Error('Gagal menghapus: ' + resp.status);
          EVKIN.toast('Pegawai dihapus', 'success');
          await loadPage(el.__masterSdmPage);
        } catch (err) {
          console.warn(err);
          // fallback to full replace if delete endpoint not available
          const list = await fetchAll().catch(() => []);
          const newList = list.filter(p => String(p.nip) !== String(nip));
          await persistMasterPegawai(newList);
        }
      });
    };

    renderSkeleton();
    loadPage(el.__masterSdmPage);
  };

})();
