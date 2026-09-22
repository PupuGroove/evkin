/* EVKIN ABSENSI v3.1 - import-advanced.js
   Delegasi import batch ke importMod (terintegrasi dengan workflow utama). */
(function () {
  const EVKIN = window.EVKIN;
  const mod = EVKIN.importAdvancedMod = {};
  const importMod = () => EVKIN.importMod;

  mod.processBatchFile = function (file, onProgress, onComplete) {
    importMod().processFile(file, onProgress)
      .then((stats) => onComplete(null, {
        totalRecords: stats.totalRaw,
        processedCount: stats.totalRecord,
        errorCount: stats.bermasalah,
        batches: Math.ceil(stats.totalRaw / importMod().BATCH_SIZE)
      }))
      .catch((err) => onComplete(err));
  };

  mod.processFile = function (file, onProgress) {
    return importMod().processFile(file, onProgress);
  };
})();
