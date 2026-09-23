/* EVKIN ABSENSI v3.1 - state.js
   State global dan gating workflow. Penyimpanan master dilakukan di DuckDB backend. */
(function () {
  const EVKIN = window.EVKIN || (window.EVKIN = {});
  const M = EVKIN.master;

  EVKIN.STEPS = [
    { id: 'dashboard', label: 'Dashboard', icon: 'gauge', always: true },
    { id: 'pembulatan', label: 'Pembulatan Desimal', icon: 'repeat', always: true, workflow: false },
    { id: 'import', label: 'Import Data', icon: 'upload', workflow: true },
    { id: 'config', label: 'Konfigurasi', icon: 'sliders', workflow: true },
    { id: 'master-sdm', label: 'Master SDM', icon: 'users', workflow: false },
    { id: 'skp-assessment', label: 'Penilaian SKP (Opsional)', icon: 'target', workflow: false },
    { id: 'master-pengembalian', label: 'Master Pengembalian', icon: 'repeat', workflow: false },
    { id: 'tukin-annual', label: 'Pengelolaan Tukin', icon: 'calendar-range', workflow: false },
    { id: 'reconcile', label: 'Rekonsiliasi', icon: 'clipboard-check', workflow: false },
    { id: 'harian', label: 'Hitung Harian', icon: 'calculator', workflow: true },
    { id: 'semifinal', label: 'Semi Final', icon: 'shield-check', workflow: true },
    { id: 'rekap', label: 'Rekap SDM', icon: 'users', workflow: true },
    { id: 'final', label: 'Final', icon: 'badge-check', workflow: true },
    { id: 'final-tukin', label: 'Final Tukin', icon: 'badge-check', workflow: false, always: true },
    { id: 'final-tukin-results', label: 'Hasil Perhitungan', icon: 'table', workflow: false, always: true },
    { id: 'export', label: 'Export Excel', icon: 'file-down', workflow: true }
  ];

  function defaultConfig() {
    const master = EVKIN.master || {};
    const holidaysDefault = Array.isArray(master.holidays2026) ? master.holidays2026 : [];
    const jabatanDefault = Array.isArray(master.jabatanDefault) ? master.jabatanDefault : [];
    const jenisDefault = Array.isArray(master.jenisNoPotonganDefault) ? master.jenisNoPotonganDefault : [];
    return {
      saved: false,
      effectiveDaysMode: 'auto',
      effectiveDaysManual: 22,
      holidays: holidaysDefault.map(h => ({ d: h && h.d, n: h && h.n ? h.n : 'Libur' })).filter(h => h && h.d),
      jabatanMaster: jabatanDefault.map(j => ({ nama: j && j.nama ? j.nama : '', metode: j && j.metode === 'durasi' ? 'durasi' : 'reguler' })).filter(j => j && j.nama),
      jamDasar: {
        senKam: { masuk: '07:30', pulang: '16:00' },
        jumat: { masuk: '07:30', pulang: '16:30' }
      },
      flexi: {
        enabled: true,
        masukStart: '07:31', masukEnd: '08:00',
        kompensasiSenKam: '16:30', kompensasiJumat: '17:00'
      },
      keterlambatanTiers: [
        { max: 30, pct: 0.5 }, { max: 60, pct: 1 }, { max: 90, pct: 1.50 }, { max: 120, pct: 2 }, { max: 9999, pct: 3 }
      ],
      pulangCepatTiers: [
        { max: 30, pct: 0.5 }, { max: 60, pct: 1 }, { max: 90, pct: 1.50 }, { max: 120, pct: 2 }, { max: 9999, pct: 3 }
      ],
      minDurasiJam: 7.5,
      potonganTidakLengkap: 3,
      potonganHariKurangPerHari: 3,
      jenisNoPotongan: jenisDefault.slice(),
      leavePeriods: [],
      masterPegawai: []
    };
  }

  function normalizeConfig(rawConfig) {
    const base = defaultConfig();
    const source = rawConfig && typeof rawConfig === 'object' ? rawConfig : {};
    const merged = { ...base, ...source };
    const jamDasar = source.jamDasar || {};
    const senKam = jamDasar.senKam || {};
    const jumat = jamDasar.jumat || {};
    const flexi = source.flexi || {};
    const mergedJam = {
      senKam: { masuk: senKam.masuk || base.jamDasar.senKam.masuk, pulang: senKam.pulang || base.jamDasar.senKam.pulang },
      jumat: { masuk: jumat.masuk || base.jamDasar.jumat.masuk, pulang: jumat.pulang || base.jamDasar.jumat.pulang }
    };
    const mergedFlexi = {
      enabled: typeof flexi.enabled === 'boolean' ? flexi.enabled : base.flexi.enabled,
      masukStart: flexi.masukStart || base.flexi.masukStart,
      masukEnd: flexi.masukEnd || base.flexi.masukEnd,
      kompensasiSenKam: flexi.kompensasiSenKam || base.flexi.kompensasiSenKam,
      kompensasiJumat: flexi.kompensasiJumat || base.flexi.kompensasiJumat
    };
    const normalizeTierList = (list, fallback) => {
      const arr = Array.isArray(list) ? list : fallback;
      return arr.map((tier) => ({ max: Number(tier && tier.max) || 0, pct: Number(tier && tier.pct) || 0 })).filter(tier => Number.isFinite(tier.max) && Number.isFinite(tier.pct));
    };
    return {
      ...merged,
      saved: !!source.saved,
      effectiveDaysMode: source.effectiveDaysMode === 'manual' ? 'manual' : 'auto',
      effectiveDaysManual: Number(source.effectiveDaysManual) || base.effectiveDaysManual,
      holidays: Array.isArray(source.holidays) ? source.holidays.map(h => ({ d: String(h && h.d || ''), n: String(h && h.n || 'Libur') })).filter(h => h.d) : base.holidays,
      jabatanMaster: Array.isArray(source.jabatanMaster) ? source.jabatanMaster.map(j => ({ nama: String(j && j.nama || ''), metode: j && j.metode === 'durasi' ? 'durasi' : 'reguler' })).filter(j => j.nama) : base.jabatanMaster,
      jamDasar: mergedJam,
      flexi: mergedFlexi,
      keterlambatanTiers: normalizeTierList(source.keterlambatanTiers, base.keterlambatanTiers),
      pulangCepatTiers: normalizeTierList(source.pulangCepatTiers, base.pulangCepatTiers),
      minDurasiJam: Number(source.minDurasiJam) || base.minDurasiJam,
      potonganTidakLengkap: source.potonganTidakLengkap != null && source.potonganTidakLengkap !== '' && Number.isFinite(Number(source.potonganTidakLengkap)) && Number(source.potonganTidakLengkap) >= 0 ? Number(source.potonganTidakLengkap) : base.potonganTidakLengkap,
      potonganHariKurangPerHari: source.potonganHariKurangPerHari != null && source.potonganHariKurangPerHari !== '' && Number.isFinite(Number(source.potonganHariKurangPerHari)) && Number(source.potonganHariKurangPerHari) >= 0 ? Number(source.potonganHariKurangPerHari) : base.potonganHariKurangPerHari,
      jenisNoPotongan: Array.isArray(source.jenisNoPotongan) ? source.jenisNoPotongan.map(String).filter(Boolean) : base.jenisNoPotongan,
      leavePeriods: Array.isArray(source.leavePeriods) ? source.leavePeriods : base.leavePeriods,
      masterPegawai: Array.isArray(source.masterPegawai) ? source.masterPegawai : base.masterPegawai
    };
  }

  const state = EVKIN.state = {
    rawHeaders: [],
    raw: [],
    data: [],
    importStats: null,
    importMode: 'standard',
    config: normalizeConfig(defaultConfig()),
    daily: [],
    harianPage: 0,
    rekap: [],
    rekapPage: 0,
    semifinalVerified: false,
    semifinal: [],
    semifinalPage: 0,
    final: [],
    finalPage: 0,
    finalSKP: { enabled: false, rows: [] },
    finalKombinasi: { enabled: false, useApp: true, useEabsensi: false, useEsdm: false, rows: [] },
    finalCombinedSKP: {
      useApp: true,
      useEabsensi: false,
      useEsdm: false,
      skpRows: [],
      eabsensiRows: [],
      esdmRows: [],
      combinedRows: [],
      absensiProcessed: false
    },
    reconciliationReviewed: false,
    auditLog: [],
    month: '',
    timeMode: 'original'
  };
  EVKIN.defaultConfig = defaultConfig;
  EVKIN.normalizeConfig = normalizeConfig;

  EVKIN.getMasterPegawaiList = function () {
    const rows = Array.isArray(state.config && state.config.masterPegawai) ? state.config.masterPegawai : [];
    return rows;
  };

  EVKIN.assertDailyCoverage = function () {
    if (state.workflowLoadError) throw new Error(state.workflowLoadError);
    const expected = state.data.filter(r => !r.deleted && r.tanggal && r.nip);
    const key = r => r._id || (r.nip + '|' + ((r.tanggal && r.tanggal.key) || r.tanggalKey || ''));
    const remaining = new Map();
    expected.forEach(r => remaining.set(key(r), (remaining.get(key(r)) || 0) + 1));
    for (const row of state.daily) {
      const count = remaining.get(key(row)) || 0;
      if (!count) throw new Error('Hasil Harian tidak cocok dengan data impor. Hitung ulang seluruh data.');
      remaining.set(key(row), count - 1);
    }
    const missing = [...remaining.values()].reduce((a,b) => a+b,0);
    if (missing) throw new Error(`${missing} record impor belum dihitung Harian. Hitung ulang seluruh data sebelum verifikasi/Rekap.`);
    return {expected:expected.length, calculated:state.daily.length};
  };

  // ---- Persistensi (DuckDB master-only) ----
  EVKIN.save = async function () {
    try {
      if (EVKIN.exportBackend && EVKIN.exportBackend.enabled) {
        // Saving workflow results must not re-import the entire canonical SDM
        // master. Master edits are committed explicitly in the Master SDM module.
          await EVKIN.syncBackendWorkflow(undefined, {derivedOnly:true}).catch((err) => {
          console.warn('Gagal sinkronisasi state ke DuckDB master:', err);
          throw err;
        });
        return true;
      }
      console.warn('DuckDB master-only mode: backend tidak aktif. State hanya ada di memory browser.' );
      return false;
    } catch (e) { console.warn('Gagal simpan state ke master database', e); return false; }
  };

  EVKIN.load = async function () {
    try {
      if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) {
        return false;
      }
      const response = await fetch(new URL('/api/workflow/state', EVKIN.exportBackend.apiBase).toString(), {
        method: 'GET',
        cache: 'no-store'
      });
      if (!response.ok) {
        console.warn('Tidak ada state tersimpan di DuckDB:', response.status);
        return false;
      }
      const result = await response.json();
      const data = result && result.data ? result.data : {};

      const masterCache = state.config && state.config.masterPegawai || [];
      if (data.config !== undefined && data.config !== null) {
        state.config = typeof data.config === 'string' ? JSON.parse(data.config) : data.config;
      } else { state.config = defaultConfig(); }
      state.config = normalizeConfig(state.config || defaultConfig());
      state.config.masterPegawai = masterCache;
      state.config = normalizeConfig(state.config);
      state.rawHeaders = Array.isArray(data.raw_import) ? Object.keys(data.raw_import[0] || {}) : state.rawHeaders;
      state.raw = Array.isArray(data.raw_import) ? data.raw_import : state.raw;
      if (Array.isArray(data.processed_data) && data.processed_data.length) {
        state.data = data.processed_data.map(row => typeof row.record === 'string' ? JSON.parse(row.record) : row.record);
      } else if (Array.isArray(data.raw_import) && data.raw_import.length) {
        // Older snapshots only contain raw columns. Rebuild calculation records without saving or re-importing.
        state.data = state.config._workflow && state.config._workflow.importMode === 'wali' && EVKIN.waliImportMod
          ? EVKIN.waliImportMod.restoreRecords(data.raw_import) : EVKIN.importMod.restoreRecords(data.raw_import);
      } else { state.data = []; }
      const workflow = state.config._workflow || {};
      const expectedCount = Number(workflow.importStats && workflow.importStats.totalRecord) || 0;
      state.workflowLoadError = '';
      if (expectedCount > state.data.length) {
        // Repair old interrupted batch saves only when complete source data is available.
        const restored = workflow.importMode === 'wali' && EVKIN.waliImportMod && EVKIN.waliImportMod.restoreRecords
          ? EVKIN.waliImportMod.restoreRecords(state.raw) : EVKIN.importMod.restoreRecords(state.raw);
        const prefixMatches = state.data.every((row,index) => restored[index] && row.nip === restored[index].nip && row.tanggal.key === restored[index].tanggal.key);
        if (restored.length === expectedCount && prefixMatches) {
          state.data = state.data.concat(restored.slice(state.data.length));
        } else {
          state.workflowLoadError = `Impor tersimpan tidak lengkap: ${state.data.length}/${expectedCount} record. Impor ulang file sumber lengkap sebelum menghitung.`;
        }
      }
      const months = [...new Set(state.data.filter(row => row.tanggal && !row.deleted).map(row => row.tanggal.monthKey).filter(Boolean))].sort();
      state.month = months.includes(workflow.month) ? workflow.month : (months[0] || '');
      state.timeMode = workflow.timeMode || 'original';
      state.importMode = workflow.importMode || 'standard';
      state.importStats = {...(workflow.importStats || {}), months, totalRecord:state.data.length,
        totalRaw:state.raw.length, totalSDM:new Set(state.data.map(row=>row.nip)).size};
      state.semifinalVerified = workflow.semifinalVerified === true && Array.isArray(data.daily_data) && data.daily_data.length > 0;
      if (EVKIN.exportBackend && EVKIN.exportBackend.getWorkflowFlags && state.month) {
        try {
          const flags = await EVKIN.exportBackend.getWorkflowFlags(state.month);
          state.semifinalVerified = !!(flags.flags && flags.flags['semifinal:' + state.month] && flags.flags['semifinal:' + state.month].verified);
        } catch (error) {
          console.warn('Status verifikasi server tidak dapat dimuat:', error);
          state.semifinalVerified = false;
        }
      }
      state.daily = Array.isArray(data.daily_data) ? data.daily_data : [];
      state.rekap = Array.isArray(data.rekap_sdm) ? data.rekap_sdm : [];
      state.semifinal = Array.isArray(data.semifinal) ? data.semifinal : [];
      state.final = Array.isArray(data.final_absensi) ? data.final_absensi.map((row) => ({
        ...row,
        tukin: row.tukin ?? row.tukinbruto ?? row.tukin_gross,
        komponen: row.komponen ?? row.komponenKehadiran,
        potPct: row.potPct ?? row.potonganKehadiranPct,
        nominal: row.nominal ?? row.nominalPotonganKehadiran,
        finalDibayar: row.finalDibayar ?? row.final_tukin_dibayar
      })) : [];
      state.dailyComplete = false;
      if (state.daily.length) {
        try { EVKIN.assertDailyCoverage(); state.dailyComplete = true; }
        catch (error) { state.semifinalVerified = false; }
      }
      const recapComplete = state.rekap.length && state.rekap.reduce((sum,row) => sum + Number(row.jumlahRecord || 0),0) === state.daily.length;
      if (!state.dailyComplete || !state.semifinalVerified || !recapComplete) state.rekap = [];
      if (!state.dailyComplete || !state.semifinalVerified || !recapComplete) state.final = [];
      // Preserve the input rows and source selections, not only calculated exports.
      state.finalSKP = { enabled: false, rows: data.final_skp || [], ...(state.final.length ? workflow.finalSKP : {}) };
      state.finalKombinasi = { enabled: false, useApp: true, useEabsensi: false, useEsdm: false,
        rows: data.final_kombinasi || [], ...(state.final.length ? workflow.finalKombinasi : {}) };
      state.finalCombinedSKP = { useApp: true, useEabsensi: false, useEsdm: false,
        skpRows: [], eabsensiRows: [], esdmRows: [], combinedRows: data.final_combined_skp || [],
        absensiProcessed: false, ...(state.final.length ? workflow.finalCombinedSKP : {}) };
      if (!state.config) state.config = defaultConfig();
      state.config = normalizeConfig(state.config);
      return true;
    } catch (e) { state.workflowLoadError = 'Data workflow gagal dimuat: ' + e.message; console.warn('Gagal baca state dari master database', e); return false; }
  };

  EVKIN.previewResetProfile = async function (profile) {
    const response = await fetch(new URL(`/api/admin/module-reset/${encodeURIComponent(profile)}/preview`, EVKIN.exportBackend.apiBase), {cache:'no-store'});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Preview reset gagal.');
    return result;
  };

  EVKIN.executeResetProfile = async function (profile, preview, details = {}) {
    const response = await fetch(new URL(`/api/admin/module-reset/${encodeURIComponent(profile)}`, EVKIN.exportBackend.apiBase), {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        preview_token:preview.preview_token, confirmation:preview.confirmation,
        actor:details.actor || 'EVKIN_LOCAL_UI', reason:details.reason || `Reset ${profile}`
      })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || 'Reset gagal. Data aplikasi tetap dipertahankan.');
    return result;
  };

  EVKIN.requestResetProfile = async function (profile, details = {}) {
    const preview = await EVKIN.previewResetProfile(profile);
    return EVKIN.executeResetProfile(profile, preview, details);
  };

  EVKIN.resetAll = async function () {
    if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) {
      throw new Error('Aktifkan backend sebelum mereset workflow.');
    }
    await EVKIN.requestResetProfile('workflow_results', {reason:'Reset hasil workflow dari UI'});
    if (!await EVKIN.load()) throw new Error('Reset selesai, tetapi pemuatan ulang gagal. Muat ulang halaman.');
    state.harianPage = state.rekapPage = state.semifinalPage = state.finalPage = 0;
  };

  EVKIN.deleteAbsensiWorkflow = async function () {
    if (!EVKIN.exportBackend || !EVKIN.exportBackend.enabled) throw new Error('Aktifkan backend terlebih dahulu.');
    if (EVKIN.deletingAbsensi || (EVKIN.harianMod && EVKIN.harianMod.processing)) {
      throw new Error('Tunggu proses workflow selesai sebelum menghapus data.');
    }
    EVKIN.deletingAbsensi = true;
    try {
      // Finish previously queued writes so they cannot restore data after deletion.
      await EVKIN.exportBackend.syncQueue;
      const result = await EVKIN.requestResetProfile('workflow', {reason:'Reset seluruh workflow dari UI'});
      if (!await EVKIN.load()) throw new Error('Data backend sudah dihapus. Muat ulang halaman karena pemuatan state gagal.');
      state.harianPage = state.rekapPage = state.semifinalPage = state.finalPage = 0;
      state.reconciliationReviewed = false;
      if (EVKIN.db && EVKIN.db.replaceStore) {
        await Promise.all(['workflow_config','raw_import','daily_data','rekap_sdm','final_absensi',
          'final_skp','final_kombinasi','final_combined_skp'].map(name => EVKIN.db.replaceStore(name, [])))
          .catch(() => { throw new Error('Data backend sudah dihapus, tetapi cache browser gagal dibersihkan. Muat ulang halaman.'); });
      }
      return result;
    } finally { EVKIN.deletingAbsensi = false; }
  };

  // ---- Status penyelesaian tiap tahap ----
  EVKIN.stepDone = function (id) {
    switch (id) {
      case 'import': return state.data.length > 0;
      case 'config': return !!state.config.saved;
      case 'master-sdm': return Array.isArray(state.config.masterPegawai) && state.config.masterPegawai.length > 0;
      case 'reconcile': return !!state.reconciliationReviewed;
      case 'harian': return state.daily.length > 0 && state.dailyComplete !== false;
      case 'rekap': return state.rekap.length > 0;
      case 'semifinal': return !!state.semifinalVerified;
      case 'final': return state.final.length > 0;
      case 'export': return state.final.length > 0;
      default: return false;
    }
  };

  EVKIN.stepUnlocked = function (id) {
    switch (id) {
      case 'dashboard': return true;
      case 'pembulatan': return true;
      case 'import': return true;
      case 'config': return EVKIN.stepDone('import');
      case 'master-sdm': return true;
      case 'skp-assessment': return true;
      case 'final-tukin': return true; // Backend validates the selected period/mode and verified Rekap SDM.
      case 'final-tukin-results': return true; // Persisted snapshots remain accessible after restart.
      case 'master-pengembalian': return true;
      case 'tukin-annual': return true;
      case 'reconcile': return true;
      case 'harian': return EVKIN.stepDone('import') && EVKIN.stepDone('config');
      case 'semifinal': return EVKIN.stepDone('harian');
      // Navigation remains available for reviewing results and recovery guidance.
      // Calculation is guarded separately by rekapMod.process.
      case 'rekap': return true;
      case 'final': return EVKIN.stepDone('semifinal') && EVKIN.stepDone('rekap');
      case 'export': return EVKIN.stepUnlocked('final') && EVKIN.stepDone('final');
      default: return false;
    }
  };

  // Invalidasi hasil tahap-tahap setelah perubahan hulu
  EVKIN.invalidateFrom = function (id, options = {}) {
    const order = ['import', 'config', 'harian', 'semifinal', 'rekap', 'final'];
    const idx = order.indexOf(id);
    const clr = (from) => {
      if (from <= order.indexOf('harian')) { state.daily = []; state.dailyComplete = false; state.harianPage = 0; }
      if (from <= order.indexOf('semifinal')) { state.semifinalVerified = false; state.semifinal = []; state.semifinalPage = 0; }
      if (from <= order.indexOf('rekap')) { state.rekap = []; state.rekapPage = 0; }
      if (from <= order.indexOf('final')) {
        state.final = []; state.finalPage = 0;
        state.finalSKP = { enabled: false, rows: [] };
        state.finalKombinasi = { enabled: false, useApp: true, useEabsensi: false, useEsdm: false, rows: [] };
        state.finalCombinedSKP = { useApp: true, useEabsensi: false, useEsdm: false, skpRows: [], eabsensiRows: [], esdmRows: [], combinedRows: [], absensiProcessed: false };
      }
    };
    // saat suatu tahap berubah, hapus tahap setelahnya
    clr(idx + 1);
    if (options.save !== false) EVKIN.save();
  };

})();
