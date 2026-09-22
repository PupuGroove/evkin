(function () {
  const EVKIN = window.EVKIN || (window.EVKIN = {});

  function toNumber(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string') {
      const s = value.replace(/[^0-9,.-]/g, '').replace(/,/g, '');
      if (s === '' || s === '-' || s === '.') return 0;
      const n = Number(s);
      return Number.isFinite(n) ? n : 0;
    }
    return Number(value) || 0;
  }

  function roundValue(raw, unit, method) {
    const q = raw / unit;
    if (method === 'floor') return Math.floor(q) * unit;
    if (method === 'ceil') return Math.ceil(q) * unit;
    return Math.round(q) * unit;
  }

  function parseNumeric(value) {
    if (value === null || value === undefined || value === '') return 0;
    if (typeof value === 'number') return value;
    let s = String(value).trim().replace(/Rp/gi, '').replace(/\s/g, '');
    if (s.includes('.') && s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
    else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
    else if (s.includes(',')) s = s.replace(',', '.');
    return Number(s) || 0;
  }

  function buildResult(rows, valueColumn, unit, method) {
    const result = rows.map((row, i) => {
      const original = Math.round(parseNumeric(row[valueColumn]));
      const rounded = Math.round(roundValue(original, unit, method));
      return {
        no: i + 1,
        raw: { ...row },
        original,
        rounded,
        correction: 0,
        final: rounded,
        fraction: (original / unit) - Math.floor(original / unit)
      };
    });

    const total = result.reduce((sum, x) => sum + x.original, 0);
    const initial = result.reduce((sum, x) => sum + x.rounded, 0);
    let residual = Math.round((total - initial) * 100) / 100;
    let steps = Math.round(residual / unit);

    if (Math.abs(residual - steps * unit) < 0.01 && result.length) {
      if (steps > 0) {
        [...result].sort((a, b) => b.fraction - a.fraction).forEach((x, j) => {
          if (j < steps) x.correction += unit;
        });
        for (let j = result.length; j < steps; j++) {
          result[j % result.length].correction += unit;
        }
      } else if (steps < 0) {
        const n = Math.abs(steps);
        [...result].sort((a, b) => a.fraction - b.fraction).forEach((x, j) => {
          if (j < n) x.correction -= unit;
        });
        for (let j = result.length; j < n; j++) {
          result[j % result.length].correction -= unit;
        }
      }
    }

    result.forEach((x) => {
      x.final = x.rounded + x.correction;
    });

    const finalTotal = result.reduce((sum, x) => sum + x.final, 0);
    const diff = Math.round(total - finalTotal);
    if (diff !== 0 && result.length) {
      result[result.length - 1].correction += diff;
      result[result.length - 1].final += diff;
    }

    result.forEach((x) => {
      x.original = Math.round(x.original);
      x.rounded = Math.round(x.rounded);
      x.correction = Math.round(x.correction);
      x.final = Math.round(x.final);
    });

    return {
      result,
      total,
      initial,
      correction: result.reduce((sum, x) => sum + x.correction, 0),
      final: result.reduce((sum, x) => sum + x.final, 0)
    };
  }

  function formatRupiah(value) {
    return new Intl.NumberFormat('id-ID', {
      style: 'currency',
      currency: 'IDR',
      maximumFractionDigits: 0
    }).format(Number(value) || 0);
  }

  function readWorkbook(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = function (event) {
        try {
          const wb = XLSX.read(new Uint8Array(event.target.result), { type: 'array' });
          const sheetName = wb.SheetNames[0];
          const ws = wb.Sheets[sheetName];
          const data = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' });
          if (!data || data.length < 2) {
            throw new Error('File Excel kosong atau tidak memiliki data.');
          }
          const headers = data[0].map((h) => String(h || ''));
          const rows = data.slice(1).map((row) => {
            const obj = {};
            headers.forEach((header, index) => {
              obj[header] = row[index] ?? '';
            });
            return obj;
          });
          resolve({ headers, rows, sheetName, fileName: file.name.replace(/\.(xlsx|xls)$/i, '') });
        } catch (error) {
          reject(error);
        }
      };
      reader.onerror = function () {
        reject(new Error('Gagal membaca file Excel.'));
      };
      reader.readAsArrayBuffer(file);
    });
  }

  function createCell(value) {
    const td = document.createElement('td');
    td.textContent = value === null || value === undefined ? '' : String(value);
    return td;
  }

  function renderPreviewTable(container, headers, resultRows) {
    container.innerHTML = '';
    if (!resultRows || !resultRows.length) {
      container.innerHTML = '<div class="muted">Belum ada preview hasil.</div>';
      return;
    }

    const rowValues = resultRows.map((item) => (item && item.raw ? item.raw : item));
    const baseHeaders = headers && headers.length ? headers : Object.keys(rowValues[0] || {});
    const extraHeaders = Object.keys(rowValues[0] || {}).filter((key) => !baseHeaders.includes(key));
    const allHeaders = [...baseHeaders, ...extraHeaders];

    const table = document.createElement('table');
    table.className = 'tool-table';
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    allHeaders.forEach((header) => {
      const th = document.createElement('th');
      th.textContent = header;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rowValues.forEach((row) => {
      const tr = document.createElement('tr');
      allHeaders.forEach((header) => {
        const value = row[header];
        tr.appendChild(createCell(value === null || value === undefined ? '' : value));
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  EVKIN.pembulatanBackend = {
    baseUrl: 'http://localhost:9101',
    enabled: false,
    async check() {
      try {
        const res = await fetch(this.baseUrl + '/health', { cache: 'no-store' });
        if (!res.ok) throw new Error('Backend tidak merespons');
        const data = await res.json();
        this.enabled = !!(data && data.status === 'ok');
        return this.enabled;
      } catch (error) {
        this.enabled = false;
        return false;
      }
    },
    async process(payload) {
      const res = await fetch(this.baseUrl + '/api/pembulatan/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch (error) { throw new Error('Respons backend tidak valid'); }
      if (!res.ok) {
        throw new Error((data && data.detail) || 'Gagal memproses di backend');
      }
      return data;
    }
  };

  EVKIN.pembulatanMod = {
    render: function (container) {
      container.innerHTML = '';
      const context = {
        fileName: 'BNBA',
        headers: [],
        rows: [],
        result: [],
        selectedColumn: '',
        selectedColumns: []
      };

      const wrap = document.createElement('div');
      wrap.className = 'mod-wrap';

      const header = document.createElement('div');
      header.className = 'module-head';
      header.innerHTML = '<div><h2>Rekonsiliasi Pembulatan Tukin @dio</h2><p class="muted">Import Excel BNBA, bulatkan nominal, distribusikan selisih secara otomatis, dan pastikan total akhir tetap sama dengan total sumber.</p></div>';
      wrap.appendChild(header);

      const cardImport = document.createElement('div');
      cardImport.className = 'card';
      cardImport.innerHTML = '<h3>1. Import Data BNBA</h3>';

      const fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.accept = '.xlsx,.xls';

      const info = document.createElement('div');
      info.className = 'muted';
      info.style.marginTop = '8px';
      info.textContent = 'Belum ada file Excel yang dipilih.';

      const toolGrid = document.createElement('div');
      toolGrid.className = 'tool-grid';
      toolGrid.style.marginTop = '12px';

      const colWrap = document.createElement('div');
      colWrap.innerHTML = '<label>Kolom Nominal Tukin</label>';
      const valueCol = document.createElement('select');
      valueCol.multiple = true;
      valueCol.size = 6;
      valueCol.style.width = '100%';
      valueCol.style.marginTop = '6px';
      valueCol.style.padding = '10px';
      valueCol.style.border = '1px solid #ccd3dd';
      valueCol.style.borderRadius = '8px';
      valueCol.style.background = '#fff';
      valueCol.style.color = '#1a2433';
      valueCol.style.minHeight = '120px';
      colWrap.appendChild(valueCol);

      const unitWrap = document.createElement('div');
      unitWrap.innerHTML = '<label>Kelipatan Pembulatan</label>';
      const unitSel = document.createElement('select');
      [1, 10, 100, 1000, 10000, 100000].forEach((u) => {
        const option = document.createElement('option');
        option.value = String(u);
        option.textContent = 'Rp' + u.toLocaleString('id-ID');
        if (u === 1000) option.selected = true;
        unitSel.appendChild(option);
      });
      unitWrap.appendChild(unitSel);

      const methodWrap = document.createElement('div');
      methodWrap.innerHTML = '<label>Metode</label>';
      const methodSel = document.createElement('select');
      [
        ['nearest', 'Terdekat'],
        ['floor', 'Ke bawah'],
        ['ceil', 'Ke atas']
      ].forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        if (value === 'nearest') option.selected = true;
        methodSel.appendChild(option);
      });
      methodWrap.appendChild(methodSel);

      toolGrid.appendChild(colWrap);
      toolGrid.appendChild(unitWrap);
      toolGrid.appendChild(methodWrap);

      const actionRow = document.createElement('div');
      actionRow.className = 'actions-row';
      const backendStatus = document.createElement('span');
      backendStatus.className = 'pill gray';
      backendStatus.textContent = 'Backend terpisah: tidak aktif';
      backendStatus.style.marginRight = '8px';
      const btnBackendToggle = document.createElement('button');
      btnBackendToggle.type = 'button';
      btnBackendToggle.className = 'btn btn-secondary';
      btnBackendToggle.textContent = 'Cek Backend Terpisah';
      const btnProcess = document.createElement('button');
      btnProcess.type = 'button';
      btnProcess.className = 'btn btn-primary';
      btnProcess.textContent = 'PROSES REKONSILIASI';
      const btnDownload = document.createElement('button');
      btnDownload.type = 'button';
      btnDownload.className = 'btn btn-success';
      btnDownload.textContent = 'DOWNLOAD BNBA FINAL (.XLSX)';
      actionRow.appendChild(backendStatus);
      actionRow.appendChild(btnBackendToggle);
      actionRow.appendChild(btnProcess);
      actionRow.appendChild(btnDownload);

      const note = document.createElement('div');
      note.className = 'tool-note';
      note.style.marginTop = '12px';
      note.innerHTML = '<b>Catatan:</b> seluruh nominal Tukin/BNBA diproses sebagai <b>rupiah bulat tanpa desimal</b>. Jika sumber memiliki desimal, sistem membulatkan ke rupiah terdekat terlebih dahulu.<br><b>Aturan:</b> seluruh kolom asli tetap dipertahankan. Sistem menambahkan kolom Pembulatan Awal, Koreksi Rekonsiliasi, Tukin Final, dan Status. Koreksi dilakukan agar <b>Total Tukin Final − Total Tukin Awal = Rp0</b>.';

      cardImport.appendChild(fileInput);
      cardImport.appendChild(info);
      cardImport.appendChild(toolGrid);
      cardImport.appendChild(actionRow);
      cardImport.appendChild(note);
      wrap.appendChild(cardImport);

      const cardStats = document.createElement('div');
      cardStats.className = 'card';
      cardStats.innerHTML = '<h3>2. Kontrol Rekonsiliasi</h3>';

      const statsGrid = document.createElement('div');
      statsGrid.className = 'tool-stats';
      const statMeta = [
        { id: 'awal', label: 'Total Tukin Awal' },
        { id: 'bulat', label: 'Total Pembulatan Awal' },
        { id: 'koreksi', label: 'Total Koreksi' },
        { id: 'final', label: 'Total Tukin Final' },
        { id: 'selisih', label: 'SELISIH' }
      ];
      statMeta.forEach((stat) => {
        const item = document.createElement('div');
        item.className = 'tool-stat';
        item.innerHTML = '<span class="label">' + stat.label + '</span><span class="value" id="' + stat.id + '">Rp0</span>';
        statsGrid.appendChild(item);
      });
      const statusText = document.createElement('p');
      statusText.id = 'pembulatan-status';
      statusText.className = 'muted';
      statusText.style.marginTop = '12px';
      statusText.textContent = 'Belum ada data yang diproses.';
      cardStats.appendChild(statsGrid);
      cardStats.appendChild(statusText);
      wrap.appendChild(cardStats);

      const cardPreview = document.createElement('div');
      cardPreview.className = 'card';
      cardPreview.innerHTML = '<h3>3. Preview BNBA</h3>';
      const previewWrap = document.createElement('div');
      previewWrap.className = 'tool-table-wrap';
      cardPreview.appendChild(previewWrap);
      wrap.appendChild(cardPreview);

      function normalizeHeader(value) {
        return String(value ?? '').replace(/\uFEFF/g, '').trim();
      }

      function guessNominalColumns(headers) {
        const normalized = headers.map((header) => normalizeHeader(header)).filter(Boolean);
        const guessed = normalized.filter((header) => /tukin|nominal|jumlah|dibayar|nilai|pembayaran/i.test(header));
        if (guessed.length) return guessed;
        const fallback = normalized.filter((header) => !/^no\.?\s*$/i.test(header));
        return fallback.length ? [fallback[0]] : normalized;
      }

      function updateValueColumnOptions(headers) {
        const normalizedHeaders = headers.map((header) => normalizeHeader(header)).filter(Boolean);
        valueCol.innerHTML = '';

        const guessed = guessNominalColumns(normalizedHeaders);
        normalizedHeaders.forEach((header, index) => {
          const option = document.createElement('option');
          option.value = header;
          option.textContent = header;
          const defaultSelected = guessed.includes(header) || (!guessed.length && index === normalizedHeaders.length - 1);
          option.selected = defaultSelected;
          valueCol.appendChild(option);
        });

        valueCol.size = Math.min(Math.max(4, normalizedHeaders.length), 12);
        if (!normalizedHeaders.length) {
          context.selectedColumns = [];
          return;
        }

        const selected = Array.from(valueCol.options).filter((option) => option.selected).map((option) => option.value);
        if (!selected.length) {
          valueCol.options[0].selected = true;
        }
        context.selectedColumns = Array.from(valueCol.selectedOptions).map((option) => option.value);
      }

      function getSelectedColumns() {
        const selected = Array.from(valueCol.selectedOptions).map((option) => option.value);
        if (selected.length) return selected;
        if (valueCol.options.length) return [valueCol.options[0].value];
        return [];
      }

      function renderStats(total, initial, correction, final, diff) {
        document.getElementById('awal').textContent = formatRupiah(total);
        document.getElementById('bulat').textContent = formatRupiah(initial);
        document.getElementById('koreksi').textContent = (correction >= 0 ? '+' : '') + formatRupiah(correction);
        document.getElementById('final').textContent = formatRupiah(final);
        document.getElementById('selisih').textContent = formatRupiah(diff);

        const statusNode = document.getElementById('pembulatan-status');
        statusNode.className = Math.abs(diff) < 0.01 ? 'ok' : 'bad';
        statusNode.textContent = Math.abs(diff) < 0.01
          ? '✓ REKONSILIASI VALID — Total awal dan total final sama persis.'
          : '⚠ REKONSILIASI BELUM 0 — periksa data.';
      }

      fileInput.addEventListener('change', async function (event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;
        try {
          const parsed = await readWorkbook(file);
          context.fileName = parsed.fileName;
          context.headers = parsed.headers;
          context.rows = parsed.rows;
          info.textContent = `${file.name} | Sheet: ${parsed.sheetName} | ${parsed.rows.length.toLocaleString('id-ID')} baris`;
          updateValueColumnOptions(context.headers);
          statusText.textContent = 'File siap diproses.';
        } catch (error) {
          context.headers = [];
          context.rows = [];
          info.textContent = error.message;
          statusText.textContent = 'File gagal dibaca.';
        }
      });

      async function runComputation() {
        if (!context.rows.length) {
          statusText.textContent = 'Import file Excel terlebih dahulu.';
          return;
        }
        const selectedColumns = getSelectedColumns();
        if (!selectedColumns.length) {
          statusText.textContent = 'Pilih minimal satu kolom nominal untuk diproses.';
          return;
        }
        const unit = Number(unitSel.value || 1000);
        const method = methodSel.value || 'nearest';

        try {
          if (EVKIN.pembulatanBackend.enabled) {
            btnProcess.disabled = true;
            statusText.textContent = 'Menghitung via backend terpisah...';
            const payload = { rows: context.rows, selectedColumns, unit, method };
            const data = await EVKIN.pembulatanBackend.process(payload);
            context.result = data.rows || [];
            const diff = Math.round((data.final || 0) - (data.total || 0));
            renderPreviewTable(previewWrap, context.headers, context.result);
            renderStats(data.total || 0, data.initial || 0, data.correction || 0, data.final || 0, diff);
            statusText.textContent = 'Hitung selesai via backend terpisah.';
            btnProcess.disabled = false;
            return;
          }

          let rows = context.rows.map((row) => ({ ...row }));
          const totals = selectedColumns.reduce((acc, column) => {
            const parsed = buildResult(rows, column, unit, method);
            parsed.result.forEach((item) => {
              const row = rows[item.no - 1];
              row[`${column}_Pembulatan_Awal`] = item.rounded;
              row[`${column}_Koreksi_Rekonsiliasi`] = item.correction;
              row[`${column}_Tukin_Final`] = item.final;
              row[`${column}_Status_Rekonsiliasi`] = Math.abs(item.final - item.original) < 0.01 ? 'Sama' : 'Dikoreksi';
            });
            acc.total += parsed.total;
            acc.initial += parsed.initial;
            acc.correction += parsed.correction;
            acc.final += parsed.final;
            return acc;
          }, { total: 0, initial: 0, correction: 0, final: 0 });
          context.result = rows;
          const diff = Math.round(totals.final - totals.total);
          renderPreviewTable(previewWrap, context.headers, rows);
          renderStats(totals.total, totals.initial, totals.correction, totals.final, diff);
          statusText.textContent = 'Hitung selesai secara lokal.';
        } catch (error) {
          statusText.textContent = error.message || 'Gagal memproses pembulatan.';
        } finally {
          btnProcess.disabled = false;
        }
      }

      btnBackendToggle.addEventListener('click', async function () {
        try {
          const ok = await EVKIN.pembulatanBackend.check();
          if (ok) {
            backendStatus.className = 'pill green';
            backendStatus.textContent = 'Backend terpisah: aktif';
            statusText.textContent = 'Backend terpisah tersedia. Proses akan memakai server terpisah.';
          } else {
            backendStatus.className = 'pill gray';
            backendStatus.textContent = 'Backend terpisah: tidak aktif';
            statusText.textContent = 'Backend terpisah tidak tersedia; fallback ke proses lokal.';
          }
        } catch (error) {
          backendStatus.className = 'pill gray';
          backendStatus.textContent = 'Backend terpisah: tidak aktif';
          statusText.textContent = 'Backend terpisah tidak tersedia; fallback ke proses lokal.';
        }
      });

      btnProcess.addEventListener('click', runComputation);

      btnDownload.addEventListener('click', function () {
        if (!context.result.length) {
          statusText.textContent = 'Tidak ada hasil rekonsiliasi untuk diunduh.';
          return;
        }

        const exportRows = (context.result || []).map((item) => {
          const base = item && item.raw ? { ...item.raw } : { ...item };
          if (item && item.raw) {
            Object.keys(item).forEach((key) => {
              if (!['no', 'raw', 'original', 'rounded', 'correction', 'final', 'fraction'].includes(key)) {
                base[key] = item[key];
              }
            });
          }
          return base;
        });
        const ws = XLSX.utils.json_to_sheet(exportRows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, 'BNBA_Final');
        XLSX.writeFile(wb, `${context.fileName || 'BNBA'}_final.xlsx`);
        statusText.textContent = 'File Excel hasil pembulatan siap diunduh.';
      });

      container.appendChild(wrap);
      EVKIN.pembulatanBackend.check().then((ok) => {
        if (ok) {
          backendStatus.className = 'pill green';
          backendStatus.textContent = 'Backend terpisah: aktif';
        } else {
          backendStatus.className = 'pill gray';
          backendStatus.textContent = 'Backend terpisah: tidak aktif';
        }
      });
    }
  };
})();