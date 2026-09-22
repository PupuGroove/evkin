(function(){
  const EVKIN = window.EVKIN || {};
  EVKIN.jobs = EVKIN.jobs || {};
  const backend = EVKIN.exportBackend || {};

  function apiBase() { return backend.apiBase || 'http://localhost:8000'; }

  function appendText(parent, tagName, value, className) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = value == null ? '' : String(value);
    parent.appendChild(element);
    return element;
  }

  function showListMessage(list, message, className) {
    list.replaceChildren();
    appendText(list, 'div', message, className);
  }

  async function handleJobAction(action, id) {
    try {
      if (action === 'view') {
        const response = await fetch(new URL('/api/jobs/' + encodeURIComponent(id), apiBase()).toString());
        if (!response.ok) throw new Error('Gagal ambil job');
        const job = await response.json();
        alert(JSON.stringify(job, null, 2));
      } else if (action === 'cancel') {
        const response = await fetch(new URL('/api/jobs/' + encodeURIComponent(id) + '/cancel', apiBase()).toString(), { method: 'POST' });
        if (!response.ok) throw new Error('Cancel gagal');
        EVKIN.toast('Cancel requested', 'info');
        EVKIN.jobs.refresh();
      } else if (action === 'retry') {
        const response = await fetch(new URL('/api/jobs/' + encodeURIComponent(id) + '/retry', apiBase()).toString(), { method: 'POST' });
        if (!response.ok) throw new Error('Retry gagal');
        const data = await response.json();
        EVKIN.toast('Retry queued: ' + data.job_id, 'success');
        EVKIN.jobs.refresh();
      }
    } catch (error) {
      EVKIN.toast(error.message || error, 'error');
    }
  }

  function renderJobs(list, jobs) {
    list.replaceChildren();
    if (!jobs || !jobs.length) {
      appendText(list, 'div', 'Tidak ada job.', 'muted');
      return;
    }

    jobs.forEach(job => {
      const progress = Math.round((Number(job.progress) || 0) * 100);
      const started = job.started_at ? String(job.started_at).replace('T', ' ').replace('Z', '') : '-';
      const finished = job.finished_at ? String(job.finished_at).replace('T', ' ').replace('Z', '') : '-';
      const row = document.createElement('div');
      row.className = 'job-row card small';
      row.style.cssText = 'margin-bottom:8px;padding:8px;display:flex;justify-content:space-between;align-items:center';

      const details = document.createElement('div');
      details.style.cssText = 'flex:1';
      const heading = document.createElement('div');
      appendText(heading, 'strong', job.id);
      heading.appendChild(document.createTextNode(' '));
      appendText(heading, 'span', '(' + String(job.type == null ? '' : job.type) + ')', 'muted');
      details.appendChild(heading);
      appendText(details, 'div', `Status: ${job.status == null ? '' : job.status} | Progress: ${progress}% | Rows: ${job.row_count ?? '-'}`, 'muted');
      appendText(details, 'div', `Started: ${started} | Finished: ${finished}`, 'muted');
      appendText(details, 'div', 'Message: ' + (job.message == null ? '' : String(job.message).slice(0, 240)), 'muted small');
      row.appendChild(details);

      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;flex-direction:column;gap:6px;margin-left:8px';
      [['view', 'Lihat', 'btn btn-ghost'], ['cancel', 'Cancel', 'btn btn-warning'], ['retry', 'Retry', 'btn btn-primary']].forEach(([action, label, className]) => {
        const button = appendText(actions, 'button', label, className);
        button.type = 'button';
        button.addEventListener('click', () => handleJobAction(action, String(job.id == null ? '' : job.id)));
      });
      row.appendChild(actions);
      list.appendChild(row);
    });
  }

  EVKIN.jobs.renderJobs = renderJobs;

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
    showListMessage(list, 'Memuat...');
    try {
      const response = await fetch(new URL('/api/jobs', apiBase()).toString());
      if (!response.ok) throw new Error('Gagal ambil daftar job: ' + response.status);
      renderJobs(list, await response.json());
    } catch (error) {
      showListMessage(list, error.message || error, 'alert error');
    }
  };
})();
