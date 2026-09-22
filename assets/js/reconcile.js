/* EVKIN ABSENSI v3.1 - reconcile.js */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util, S = EVKIN.state;
  const mod = EVKIN.reconcileMod = {};

  function collectIssues() {
    const rawRows = Array.isArray(S.raw) && S.raw.length ? S.raw : (Array.isArray(S.data) ? S.data : []);
    const dailyRows = Array.isArray(S.daily) ? S.daily : [];
    const rawNips = new Set();
    const detailed = [];
    const dailyIssues = [];

    rawRows.forEach((row) => {
      const nip = String(row && row.nip ? row.nip : '').trim();
      if (nip) rawNips.add(nip);
    });

    dailyRows.forEach((row) => {
      const nip = String(row && row.nip ? row.nip : '').trim();
      const date = row && row.tanggal ? row.tanggal : '-';
      const name = row && row.nama ? row.nama : '-';

      if (row && row.statusDuplikasi) {
        dailyIssues.push({ nip, nama: name, tanggal: date, type: 'Duplikasi', detail: Array.isArray(row.flags) && row.flags.length ? row.flags.join(', ') : 'Record ganda pada tanggal yang sama' });
      }
      if (row && row.statusLengkap === 'Tidak Lengkap') {
        dailyIssues.push({ nip, nama: name, tanggal: date, type: 'Absensi tidak lengkap', detail: 'Jam masuk/pulang tidak lengkap' });
      }
      if (row && Array.isArray(row.flags) && row.flags.length && !row.statusDuplikasi && row.statusLengkap !== 'Tidak Lengkap') {
        dailyIssues.push({ nip, nama: name, tanggal: date, type: 'Flag operasional', detail: row.flags.join(', ') });
      }
      if (nip) {
        detailed.push(nip);
      }
    });

    const dailyNips = new Set(detailed);
    const missingInDaily = Array.from(rawNips).filter((nip) => !dailyNips.has(nip));
    missingInDaily.forEach((nip) => {
      const rawRow = rawRows.find((row) => String(row && row.nip ? row.nip : '').trim() === nip) || {};
      dailyIssues.push({
        nip,
        nama: rawRow.nama || '-',
        tanggal: rawRow.tanggal || '-',
        type: 'Tidak masuk hasil harian',
        detail: 'NIP ada di raw import, tetapi tidak ada record valid pada hasil harian.'
      });
    });

    const summary = {
      totalRaw: rawRows.length,
      totalDaily: dailyRows.length,
      duplicate: dailyRows.filter((row) => row && row.statusDuplikasi).length,
      incomplete: dailyRows.filter((row) => row && row.statusLengkap === 'Tidak Lengkap').length,
      missingDaily: missingInDaily.length,
      totalIssue: dailyIssues.length,
      reviewed: !!S.reconciliationReviewed
    };

    return { summary, issues: dailyIssues.slice(0, 80) };
  }

  mod.render = function (el) {
    const { summary, issues } = collectIssues();
    const rowsHtml = issues.length
      ? issues.map((item) => `
          <tr>
            <td>${U.esc(item.nip || '-')}</td>
            <td>${U.esc(item.nama || '-')}</td>
            <td>${U.esc(item.tanggal || '-')}</td>
            <td>${U.esc(item.type || 'Catatan')}</td>
            <td>${U.esc(item.detail || '-')}</td>
          </tr>`).join('')
      : '<tr><td colspan="5" class="muted">Belum ada catatan rekonsiliasi untuk periode ini.</td></tr>';

    el.innerHTML = `
      <div class="module-head">
        <div>
          <h2>Rekonsiliasi &amp; Validasi</h2>
          <p class="muted">Pemeriksaan cepat antara data raw, hasil harian, dan potensi masalah sebelum masuk tahap final.</p>
        </div>
        <div>
          ${summary.reviewed ? '<span class="pill green">✓ Sudah direview</span>' : '<span class="pill yellow">⚠ Belum direview</span>'}
        </div>
      </div>

      <div class="stat-grid">
        ${card('Data Raw', summary.totalRaw, 'database', 'blue')}
        ${card('Hasil Harian', summary.totalDaily, 'list-checks', 'blue')}
        ${card('Duplikasi', summary.duplicate, 'copy', summary.duplicate ? 'red' : 'green')}
        ${card('Tidak Lengkap', summary.incomplete, 'file-warning', summary.incomplete ? 'yellow' : 'green')}
        ${card('Belum Sinkron', summary.missingDaily, 'alert-circle', summary.missingDaily ? 'red' : 'green')}
        ${card('Catatan', summary.totalIssue, 'clipboard-check', summary.totalIssue ? 'yellow' : 'green')}
      </div>

      <div class="card" style="margin-top:16px;">
        <div class="filter-bar" style="justify-content: space-between; align-items: center;">
          <strong>Catatan rekonsiliasi</strong>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn btn-secondary btn-sm" id="refreshReconcile"><i data-lucide="refresh-cw"></i> Refresh</button>
            <button class="btn btn-success btn-sm" id="markReviewed"><i data-lucide="check-circle"></i> Tandai Sudah Direview</button>
          </div>
        </div>

        <div class="table-wrap">
          <table class="data-table sm">
            <thead>
              <tr>
                <th>NIP</th>
                <th>Nama</th>
                <th>Tanggal</th>
                <th>Jenis</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>
      </div>
    `;

    const reviewButton = el.querySelector('#markReviewed');
    if (reviewButton) {
      reviewButton.onclick = () => {
        S.reconciliationReviewed = true;
        EVKIN.save();
        EVKIN.toast('Rekonsiliasi telah ditandai selesai.', 'success');
        EVKIN.go('reconcile');
      };
    }

    const refreshButton = el.querySelector('#refreshReconcile');
    if (refreshButton) {
      refreshButton.onclick = () => {
        EVKIN.go('reconcile');
      };
    }
  };

  function card(label, value, icon, color) {
    return `<div class="stat-card ${color}"><div class="stat-icon"><i data-lucide="${icon}"></i></div><div><div class="stat-val">${value}</div><div class="stat-label">${label}</div></div></div>`;
  }
})();
