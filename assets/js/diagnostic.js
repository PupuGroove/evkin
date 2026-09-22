// EVKIN ABSENSI v1.5 - Diagnostic Script
// Paste this in Browser Console (F12 → Console) and run to diagnose the issue

console.log('=== EVKIN EXPORT DIAGNOSTIC ===\n');

// 1. Check State
console.log('1. CHECK STATE DATA:');
console.log('   S.raw.length:', EVKIN.state.raw ? EVKIN.state.raw.length : 0);
console.log('   S.daily.length:', EVKIN.state.daily ? EVKIN.state.daily.length : 0);
console.log('   S.rekap.length:', EVKIN.state.rekap ? EVKIN.state.rekap.length : 0);
console.log('   S.final.length:', EVKIN.state.final ? EVKIN.state.final.length : 0);

// 2. Check Database
console.log('\n2. CHECK DATABASE:');
(async () => {
  try {
    const raw = await EVKIN.db.getAll('raw_import');
    const daily = await EVKIN.db.getAll('daily_data');
    const rekap = await EVKIN.db.getAll('rekap_sdm');
    const final = await EVKIN.db.getAll('final_absensi');

    console.log('   DB raw_import:', raw.length);
    console.log('   DB daily_data:', daily.length);
    console.log('   DB rekap_sdm:', rekap.length);
    console.log('   DB final_absensi:', final.length);

    // 3. Check Backend
    console.log('\n3. CHECK BACKEND:');
    try {
      const health = await fetch('http://localhost:8000/api/health');
      const result = await health.json();
      console.log('   Backend status:', result.status);
      console.log('   ✓ Backend tersedia');
    } catch (e) {
      console.log('   ✗ Backend tidak tersedia:', e.message);
    }

    // 4. Check Export Module
    console.log('\n4. CHECK EXPORT MODULE:');
    console.log('   mod.smartExport exists:', typeof EVKIN.exportMod.smartExport === 'function');
    console.log('   mod.saveAllToDatabase exists:', typeof EVKIN.exportMod.saveAllToDatabase === 'function');
    console.log('   mod.processWithWorker exists:', typeof EVKIN.exportMod.processWithWorker === 'function');
    console.log('   mod.downloadViaBackend exists:', typeof EVKIN.exportMod.downloadViaBackend === 'function');

    // 5. Summary
    console.log('\n5. SUMMARY:');
    console.log('   Data state:', (EVKIN.state.daily && EVKIN.state.daily.length > 0) ? '✓ OK' : '✗ KOSONG');
    console.log('   Data database:', (daily.length > 0) ? '✓ OK' : '✗ KOSONG');
    console.log('   Backend:', (health.ok) ? '✓ OK' : '✗ ERROR');
    console.log('   Export functions:', (typeof EVKIN.exportMod.smartExport === 'function') ? '✓ OK' : '✗ ERROR');

    console.log('\n=== DIAGNOSTIK SELESAI ===');
    console.log('\nAction items:');
    if (!EVKIN.state.daily || EVKIN.state.daily.length === 0) {
      console.log('❌ State kosong → Jalankan Hitung Harian dulu');
    }
    if (daily.length === 0) {
      console.log('❌ Database kosong → Click ① Simpan ke Database');
    }
    if (typeof EVKIN.exportMod.smartExport !== 'function') {
      console.log('❌ Export functions error → Refresh browser (Ctrl+Shift+R)');
    }
  } catch (err) {
    console.error('ERROR:', err);
  }
})();
