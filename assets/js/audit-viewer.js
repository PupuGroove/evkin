/* EVKIN ABSENSI v3.1 - audit-viewer.js
   Modul untuk melihat dan mengelola Audit Log */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util, S = EVKIN.state;
  const mod = EVKIN.auditViewerMod = {};

  mod.render = function (el) {
    const stats = EVKIN.auditMod.getStats();
    const logs = S.auditLog.slice().reverse(); // newest first

    el.innerHTML = `
      <div class="module-head">
        <div>
          <h2>📋 Audit Log Viewer</h2>
          <p class="muted">Tracking semua aktivitas aplikasi untuk mencegah manipulasi data</p>
        </div>
      </div>

      <div class="stat-grid big" style="margin-bottom: 24px;">
        <div class="stat-card blue">
          <div class="stat-icon"><i data-lucide="activity"></i></div>
          <div>
            <div class="stat-val">${stats.total}</div>
            <div class="stat-label">Total Log</div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>Statistik Aktivitas</h3>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 12px;">
          <div id="auditActionStats" style="display: contents;"></div>
        </div>
      </div>

      <div class="card" style="margin-top: 24px;">
        <h3>Recent Activity (${logs.length})</h3>
        <div style="display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap;">
          <input type="text" id="filterAction" placeholder="Filter by action..." style="flex: 1; padding: 8px; border: 1px solid #ddd; border-radius: 4px;" />
          <button id="exportAuditExcelBtn" class="btn btn-success btn-sm"><i data-lucide="file-spreadsheet"></i> Export Excel</button>
          <button id="exportAuditBtn" class="btn btn-primary btn-sm"><i data-lucide="download"></i> Export CSV</button>
          <button id="clearAuditBtn" class="btn btn-secondary btn-sm" title="Hati-hati: Ini akan menghapus semua audit log"><i data-lucide="trash-2"></i> Clear All</button>
        </div>

        ${logs.length === 0 ? '<div class="alert info">Belum ada aktivitas tercatat</div>' : `
          <div class="table-wrap">
            <table class="data-table sm">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Session</th>
                  <th>Action</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody id="auditLogRows"></tbody>
            </table>
          </div>
          <p style="text-align: center; margin-top: 12px; font-size: 12px; color: #999;">
            Showing ${Math.min(50, logs.length)} of ${logs.length} entries
          </p>
        `}
      </div>

      <div class="actions-row">
        <button id="auditBackBtn" class="btn btn-ghost"><i data-lucide="arrow-left"></i> Kembali</button>
      </div>
    `;

    renderActionStats(el.querySelector('#auditActionStats'), stats.byAction);
    const logRows = el.querySelector('#auditLogRows');
    if (logRows) renderRows(logRows, logs.slice(0, 50));

    // Event handlers
    const exportBtn = el.querySelector('#exportAuditBtn');
    if (exportBtn) {
      exportBtn.onclick = () => {
        EVKIN.auditMod.exportAsCSV();
        EVKIN.toast('✓ Audit log exported sebagai CSV', 'success');
      };
    }

    const exportExcelBtn = el.querySelector('#exportAuditExcelBtn');
    if (exportExcelBtn) {
      exportExcelBtn.onclick = () => {
        if (EVKIN.auditMod.exportAsExcel()) EVKIN.toast('✓ Audit log berhasil diekspor ke Excel', 'success');
      };
    }

    const clearBtn = el.querySelector('#clearAuditBtn');
    if (clearBtn) {
      clearBtn.onclick = () => {
        if (EVKIN.auditMod.clearLog()) {
          EVKIN.toast('✓ Audit log di-clear', 'success');
          EVKIN.go('audit-viewer');
        }
      };
    }

    const backBtn = el.querySelector('#auditBackBtn');
    if (backBtn) backBtn.addEventListener('click', () => EVKIN.go('dashboard'));

    const filterInput = el.querySelector('#filterAction');
    if (filterInput) {
      filterInput.onchange = () => {
        const action = filterInput.value.trim().toUpperCase();
        if (action) {
          const filtered = EVKIN.auditMod.getReport({ action });
          const tbody = el.querySelector('#auditLogRows');
          if (tbody) renderRows(tbody, filtered.slice(0, 50));
        }
      };
    }

    if (window.lucide) lucide.createIcons();
  };

  function appendText(parent, tagName, value, className, style) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (style) element.style.cssText = style;
    element.textContent = value == null ? '' : String(value);
    parent.appendChild(element);
    return element;
  }

  function renderActionStats(container, byAction) {
    if (!container) return;
    container.replaceChildren();
    Object.entries(byAction || {}).forEach(([action, count]) => {
      const card = document.createElement('div');
      card.style.cssText = 'padding:12px;background:#f5f5f5;border-radius:4px;text-align:center';
      appendText(card, 'div', count, '', 'font-weight:500;font-size:18px;color:#1976d2');
      appendText(card, 'div', formatActionLabel(action), '', 'font-size:12px;color:#666;margin-top:4px');
      container.appendChild(card);
    });
  }

  function renderRows(tbody, logs) {
    tbody.replaceChildren();
    (logs || []).forEach(log => {
      const row = document.createElement('tr');
      appendText(row, 'td', formatTimestamp(log.timestamp), '', 'font-size:12px;white-space:nowrap');
      appendText(row, 'td', log.sessionId || '-', '', 'font-size:11px;white-space:nowrap');
      const actionCell = document.createElement('td');
      appendText(actionCell, 'span', log.action, 'pill gray');
      row.appendChild(actionCell);
      const detailCell = document.createElement('td');
      detailCell.style.cssText = 'font-size:12px;max-width:300px;word-break:break-word';
      appendText(detailCell, 'code', JSON.stringify(log.details, null, 2));
      row.appendChild(detailCell);
      tbody.appendChild(row);
    });
  }

  mod.renderRows = renderRows;
  mod.renderActionStats = renderActionStats;

  function formatActionLabel(action) {
    const labels = {
      'DATA_IMPORT': 'Import Data',
      'SKP_IMPORT': 'Import SKP',
      'EABSENSI_IMPORT': 'Import E-Absensi',
      'ESDM_IMPORT': 'Import E-SDM',
      'ABSENSI_PROCESS': 'Proses Absensi',
      'DATA_EXPORT': 'Export Data',
      'DATA_EDIT': 'Edit Data',
      'DATA_DELETE': 'Delete Data',
      'WORKFLOW_ADVANCE': 'Workflow Advance',
      'STATE_RESET': 'Reset State',
      'SESSION_START': 'Mulai Sesi',
      'WORKFLOW_STAGE': 'Tahap Workflow',
      'DATABASE_SYNC': 'Sinkronisasi Database'
    };
    return labels[action] || action;
  }

  function formatTimestamp(ts) {
    const d = new Date(ts);
    return d.toLocaleString('id-ID', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  }
})();
