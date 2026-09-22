(function(){
  const EVKIN = window.EVKIN || {};
  EVKIN.jobs = EVKIN.jobs || {};
  const backend = EVKIN.exportBackend || {};

  function apiBase() { return backend.apiBase || 'http://localhost:8000'; }

  EVKIN.jobs.show = async function() {
    const main = document.getElementById('main');
    main.innerHTML = `<div class="card"><h3>Job Monitor</h3>
      <div id="jobsList">Memuat...</div>
      <div style="margin-top:12px"><button class="btn btn-secondary" id="refreshJobs">Refresh</button></div></div>`;
    document.getElementById('refreshJobs').onclick = () => EVKIN.jobs.refresh();
    EVKIN.jobs.refresh();
  };

  EVKIN.jobs.refresh = async function() {
    const list = document.getElementById('jobsList');
    list.innerHTML = 'Memuat...';
    try {
      const res = await fetch(new URL('/api/jobs', apiBase()).toString());
      if (!res.ok) throw new Error('Gagal ambil daftar job: ' + res.status);
      const jobs = await res.json();
      if (!jobs || !jobs.length) { list.innerHTML = '<div class="muted">Tidak ada job.</div>'; return; }
      const rows = jobs.map(j => {
        const progress = Math.round((j.progress || 0) * 100);
        const started = j.started_at ? j.started_at.replace('T',' ').replace('Z','') : '-';
        const finished = j.finished_at ? j.finished_at.replace('T',' ').replace('Z','') : '-';
        return `<div class="job-row card small" style="margin-bottom:8px;padding:8px;display:flex;justify-content:space-between;align-items:center">
          <div style="flex:1">
            <div><strong>${j.id}</strong> <span class="muted">(${j.type})</span></div>
            <div class="muted">Status: ${j.status} | Progress: ${progress}% | Rows: ${j.row_count ?? '-'}</div>
            <div class="muted">Started: ${started} | Finished: ${finished}</div>
            <div class="muted small">Message: ${j.message ? j.message.toString().slice(0,240) : ''}</div>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;margin-left:8px">
            <button class="btn btn-ghost" data-action="view" data-id="${j.id}">Lihat</button>
            <button class="btn btn-warning" data-action="cancel" data-id="${j.id}">Cancel</button>
            <button class="btn btn-primary" data-action="retry" data-id="${j.id}">Retry</button>
          </div>
        </div>`;
      }).join('');
      list.innerHTML = rows;
      list.querySelectorAll('button[data-action]').forEach(btn => btn.onclick = async (e) => {
        const id = btn.dataset.id; const act = btn.dataset.action;
        try {
          if (act === 'view') {
            const r = await fetch(new URL('/api/jobs/' + id, apiBase()).toString());
            if (!r.ok) throw new Error('Gagal ambil job');
            const jd = await r.json();
            alert(JSON.stringify(jd, null, 2));
          } else if (act === 'cancel') {
            const r = await fetch(new URL('/api/jobs/' + id + '/cancel', apiBase()).toString(), { method: 'POST' });
            if (!r.ok) throw new Error('Cancel gagal');
            EVKIN.toast('Cancel requested', 'info');
            EVKIN.jobs.refresh();
          } else if (act === 'retry') {
            const r = await fetch(new URL('/api/jobs/' + id + '/retry', apiBase()).toString(), { method: 'POST' });
            if (!r.ok) throw new Error('Retry gagal');
            const data = await r.json();
            EVKIN.toast('Retry queued: ' + data.job_id, 'success');
            EVKIN.jobs.refresh();
          }
        } catch (err) { EVKIN.toast(err.message || err, 'error'); }
      });
    } catch (err) {
      list.innerHTML = '<div class="alert error">' + (err.message || err) + '</div>';
    }
  };
})();
