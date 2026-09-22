/* EVKIN ABSENSI v3.1 - import-worker.js
   Web Worker untuk batch processing import data */

// Listener untuk messages dari main thread
self.onmessage = function (e) {
  const { action, data, batchSize, startIndex } = e.data;

  if (action === 'processBatch') {
    const { aoa, headers, colMap, batchSize, batchIndex } = data;

    const startIdx = batchIndex * batchSize;
    const endIdx = Math.min(startIdx + batchSize, aoa.length);
    const batchRows = aoa.slice(startIdx, endIdx);

    const processed = [];
    let errorCount = 0;

    batchRows.forEach((row, idx) => {
      try {
        const get = (f) => (colMap[f] !== undefined ? row[colMap[f]] : '');

        const nip = String(get('nip') || '').trim();
        const nama = String(get('nama') || '').trim();
        const jabatan = String(get('jabatan') || '').trim();
        const tglStr = String(get('tanggal') || '').trim();
        const masukStr = String(get('jamMasuk') || '').trim();
        const pulangStr = String(get('jamPulang') || '').trim();
        const zona = String(get('zona') || '').trim();
        const provinsi = String(get('provinsi') || '').trim();
        const kabupaten = String(get('kabupaten') || '').trim();
        const jenis = String(get('jenis') || '').trim();

        // Basic validation
        const issues = [];
        if (!nip) issues.push('NIP kosong');
        if (!tglStr) issues.push('Tanggal kosong');
        if (!masukStr) issues.push('Jam masuk kosong');
        if (!pulangStr) issues.push('Jam pulang kosong');

        if (issues.length === 0) {
          processed.push({
            nip, nama, jabatan, tglStr, masukStr, pulangStr,
            zona, provinsi, kabupaten, jenis,
            raw: Object.fromEntries(headers.map((h, i) => [h, row[i]]))
          });
        } else {
          errorCount++;
        }
      } catch (err) {
        errorCount++;
      }
    });

    // Send result back to main thread
    self.postMessage({
      action: 'batchProcessed',
      batchIndex,
      processed,
      errorCount,
      totalProcessed: processed.length,
      isComplete: endIdx >= aoa.length
    });
  }
};
