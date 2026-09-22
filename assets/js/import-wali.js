/* Import khusus Absensi Wali Asuh/Wali Asrama. */
(function () {
  const EVKIN = window.EVKIN;
  const U = EVKIN.util;
  const M = EVKIN.master;
  const S = EVKIN.state;
  const mod = EVKIN.waliImportMod = {};
  const REQUIRED = ['tglfinger', 'nmpeg', 'nip', 'jnshadir', 'nmjabatan', 'absenpagi', 'absensore'];

  function norm(value) { return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }
  function cellValue(value) {
    const text = String(value == null ? '' : value).trim();
    return /^null$/i.test(text) ? '' : text;
  }
  function dateTimeMinutes(date, time) {
    return Math.floor(Date.UTC(date.y, date.m - 1, date.d) / 60000) + time;
  }
  function rawRow(headers, row) {
    const result = {};
    headers.forEach((header, index) => {
      const key = header || ('Kolom' + (index + 1));
      if (!['latitude', 'longitude', 'latitudesore', 'longitudesore', 'latitudepulang', 'longitudepulang'].includes(norm(key))) {
        result[key] = row[index];
      }
    });
    return result;
  }
  function dateValue(value, fallback) { return U.parseDate(value) || fallback; }

  function parseCsvLine(line) {
    const row = [];
    let value = '';
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') { value += '"'; i++; }
        else quoted = !quoted;
      } else if (ch === ',' && !quoted) {
        row.push(value);
        value = '';
      } else {
        value += ch;
      }
    }
    row.push(value);
    return row;
  }

  function processCsvStream(file, onProgress) {
    return new Promise((resolve, reject) => {
      const chunkSize = 4 * 1024 * 1024;
      const batchSize = 2000;
      const decoder = new TextDecoder('utf-8');
      const raw = [];
      let rawBatch = [];
      const events = [];
      const seenRows = new Set();
      let duplicateSourceRows = 0;
      let invalidCount = 0;
      let headers = null;
      let pending = '';
      let offset = 0;
      let rowIndex = 0;

      async function flushRawBatch() { rawBatch = []; }

      async function consume(text, final) {
        pending += text;
        const lines = pending.split(/\r?\n/);
        pending = final ? '' : lines.pop();
        lines.forEach((line) => {
          if (!line.trim()) return;
          const row = parseCsvLine(line).map(cellValue);
          if (!headers) {
            headers = row.map((value) => String(value).trim().replace(/^"+|"+$/g, ''));
            return;
          }
          const index = {};
          headers.forEach((header, i) => { index[norm(header)] = i; });
          const sourceRow = rawRow(headers, row);
          raw.push(sourceRow);
          rawBatch.push(sourceRow);
          const rowKey = row.join('\u001f');
          if (seenRows.has(rowKey)) { duplicateSourceRows++; rowIndex++; return; }
          seenRows.add(rowKey);
          const nip = cellValue(row[index.nip]);
          const nama = cellValue(row[index.nmpeg]);
          const jabatan = cellValue(row[index.jabatan]) || cellValue(row[index.nmjabatan]);
          const date = U.parseDate(cellValue(row[index.tglfinger]));
          const masukDate = dateValue(index.tanggalmasuk === undefined ? '' : row[index.tanggalmasuk], date);
          const pulangDate = dateValue(index.tanggalpulang === undefined ? '' : row[index.tanggalpulang], date);
          const masukValue = cellValue(row[index.absenpagi]);
          const pulangValue = cellValue(row[index.absensore]);
          const masuk = U.parseTime(masukValue);
          const pulang = U.parseTime(pulangValue);
          const issues = [];
          if (!nip) issues.push('NIP kosong');
          if (!date) issues.push('Tanggal tidak valid');
          if (masukValue !== '' && masuk === null) issues.push('Jam masuk tidak valid');
          if (pulangValue !== '' && pulang === null) issues.push('Jam pulang tidak valid');
          if (nip && masukDate && masuk !== null) events.push({ direction: 'in', date: masukDate, time: masuk, nip, nama, jabatan, rowIndex, issues });
          if (nip && pulangDate && pulang !== null) events.push({ direction: 'out', date: pulangDate, time: pulang, nip, nama, jabatan, rowIndex, issues });
          if (nip && (masukDate || pulangDate) && masuk === null && pulang === null) {
            events.push({direction:'empty',date:masukDate || pulangDate,time:0,nip,nama,jabatan,rowIndex,issues});
          }
          if (!nip || (!masukDate && !pulangDate)) invalidCount++;
          rowIndex++;
        });
        if (rawBatch.length >= batchSize) await flushRawBatch();
      }

      async function readNext() {
        if (offset >= file.size) {
          await consume(decoder.decode(), true);
          await flushRawBatch();
          if (!headers) return reject(new Error('File CSV kosong.'));
          const missing = REQUIRED.filter((header) => !headers.some((value) => norm(value) === header));
          if (missing.length) {
            return reject(new Error('Header Absensi Wali tidak sesuai. Kolom wajib hilang: ' + missing.join(', ')));
          }
          const data = mergeSameWorkDate(buildRecords(events));
          const totalSourceRows = rowIndex;
          if (totalSourceRows > 0 && data.length === 0) {
            return reject(new Error('CSV terbaca, tetapi tidak ditemukan event waktu yang valid. Periksa format tanggal dan jam pada tgl_finger, absen_pagi, atau absen_sore.'));
          }
          const result = stats(data, totalSourceRows, invalidCount, duplicateSourceRows);
          await EVKIN.importMod.applyImportResult(headers, raw, data, result, 'wali');
          return resolve(result);
        }
        const end = Math.min(offset + chunkSize, file.size);
        const reader = new FileReader();
        reader.onload = async (event) => {
          try {
          await consume(decoder.decode(event.target.result, { stream: end < file.size }), false);
          offset = end;
          if (onProgress) onProgress({ progress: Math.round(offset / file.size * 100), processedCount: rowIndex, totalRecords: 0, currentBatch: 1, totalBatches: 1 });
          setTimeout(readNext, 0);
          } catch (error) {
            reject(error);
          }
        };
        reader.onerror = () => reject(new Error('Gagal membaca CSV pada byte ' + offset + '.'));
        reader.readAsUint8Array ? reader.readAsUint8Array(file.slice(offset, end)) : reader.readAsArrayBuffer(file.slice(offset, end));
      }
      readNext();
    });
  }

  function parseRows(aoa) {
    if (!aoa || aoa.length < 2) throw new Error('File kosong atau tidak memiliki data.');
    const headers = aoa[0].map(value => String(value).trim());
    const indexes = {};
    headers.forEach((header, index) => { indexes[norm(header)] = index; });
    const missing = REQUIRED.filter(header => indexes[header] === undefined);
    if (missing.length) throw new Error('Header Absensi Wali tidak sesuai. Kolom wajib hilang: ' + missing.join(', '));
    const raw = [];
    const events = [];
    let invalidCount = 0;
    const seenRows = new Set();
    let duplicateSourceRows = 0;
    aoa.slice(1).forEach((row, rowIndex) => {
      if (!row.some(value => String(value == null ? '' : value).trim() !== '')) return;
      raw.push(rawRow(headers, row));
      const rowKey = row.map(value => String(value == null ? '' : value).trim()).join('\u001f');
      if (seenRows.has(rowKey)) { duplicateSourceRows++; return; }
      seenRows.add(rowKey);
      const nip = String(row[indexes.nip] || '').trim();
      const nama = String(row[indexes.nmpeg] || '').trim();
      const jabatan = String(row[indexes.jabatan] || '').trim() || String(row[indexes.nmjabatan] || '').trim();
      const fingerDate = U.parseDate(row[indexes.tglfinger]);
      const masukDate = indexes.tanggalmasuk === undefined
        ? fingerDate
        : dateValue(row[indexes.tanggalmasuk], fingerDate);
      const pulangDate = indexes.tanggalpulang === undefined
        ? fingerDate
        : dateValue(row[indexes.tanggalpulang], fingerDate);
      const masuk = U.parseTime(row[indexes.absenpagi]);
      const pulang = U.parseTime(row[indexes.absensore]);
      const issues = [];
      if (!nip) issues.push('NIP kosong');
      if (!masukDate && !pulangDate) issues.push('Tanggal tidak valid');
      if (row[indexes.absenpagi] !== '' && masuk === null) issues.push('Jam masuk tidak valid');
      if (row[indexes.absensore] !== '' && pulang === null) issues.push('Jam pulang tidak valid');
      if (nip && masukDate && masuk !== null) events.push({ direction: 'in', date: masukDate, time: masuk, nip, nama, jabatan, rowIndex, issues });
      if (nip && pulangDate && pulang !== null) events.push({ direction: 'out', date: pulangDate, time: pulang, nip, nama, jabatan, rowIndex, issues });
      if (!nip || (!masukDate && !pulangDate)) {
        invalidCount++;
        return;
      }
      if (masuk === null && pulang === null) {
        events.push({ direction: 'empty', date: masukDate || pulangDate, time: 0, nip, nama, jabatan, rowIndex, issues });
      }
    });
    return { headers, raw, events, invalidCount, duplicateSourceRows };
  }

  function makeRecord(event, paired, issues) {
    const date = event.date;
    const pulangDate = paired ? paired.date : null;
    const off = M.detectZone('', '');
    const record = {
      _id: U.uid(), nip: event.nip, nama: event.nama, jabatan: event.jabatan,
      tanggal: date, tanggalPulang: pulangDate ? pulangDate.str : '',
      tanggalMasukObj: date, tanggalPulangObj: pulangDate,
      masukMin: event.direction === 'in' ? event.time : null,
      pulangMin: paired ? paired.time : (event.direction === 'out' ? event.time : null),
      masukNormMin: event.direction === 'in' ? event.time : null,
      pulangNormMin: paired ? paired.time : (event.direction === 'out' ? event.time : null),
      masukNormMinAdd: event.direction === 'in' ? event.time : null,
      pulangNormMinAdd: paired ? paired.time : (event.direction === 'out' ? event.time : null),
      provinsi: '', kabupaten: '', zona: off, jenis: 'Bekerja di Kantor',
      crossDay: !!(paired && pulangDate.key !== date.key),
      shiftFlag: paired ? (pulangDate.key !== date.key ? 'SHIFT LINTAS HARI' : 'SHIFT NORMAL') : (event.direction === 'out' ? 'ABSEN PULANG TANPA MASUK' : 'ABSEN MASUK TANPA PULANG'),
      issues: (issues || []).concat(event.issues || [])
        .concat(event.direction === 'in' && !paired ? ['Jam pulang kosong'] : [])
        .concat(event.direction === 'out' ? ['Jam masuk kosong'] : []),
      dupFlag: false, deleted: false, sourceFormat: 'wali'
    };
    record.masukAt = record.masukMin === null ? '' : date.key + 'T' + U.fmtTime(record.masukMin);
    record.pulangAt = record.pulangMin === null ? '' : (pulangDate || date).key + 'T' + U.fmtTime(record.pulangMin);
    return record;
  }

  function buildRecords(events) {
    const byNip = {};
    events.forEach(event => { (byNip[event.nip] || (byNip[event.nip] = [])).push(event); });
    const records = [];
    Object.keys(byNip).forEach(nip => {
      byNip[nip].filter(event => event.direction === 'empty').forEach(event => records.push(makeRecord(event, null, ['Jam masuk dan pulang kosong'])));
      const list = byNip[nip].filter(event => event.direction !== 'invalid' && event.direction !== 'empty').sort((a, b) => dateTimeMinutes(a.date, a.time) - dateTimeMinutes(b.date, b.time));
      for (let index = 0; index < list.length;) {
        const event = list[index];
        const next = list[index + 1];
        const elapsed = next
          ? dateTimeMinutes(next.date, next.time) - dateTimeMinutes(event.date, event.time)
          : null;
        const paired = next && elapsed >= 0 && elapsed <= 18 * 60 ? next : null;
        // The source columns are not reliable shift directions: a late
        // absen_sore can be the actual clock-in for a night shift.
        const masukEvent = Object.assign({}, event, { direction: 'in' });
        records.push(makeRecord(masukEvent, paired));
        index += paired ? 2 : 1;
      }
    });
    return records.sort((a, b) => a.tanggal.key.localeCompare(b.tanggal.key) || String(a.nip).localeCompare(String(b.nip)));
  }

  function mergeSameWorkDate(records) {
    const groups = {};
    records.forEach(record => {
      const key = record.nip + '|' + record.tanggal.key;
      const current = groups[key];
      if (!current) {
        groups[key] = record;
        return;
      }
      if (current.masukMin === null && record.masukMin !== null) {
        current.masukMin = record.masukMin;
        current.masukAt = record.masukAt;
        current.tanggalMasukObj = record.tanggalMasukObj;
      } else if (record.masukMin !== null && current.masukMin !== null && record.masukMin < current.masukMin) {
        current.masukMin = record.masukMin;
        current.masukAt = record.masukAt;
        current.tanggalMasukObj = record.tanggalMasukObj;
      }
      if (current.pulangMin === null && record.pulangMin !== null) {
        current.pulangMin = record.pulangMin;
        current.pulangAt = record.pulangAt;
        current.tanggalPulangObj = record.tanggalPulangObj;
      } else if (record.pulangMin !== null && record.pulangAt > current.pulangAt) {
        current.pulangMin = record.pulangMin;
        current.pulangAt = record.pulangAt;
        current.tanggalPulangObj = record.tanggalPulangObj;
      }
      current.tanggalPulang = current.tanggalPulangObj ? current.tanggalPulangObj.str : '';
      current.crossDay = !!(current.tanggalPulangObj && current.tanggalPulangObj.key !== current.tanggal.key);
      current.shiftFlag = current.crossDay ? 'SHIFT LINTAS HARI' : (current.masukMin !== null && current.pulangMin !== null ? 'SHIFT NORMAL' : 'DATA TIDAK LENGKAP');
      current.issues = [];
      if (current.masukMin === null) current.issues.push('Jam masuk kosong');
      if (current.pulangMin === null) current.issues.push('Jam pulang kosong');
    });
    return Object.keys(groups).map(key => groups[key])
      .sort((a, b) => a.tanggal.key.localeCompare(b.tanggal.key) || String(a.nip).localeCompare(String(b.nip)));
  }

  function stats(data, totalRaw, invalidCount, duplicateSourceRows) {
    const keys = data.map(row => row.tanggal.key).sort();
    return {
      totalRaw, totalRecord: data.length, totalSDM: new Set(data.map(row => row.nip)).size,
      rentang: keys.length ? keys[0] + ' s/d ' + keys[keys.length - 1] : '-',
      valid: data.filter(row => !row.issues.length).length,
      bermasalah: invalidCount + data.filter(row => row.issues.length).length,
      rejectedRows: invalidCount,
      dupGroups: 0, duplicateSourceRows: duplicateSourceRows || 0,
      crossDay: data.filter(row => row.crossDay).length,
      months: Array.from(new Set(data.map(row => row.tanggal.monthKey))).sort()
    };
  }

  mod.processAoa = function (aoa) {
    const parsed = parseRows(aoa);
    const data = mergeSameWorkDate(buildRecords(parsed.events));
    const result = stats(data, parsed.raw.length, parsed.invalidCount, parsed.duplicateSourceRows);
    return EVKIN.importMod.applyImportResult(parsed.headers, parsed.raw, data, result, 'wali');
  };
  mod.restoreRecords = function (raw) {
    if (!raw.length) return [];
    const headers = Object.keys(raw[0]);
    const parsed = parseRows([headers, ...raw.map(row => headers.map(key => row[key]))]);
    return mergeSameWorkDate(buildRecords(parsed.events));
  };
  mod.processFile = function (file, onProgress) {
    if (/\.csv$/i.test(file && file.name || '')) return processCsvStream(file, onProgress);
    return new Promise((resolve, reject) => {
      EVKIN.importMod.handleFile(file, (error, aoa) => {
        if (error) return reject(error);
        try {
          if (onProgress) onProgress({ progress: 100, processedCount: aoa.length - 1, totalRecords: aoa.length - 1, currentBatch: 1, totalBatches: 1 });
          resolve(mod.processAoa(aoa));
        } catch (error) { reject(error); }
      });
    });
  };
})();
