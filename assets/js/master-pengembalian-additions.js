// Auxiliary handlers added for Master Pengembalian (separate file to avoid merge conflicts)
(function(){
  const EVKIN = window.EVKIN;

  function appendCell(row, value, tagName) {
    const cell = document.createElement(tagName || 'td');
    cell.textContent = value == null ? '' : String(value);
    row.appendChild(cell);
    return cell;
  }

  function createTable(headers) {
    const wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    const table = document.createElement('table');
    table.className = 'data-table';
    const headRow = document.createElement('tr');
    headers.forEach(header => appendCell(headRow, header, 'th'));
    const thead = document.createElement('thead');
    thead.appendChild(headRow);
    const tbody = document.createElement('tbody');
    table.append(thead, tbody);
    wrap.appendChild(table);
    return { wrap, tbody };
  }

  function renderCaseList(container, rows) {
    const { wrap, tbody } = createTable(['case_id', 'nip', 'periode']);
    (rows || []).forEach(item => {
      const row = document.createElement('tr');
      appendCell(row, item.case_id);
      appendCell(row, item.nip);
      appendCell(row, item.periode);
      row.addEventListener('click', () => {
        document.getElementById('rd_case_id').value = item.case_id == null ? '' : String(item.case_id);
        showDasar(item.case_id);
      });
      tbody.appendChild(row);
    });
    container.replaceChildren(wrap);
  }

  function renderDasarList(container, caseId, rows) {
    const heading = document.createElement('h4');
    heading.textContent = 'Dasar untuk ' + String(caseId == null ? '' : caseId);
    const { wrap, tbody } = createTable(['id', 'periode', 'komponen', 'nilai_awal', 'nilai_dasar', 'nominal_pengembalian', 'aksi']);
    (rows || []).forEach(item => {
      const row = document.createElement('tr');
      [item.id, item.periode, item.komponen, item.nilai_awal, item.nilai_dasar, item.nominal_pengembalian].forEach(value => appendCell(row, value));
      const actionCell = appendCell(row, '');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-secondary';
      button.textContent = 'Buat Penyesuaian';
      button.addEventListener('click', () => openPenyesuaianFormWithRow(caseId, item));
      actionCell.appendChild(button);
      tbody.appendChild(row);
    });
    container.replaceChildren(heading, wrap);
  }

  // review dasar button
  document.addEventListener('click', function(e){
    if (!e.target) return;
    if (e.target.id === 'mpReviewDasar') {
      const cont = document.getElementById('mpContent');
      cont.innerHTML = `<h3>Review Dasar Perhitungan</h3>
        <div class="form-row"><div><label>Case ID</label><input id="rd_case_id" placeholder="Masukkan case_id atau pilih dari daftar"/></div>
        <div style="align-self:flex-end"><button id="rd_pick" class="btn btn-secondary">Pilih Case</button></div></div>
        <div><button id="rd_list_cases" class="btn btn-secondary">Tampilkan Daftar Case</button></div>
        <div id="rdResult"></div>`;
      document.getElementById('rd_pick').onclick = async function(){ const cid = document.getElementById('rd_case_id').value; if(cid) { showDasar(cid); } };
      document.getElementById('rd_list_cases').onclick = async function(){ const cont2 = document.getElementById('rdResult'); cont2.innerHTML = '<p>Memuat daftar case...</p>'; try{ if(!EVKIN.exportBackend||!EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif'); const res = await fetch(new URL('/api/pengembalian/cases', EVKIN.exportBackend.apiBase).toString()); const j = await res.json(); renderCaseList(cont2, j.rows || []); }catch(err){ cont2.innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>'; } };
    }
    if (e.target && e.target.id === 'mpCreatePenyesuaian') {
      // open blank penyesuaian form
      EVKIN.go('master-pengembalian');
      openBlankPenyesuaianForm();
    }
  });

  async function showDasar(case_id){ const cont2 = document.getElementById('rdResult'); cont2.innerHTML = '<p>Mengambil dasar perhitungan...</p>'; try{ if(!EVKIN.exportBackend||!EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif'); const res = await fetch(new URL('/api/pengembalian/dasar/'+encodeURIComponent(case_id), EVKIN.exportBackend.apiBase).toString()); if(!res.ok) throw new Error('Gagal ambil dasar'); const j = await res.json(); const rows = j.rows||[]; if(!rows.length){ cont2.innerHTML = '<div class="alert info">Tidak ada dasar perhitungan</div>'; return; } renderDasarList(cont2, case_id, rows); }catch(err){ cont2.innerHTML = '<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>'; } }

  function openPenyesuaianFormWithRow(case_id, row) {
    const cont = document.getElementById('mpContent');
    cont.innerHTML = `<h3>Buat Penyesuaian — Case ${EVKIN.util.esc(case_id)}</h3>
      <div class="form-row"><div><label>Case ID</label><input id="py_case_id" value="${EVKIN.util.esc(case_id)}" readonly/></div><div><label>NIP</label><input id="py_nip" value="${EVKIN.util.esc(row.nip || '')}"/></div></div>
      <div class="form-row"><div><label>Periode</label><input id="py_periode" value="${EVKIN.util.esc(row.periode || '')}"/></div><div><label>Komponen</label><input id="py_komponen" value="${EVKIN.util.esc(row.komponen || '')}"/></div></div>
      <div class="form-row"><div><label>Nominal Sebelum</label><input id="py_sebelum" value="${EVKIN.util.esc(row.nilai_awal || '')}"/></div><div><label>Nominal Setelah</label><input id="py_setelah" value=""/></div></div>
      <div class="form-row"><div><label>Selisih</label><input id="py_selisih" readonly/></div><div><label>Jenis Penyesuaian</label><select id="py_jenis"><option>ABSENSI</option><option>WITA</option><option>WIT</option><option>TENDIK</option><option>SP2D</option><option>CUTI</option><option>IZIN</option><option>SKP</option><option>MANUAL</option><option>LAINNYA</option></select></div></div>
      <div class="form-row"><div style="flex:2"><label>Alasan</label><input id="py_alasan"/></div><div style="align-self:flex-end"><button id="py_submit" class="btn btn-primary">Kirim Penyesuaian</button></div></div>`;
    const sebelum = document.getElementById('py_sebelum'); const setelah = document.getElementById('py_setelah'); const sel = document.getElementById('py_selisih'); function recalc(){ const a=parseFloat(sebelum.value)||0; const b=parseFloat(setelah.value)||0; sel.value=(b-a).toString(); } setelah.oninput=recalc; document.getElementById('py_submit').onclick=async function(){ const payload=[{ case_id:document.getElementById('py_case_id').value, nip:document.getElementById('py_nip').value, periode:document.getElementById('py_periode').value, komponen:document.getElementById('py_komponen').value, nominal_sebelum:parseFloat(document.getElementById('py_sebelum').value)||0, nominal_setelah:parseFloat(document.getElementById('py_setelah').value)||0, selisih:parseFloat(document.getElementById('py_selisih').value)||0, jenis_penyesuaian:document.getElementById('py_jenis').value, alasan_penyesuaian:document.getElementById('py_alasan').value, reference_id:'REF-'+Date.now() }]; try{ if(!EVKIN.exportBackend||!EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif'); const res=await fetch(new URL('/pengembalian/penyesuaian',EVKIN.exportBackend.apiBase).toString(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:payload,created_by:(EVKIN.user&&EVKIN.user.username)?EVKIN.user.username:'ui'})}); const j=await res.json(); if(!res.ok) throw new Error(j.detail||'Gagal kirim penyesuaian'); const inserted=Number(j.inserted)||0; cont.innerHTML='<div class="alert success">Penyesuaian terkirim. '+(inserted?inserted+' baris':'')+'</div>'; }catch(err){ cont.innerHTML='<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>'; } }

  }

  function openBlankPenyesuaianForm(){ const cont = document.getElementById('mpContent'); cont.innerHTML = `<h3>Buat Penyesuaian Baru</h3>
    <div class="form-row"><div><label>Case ID</label><input id="py_case_id"/></div><div><label>NIP</label><input id="py_nip"/></div></div>
    <div class="form-row"><div><label>Periode</label><input id="py_periode"/></div><div><label>Komponen</label><input id="py_komponen" value="TUKIN"/></div></div>
    <div class="form-row"><div><label>Nominal Sebelum</label><input id="py_sebelum"/></div><div><label>Nominal Setelah</label><input id="py_setelah"/></div></div>
    <div class="form-row"><div><label>Selisih</label><input id="py_selisih" readonly/></div><div><label>Jenis Penyesuaian</label><select id="py_jenis"><option>ABSENSI</option><option>WITA</option><option>WIT</option><option>TENDIK</option><option>SP2D</option><option>CUTI</option><option>IZIN</option><option>SKP</option><option>MANUAL</option><option>LAINNYA</option></select></div></div>
    <div class="form-row"><div style="flex:2"><label>Alasan</label><input id="py_alasan"/></div><div style="align-self:flex-end"><button id="py_submit" class="btn btn-primary">Kirim Penyesuaian</button></div></div>`;
  const sebelum = document.getElementById('py_sebelum'); const setelah = document.getElementById('py_setelah'); const sel = document.getElementById('py_selisih'); function recalc(){ const a=parseFloat(sebelum.value)||0; const b=parseFloat(setelah.value)||0; sel.value=(b-a).toString(); } setelah.oninput=recalc; document.getElementById('py_submit').onclick=async function(){ const payload=[{ case_id:document.getElementById('py_case_id').value, nip:document.getElementById('py_nip').value, periode:document.getElementById('py_periode').value, komponen:document.getElementById('py_komponen').value, nominal_sebelum:parseFloat(document.getElementById('py_sebelum').value)||0, nominal_setelah:parseFloat(document.getElementById('py_setelah').value)||0, selisih:parseFloat(document.getElementById('py_selisih').value)||0, jenis_penyesuaian:document.getElementById('py_jenis').value, alasan_penyesuaian:document.getElementById('py_alasan').value, reference_id:'REF-'+Date.now() }]; try{ if(!EVKIN.exportBackend||!EVKIN.exportBackend.enabled) throw new Error('Backend tidak aktif'); const res=await fetch(new URL('/pengembalian/penyesuaian',EVKIN.exportBackend.apiBase).toString(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:payload,created_by:(EVKIN.user&&EVKIN.user.username)?EVKIN.user.username:'ui'})}); const j=await res.json(); if(!res.ok) throw new Error(j.detail||'Gagal kirim penyesuaian'); const inserted=Number(j.inserted)||0; document.getElementById('mpContent').innerHTML='<div class="alert success">Penyesuaian terkirim. '+(inserted?inserted+' baris':'')+'</div>'; }catch(err){ document.getElementById('mpContent').innerHTML='<div class="alert error">'+EVKIN.util.esc(err.message)+'</div>'; } } }
})();
