/* EVKIN ABSENSI v3.1 - export-worker.js
   Web Worker untuk export Excel non-blocking.
   Menerima data state dan menghasilkan sheets data siap XLSX.
*/

const FMT = { date: 'dd/mm/yyyy', pct: '0.00"%"', rp: '"Rp"#,##0' };

function num(v) {
  return (v === '' || v === null || v === undefined) ? '' : Number(v);
}

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n) : '';
}

function monthLabel(bulan) {
  const labels = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  return labels[parseInt(bulan) || 0] || '';
}

// maxRows hanya membatasi bila nilainya lebih besar dari nol.
function limitRows(rows, maxRows = 0) {
  return maxRows > 0 ? rows.slice(0, maxRows) : rows;
}

// Listen untuk pesan dari main thread
self.onmessage = function (event) {
  const { action, payload } = event.data;

  if (action === 'buildSheets') {
    const { rawHeaders, raw, daily, rekap, finalData, finalSKP, finalKombinasi, finalCombinedSKP, skipRawData, maxRows } = payload;
    const sheets = {};
    const MAX_ROWS = maxRows || 0;
    const indexByNip = rows => new Map((rows || []).map(row => [String(row.nip), row]));
    const skpByNip = indexByNip(finalSKP.rows);
    const kombinasiByNip = indexByNip(finalKombinasi.rows);
    const combinedSkpByNip = indexByNip(finalCombinedSKP && finalCombinedSKP.skpRows);
    const eabsensiByNip = indexByNip(finalCombinedSKP && finalCombinedSKP.eabsensiRows);
    const esdmByNip = indexByNip(finalCombinedSKP && finalCombinedSKP.esdmRows);

    try {
      // Progress: 0/9
      self.postMessage({ type: 'progress', percent: 10, message: 'Processing DATA SUMBER...' });

      // 1. DATA SUMBER
      const srcHead = rawHeaders.length ? rawHeaders : ['(kosong)'];
      const srcRows = raw.map(r => srcHead.map(h => r[h] !== undefined ? r[h] : ''));
      sheets['DATA SUMBER'] = {
        aoa: [srcHead, ...srcRows],
        formats: null,
        widths: srcHead.map(() => 16)
      };

      // Progress: 1/9
      self.postMessage({ type: 'progress', percent: 20, message: 'Processing HITUNG HARIAN...' });

      // 2. HITUNG HARIAN
      const dH = ['NIP', 'Nama', 'Jabatan', 'Tanggal', 'Hari', 'Jam Masuk', 'Jam Pulang', 'Durasi', 'Zona', 'Jam Normalisasi', 'Metode', 'Jenis Absensi', 'Status Hari Libur', 'Status Cuti', 'Status Duplikasi', 'Absensi Lengkap', 'Pot Keterlambatan', 'Pot Pulang Cepat', 'Pot Durasi', 'Pot Tidak Lengkap', 'Total Potongan Harian', 'Flag', 'Tanggal/Jam Masuk', 'Tanggal/Jam Pulang', 'Status Jadwal', 'Status Absensi'];
      const dailyLimited = limitRows(daily, MAX_ROWS);
      const dRows = dailyLimited.map(x => [x.nip, x.nama, x.jabatan, x.tanggal, x.hari, x.jamMasuk, x.jamPulang, x.durasi, x.zona, x.jamNormalisasi, x.metode, x.jenis, x.statusHariLibur, x.statusCuti, x.statusDuplikasi, x.statusLengkap, num(x.potKeterlambatan), num(x.potPulangCepat), num(x.potDurasi), num(x.potTidakLengkap), num(x.totalHarian), x.flags.join('; '), x.masukAt || '', x.pulangAt || '', x.statusJadwal || '', x.statusAbsensi || '']);
      sheets['HITUNG HARIAN'] = {
        aoa: [dH, ...dRows],
        formats: { 16: FMT.pct, 17: FMT.pct, 18: FMT.pct, 19: FMT.pct, 20: FMT.pct },
        widths: [18, 22, 22, 12, 8, 9, 9, 9, 7, 16, 10, 16, 18, 14, 12, 12, 12, 12, 10, 12, 14, 30, 20, 20, 14, 20]
      };

      // Progress: 2/9
      self.postMessage({ type: 'progress', percent: 30, message: 'Processing SEMI FINAL...' });

      // 4. SEMI FINAL (verifikasi anomali) - diproses lebih awal
      const sfH = ['NIP', 'Nama', 'Tanggal', 'Jam Masuk', 'Jam Pulang', 'Jenis', 'Status Duplikasi', 'Absensi Lengkap', 'Status Hari Libur', 'Status Cuti', 'Flag', 'Total Harian'];
      const sfRows = dailyLimited.filter(x => x.flags.length || x.statusDuplikasi || x.statusLengkap === 'Tidak Lengkap').map(x => [x.nip, x.nama, x.tanggal, x.jamMasuk, x.jamPulang, x.jenis, x.statusDuplikasi, x.statusLengkap, x.statusHariLibur, x.statusCuti, x.flags.join('; '), num(x.totalHarian)]);
      sheets['SEMI FINAL'] = {
        aoa: [sfH, ...(sfRows.length ? sfRows : [['-', 'Tidak ada anomali', '', '', '', '', '', '', '', '', '', '']])],
        formats: { 11: FMT.pct },
        widths: [18, 22, 12, 9, 9, 14, 14, 14, 18, 14, 30, 12]
      };

      // Progress: 3/9
      self.postMessage({ type: 'progress', percent: 40, message: 'Processing REKAP SDM...' });

      // 3. REKAP SDM
      const rH = ['NIP', 'Nama', 'Jabatan', 'Bulan', 'Hari Efektif', 'Hari Ada Absensi', 'Hari Kurang', 'Jumlah Hari Absen', 'Pot Keterlambatan', 'Pot Pulang Cepat', 'Pot Durasi', 'Pot Hari Kurang', 'Pot Tidak Rekam', 'Total Potongan Kehadiran', 'Status'];
      const rRows = rekap.map(x => [x.nip, x.nama, x.jabatan, monthLabel(x.bulan), x.hariEfektif, x.hariAdaAbsensi, x.hariKurang, x.jumlahHariAbsen, num(x.potKeterlambatan), num(x.potPulangCepat), num(x.potDurasi), num(x.potHariKurang), num(x.potTidakLengkap), num(x.total), x.status]);
      sheets['REKAP SDM'] = {
        aoa: [rH, ...rRows],
        formats: { 8: FMT.pct, 9: FMT.pct, 10: FMT.pct, 11: FMT.pct, 12: FMT.pct, 13: FMT.pct },
        widths: [18, 22, 22, 14, 11, 14, 11, 14, 12, 12, 10, 12, 12, 16, 14]
      };

      // Progress: 4/9
      self.postMessage({ type: 'progress', percent: 50, message: 'Processing FINAL ABSENSI...' });

      // 5. FINAL ABSENSI
      const fH = ['NIP', 'Nama', 'Jabatan', 'Bulan', 'Tukin Bruto', 'Komponen Kehadiran 30%', 'Total Potongan Kehadiran %', 'Nominal Potongan Kehadiran', 'FINAL TUKIN DIBAYAR'];
      const fRows = finalData.map(f => [f.nip, f.nama, f.jabatan, monthLabel(f.bulan), money(f.tukin), money(f.komponen), num(f.potPct), money(f.nominal), money(f.finalDibayar)]);
      const totB = finalData.reduce((a, f) => a + (Number(f.tukin) || 0), 0), totN = finalData.reduce((a, f) => a + (Number(f.nominal) || 0), 0), totP = finalData.reduce((a, f) => a + (Number(f.finalDibayar) || 0), 0);
      fRows.push(['', '', '', 'TOTAL', money(totB), '', '', money(totN), money(totP)]);
      sheets['FINAL ABSENSI'] = {
        aoa: [fH, ...fRows],
        formats: { 4: FMT.rp, 5: FMT.rp, 6: FMT.pct, 7: FMT.rp, 8: FMT.rp },
        widths: [18, 22, 22, 14, 16, 20, 20, 22, 20]
      };

      // Progress: 5/9
      self.postMessage({ type: 'progress', percent: 60, message: 'Processing ANOMALI...' });

      // 6. ANOMALI
      const aH = ['NIP', 'Nama', 'Tanggal', 'Jenis Anomali', 'Detail'];
      const aRows = [];
      dailyLimited.forEach(x => { if (x.statusDuplikasi) aRows.push([x.nip, x.nama, x.tanggal, 'Duplikasi NIP+Tanggal', x.jamMasuk + ' - ' + x.jamPulang]); });
      dailyLimited.forEach(x => { if (x.statusLengkap === 'Tidak Lengkap') aRows.push([x.nip, x.nama, x.tanggal, 'Absensi Tidak Lengkap', 'Masuk/Pulang kosong']); });
      sheets['ANOMALI'] = {
        aoa: [aH, ...(aRows.length ? aRows : [['-', 'Tidak ada anomali', '', '', '']])],
        formats: null,
        widths: [18, 22, 12, 22, 40]
      };

      // Progress: 6/9
      self.postMessage({ type: 'progress', percent: 70, message: 'Processing optional sheets...' });

      // 7. FINAL + SKP (opsional)
      if (finalSKP.enabled) {
        const skH = ['NIP', 'Nama', 'Tukin Bruto', 'Nominal Pot Kehadiran', 'Potongan SKP %', 'Nominal Pot SKP', 'FINAL TUKIN DIBAYAR'];
        const skRows = finalData.map(f => {
          const sr = skpByNip.get(String(f.nip)) || { skpPct: 0 };
          const nomSKP = Math.round((Number(f.tukin) || 0) * 0.70 * (Math.min(100, Number(sr.skpPct) || 0) / 100));
          return [f.nip, f.nama, money(f.tukin), money(f.nominal), num(sr.skpPct), money(nomSKP), money((Number(f.tukin) || 0) - (Number(f.nominal) || 0) - nomSKP)];
        });
        sheets['FINAL + SKP'] = {
          aoa: [skH, ...skRows],
          formats: { 2: FMT.rp, 3: FMT.rp, 4: FMT.pct, 5: FMT.rp, 6: FMT.rp },
          widths: [18, 22, 16, 20, 14, 18, 20]
        };
      }

      // 8. FINAL KOMBINASI (opsional)
      if (finalKombinasi.enabled || finalKombinasi.useEabsensi || finalKombinasi.useEsdm) {
        const K = finalKombinasi;
        const kH = ['NIP', 'Nama', 'Aplikasi %', 'e-Absensi %', 'ESDM %', 'Potongan Terpilih %', 'Nominal Potongan', 'FINAL TUKIN DIBAYAR'];
        const kRows = finalData.map(f => {
          const kr = kombinasiByNip.get(String(f.nip)) || { eabs: 0, esdm: 0 };
          const cand = []; if (K.useApp) cand.push(f.potPct); if (K.useEabsensi) cand.push(kr.eabs); if (K.useEsdm) cand.push(kr.esdm);
          const minPct = cand.length ? Math.min(...cand) : 0;
          const nominal = Math.round((Number(f.komponen) || 0) * (Math.min(100, minPct) / 100));
          return [f.nip, f.nama, num(f.potPct), num(kr.eabs), num(kr.esdm), num(minPct), money(nominal), money((Number(f.tukin) || 0) - nominal)];
        });
        sheets['FINAL KOMBINASI'] = {
          aoa: [kH, ...kRows],
          formats: { 2: FMT.pct, 3: FMT.pct, 4: FMT.pct, 5: FMT.pct, 6: FMT.rp, 7: FMT.rp },
          widths: [18, 22, 12, 12, 10, 16, 18, 20]
        };
      }

      // Progress: 7/9
      self.postMessage({ type: 'progress', percent: 80, message: 'Processing FINAL + SKP KOMBINASI...' });

      // 9. FINAL + SKP KOMBINASI (TAB BARU - UTAMA)
      if (finalCombinedSKP && finalCombinedSKP.absensiProcessed) {
        const FC = finalCombinedSKP;
        const fcH = ['NIP', 'Nama', 'Jabatan', 'Tukin Bruto', 'Potongan Absensi % (min)', 'Nominal Potongan Absensi (30%)', 'Potongan SKP %', 'Nominal Potongan SKP (70%)', 'Total Potongan %', 'Total Nominal Potongan', 'FINAL TUKIN DIBAYARKAN'];
        const fcRows = finalData.map(f => {
          const cr = combinedSkpByNip.get(String(f.nip)) || { skpPct: 0 };
          const komKehadiran = f.tukin * 0.30;
          const komKinerja = f.tukin * 0.70;
          // Potongan Absensi (30%) - ambil minimum dari 3 sumber
          const absensiCand = [];
          if (FC.useApp) absensiCand.push(f.potPct);
          if (FC.useEabsensi) {
            const eabsRow = eabsensiByNip.get(String(f.nip));
            if (eabsRow) absensiCand.push(eabsRow.pct);
          }
          if (FC.useEsdm) {
            const esdmRow = esdmByNip.get(String(f.nip));
            if (esdmRow) absensiCand.push(esdmRow.pct);
          }
          const finalAbsensiPct = absensiCand.length ? Math.min(...absensiCand) : f.potPct;
          const nomAbsensi = komKehadiran * (Math.min(100, finalAbsensiPct) / 100);
          // Potongan SKP (70%)
          const skpPct = cr.skpPct;
          const nomSKP = komKinerja * (Math.min(100, skpPct) / 100);
          // Total
          const totalPotPct = Math.round((finalAbsensiPct * 0.30 + skpPct * 0.70) * 100) / 100;
          const totalNominal = nomAbsensi + nomSKP;
          const tukinDibayar = f.tukin - totalNominal;
          return [f.nip, f.nama, f.jabatan, num(f.tukin), num(finalAbsensiPct), num(nomAbsensi), num(skpPct), num(nomSKP), num(totalPotPct), num(totalNominal), num(tukinDibayar)];
        });
        const totBruto = finalData.reduce((a, f) => a + f.tukin, 0);
        const totAbsensiNom = fcRows.reduce((a, r) => a + (r[5] || 0), 0);
        const totSKPNom = fcRows.reduce((a, r) => a + (r[7] || 0), 0);
        const totNominal = fcRows.reduce((a, r) => a + (r[9] || 0), 0);
        const totFinal = fcRows.reduce((a, r) => a + (r[10] || 0), 0);
        fcRows.push(['', '', '', num(totBruto), '', num(totAbsensiNom), '', num(totSKPNom), '', num(totNominal), num(totFinal)]);
        sheets['FINAL + SKP KOMBINASI'] = {
          aoa: [fcH, ...fcRows],
          formats: { 3: FMT.rp, 4: FMT.pct, 5: FMT.rp, 6: FMT.pct, 7: FMT.rp, 8: FMT.pct, 9: FMT.rp, 10: FMT.rp },
          widths: [18, 22, 22, 16, 20, 24, 14, 20, 16, 18, 22]
        };
      }

      // Progress: 8/9 - Done building sheets
      self.postMessage({ type: 'progress', percent: 95, message: 'Finalizing sheets...' });

      // Kembalikan hasil
      self.postMessage({
        type: 'complete',
        sheets: sheets,
        message: 'Sheets built successfully'
      });

    } catch (err) {
      self.postMessage({
        type: 'error',
        message: 'Error building sheets: ' + err.message,
        error: err.toString()
      });
    }
  }
};
