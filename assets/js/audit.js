/* EVKIN ABSENSI v3.1 - audit.js
   Modul Audit Log untuk tracking perubahan data dan proses */
(function () {
  const EVKIN = window.EVKIN;
  const S = EVKIN.state;
  const mod = EVKIN.auditMod = {};

  // ---- Constants ----
  const ACTIONS = {
    DATA_IMPORT: 'DATA_IMPORT',
    DATA_EDIT: 'DATA_EDIT',
    DATA_PROCESS: 'DATA_PROCESS',
    DATA_DELETE: 'DATA_DELETE',
    DATA_EXPORT: 'DATA_EXPORT',
    SKP_IMPORT: 'SKP_IMPORT',
    EABSENSI_IMPORT: 'EABSENSI_IMPORT',
    ESDM_IMPORT: 'ESDM_IMPORT',
    ABSENSI_PROCESS: 'ABSENSI_PROCESS',
    WORKFLOW_ADVANCE: 'WORKFLOW_ADVANCE',
    SESSION_START: 'SESSION_START',
    WORKFLOW_STAGE: 'WORKFLOW_STAGE',
    DATABASE_SYNC: 'DATABASE_SYNC',
    STATE_RESET: 'STATE_RESET'
  };

  const SESSION_KEY = 'evkin_audit_session_id';
  let sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = 'EVKIN-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8).toUpperCase();
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }
  mod.sessionId = sessionId;

  // ---- Log an action ----
  mod.log = function (action, details) {
    const entry = {
      timestamp: new Date().toISOString(),
      sessionId,
      action: action,
      details: details || {},
      userAgent: navigator.userAgent,
      ipInfo: 'local' // Aplikasi client-side, tidak ada IP tracking
    };

    S.auditLog.push(entry);

    // Batasi log ke 1000 entries terakhir untuk prevent memory bloat
    if (S.auditLog.length > 1000) {
      S.auditLog = S.auditLog.slice(-1000);
    }

    // Audit tidak memanggil EVKIN.save(): penyimpanan state besar bersifat sinkron
    // dan dapat menghambat export Excel. Audit ikut tersimpan pada save workflow berikutnya.
    console.log('[AUDIT]', action, details);
  };

  mod.startSession = function () {
    mod.log(ACTIONS.SESSION_START, {
      sessionId,
      app: 'EVKIN ABSENSI TENDIK',
      version: 'v1.5',
      month: S.month || null
    });
  };

  mod.logStage = function (stage, status = 'OPENED') {
    mod.log(ACTIONS.WORKFLOW_STAGE, { stage, status, month: S.month || null });
  };

  mod.logDatabaseSync = function (database, status, counts) {
    mod.log(ACTIONS.DATABASE_SYNC, { database, status, counts: counts || {} });
  };

  // ---- Import Data ----
  mod.logDataImport = function (count, month) {
    mod.log(ACTIONS.DATA_IMPORT, { count, month, source: 'CSV/Excel' });
  };

  // ---- SKP Import ----
  mod.logSkpImport = function (imported, notfound, source = 'unknown') {
    mod.log(ACTIONS.SKP_IMPORT, { imported, notfound, source });
  };

  // ---- E-Absensi Import ----
  mod.logEabsensiImport = function (imported, notfound) {
    mod.log(ACTIONS.EABSENSI_IMPORT, { imported, notfound });
  };

  // ---- E-SDM Import ----
  mod.logEsdmImport = function (imported, notfound) {
    mod.log(ACTIONS.ESDM_IMPORT, { imported, notfound });
  };

  // ---- Data Edit ----
  mod.logDataEdit = function (nip, field, oldValue, newValue) {
    mod.log(ACTIONS.DATA_EDIT, { nip, field, oldValue, newValue });
  };

  // ---- Proses Potongan Absensi ----
  mod.logAbsensiProcess = function (totalProcessed, useSources) {
    mod.log(ACTIONS.ABSENSI_PROCESS, {
      totalProcessed,
      useApp: useSources.app,
      useEabsensi: useSources.eabsensi,
      useEsdm: useSources.esdm,
      timestamp: new Date().toISOString()
    });
  };

  // ---- Data Export ----
  mod.logDataExport = function (filename, recordCount) {
    mod.log(ACTIONS.DATA_EXPORT, { filename, recordCount, timestamp: new Date().toISOString() });
  };

  // ---- Workflow Advance ----
  mod.logWorkflowAdvance = function (fromStep, toStep) {
    mod.log(ACTIONS.WORKFLOW_ADVANCE, { fromStep, toStep });
  };

  // ---- State Reset ----
  mod.logStateReset = function () {
    mod.log(ACTIONS.STATE_RESET, { message: 'Semua data di-reset' });
  };

  // ---- Get Audit Report ----
  mod.getReport = function (filters = {}) {
    let logs = S.auditLog;

    if (filters.action) {
      logs = logs.filter(l => l.action === filters.action);
    }
    if (filters.nip) {
      logs = logs.filter(l => l.details.nip === filters.nip);
    }
    if (filters.startDate && filters.endDate) {
      const start = new Date(filters.startDate).getTime();
      const end = new Date(filters.endDate).getTime();
      logs = logs.filter(l => {
        const t = new Date(l.timestamp).getTime();
        return t >= start && t <= end;
      });
    }

    return logs;
  };

  // ---- Export Audit Log as CSV ----
  mod.exportAsCSV = function () {
    const headers = ['Timestamp', 'Session ID', 'Action', 'Details', 'User Agent'];
    const rows = S.auditLog.map(entry => [
      entry.timestamp,
      entry.sessionId || '',
      entry.action,
      JSON.stringify(entry.details).replace(/"/g, '""'),
      entry.userAgent
    ]);

    const csv = [
      headers.map(h => '"' + h + '"').join(','),
      ...rows.map(r => r.map(v => '"' + v + '"').join(','))
    ].join('\n');

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'audit_log_' + new Date().toISOString().split('T')[0] + '.csv';
    link.click();
  };

  mod.exportAsExcel = function () {
    if (!window.XLSX) {
      EVKIN.toast('Modul Excel belum tersedia', 'error');
      return false;
    }
    const rows = S.auditLog.map(entry => ({
      Timestamp: entry.timestamp,
      'Session ID': entry.sessionId || '',
      Action: entry.action,
      Details: JSON.stringify(entry.details || {}),
      'User Agent': entry.userAgent || '',
      'IP Info': entry.ipInfo || 'local'
    }));
    const summary = Object.entries(mod.getStats().byAction).map(([action, count]) => ({
      Action: action,
      Count: count
    }));
    const workbook = XLSX.utils.book_new();
    const auditSheet = XLSX.utils.json_to_sheet(rows.length ? rows : [{ Timestamp: '', 'Session ID': sessionId, Action: '', Details: '', 'User Agent': '', 'IP Info': 'local' }]);
    const summarySheet = XLSX.utils.json_to_sheet(summary.length ? summary : [{ Action: '', Count: 0 }]);
    auditSheet['!cols'] = [{ wch: 24 }, { wch: 28 }, { wch: 22 }, { wch: 80 }, { wch: 45 }, { wch: 12 }];
    summarySheet['!cols'] = [{ wch: 28 }, { wch: 12 }];
    XLSX.utils.book_append_sheet(workbook, auditSheet, 'Audit Log');
    XLSX.utils.book_append_sheet(workbook, summarySheet, 'Ringkasan');
    const filename = 'audit_log_' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.xlsx';
    XLSX.writeFile(workbook, filename);
    return true;
  };

  // ---- Clear Audit Log ----
  mod.clearLog = function () {
    if (confirm('Yakin ingin menghapus semua audit log?')) {
      S.auditLog = [];
      EVKIN.save();
      return true;
    }
    return false;
  };

  // ---- Get Statistics ----
  mod.getStats = function () {
    const total = S.auditLog.length;
    const byAction = {};

    S.auditLog.forEach(entry => {
      byAction[entry.action] = (byAction[entry.action] || 0) + 1;
    });

    return { total, byAction };
  };
})();
