/* EVKIN ABSENSI v3.1 - evkin-db.js
   IndexedDB wrapper for large dataset storage using Dexie-like patterns.
   This keeps the app compatible with local file:// environments.
*/
(function () {
  const dbName = 'EVKIN_ABSENSI_DB';
  const DB_VERSION = 4;

  function openDB() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(dbName, DB_VERSION);
      request.onupgradeneeded = (event) => {
        const db = event.target.result;
        // Define stores with keyPath that allows auto-indexing
        // Since data objects have no 'id', use autoIncrement only (no keyPath)
        const stores = [
          'master_data',
          'workflow_config',
          'raw_import',
          'daily_data',
          'rekap_sdm',
          'final_absensi',
          'final_skp',
          'final_kombinasi',
          'final_combined_skp'
        ];
        stores.forEach((storeName) => {
          if (!db.objectStoreNames.contains(storeName)) {
            // Remove keyPath requirement - let IndexedDB auto-generate keys
            db.createObjectStore(storeName, { autoIncrement: true });
          }
        });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('Gagal membuka IndexedDB'));
    });
  }

  function transaction(db, storeName, mode = 'readwrite') {
    return db.transaction(storeName, mode).objectStore(storeName);
  }

  const EVKIN = window.EVKIN || {};
  EVKIN.db = {
    async putMany(storeName, rows) {
      if (!rows || !rows.length) return true;
      const db = await openDB();
      const store = transaction(db, storeName, 'readwrite');
      return new Promise((resolve, reject) => {
        const requests = rows.map((row) => {
          const payload = typeof row === 'object' && row !== null ? { ...row } : row;
          const request = store.put(payload);
          request.onerror = () => reject(request.error || new Error('Put gagal'));
          return request;
        });
        Promise.allSettled(requests).then(() => resolve(true)).catch(reject);
      });
    },

    async replaceStore(storeName, rows) {
      const db = await openDB();
      const tx = db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      return new Promise((resolve, reject) => {
        const request = store.clear();
        request.onsuccess = () => {
          if (!rows || !rows.length) {
            tx.oncomplete = () => resolve(true);
            return;
          }
          let pending = rows.length;
          rows.forEach((row) => {
            const payload = typeof row === 'object' && row !== null ? { ...row } : row;
            const putReq = store.put(payload);
            putReq.onsuccess = () => {
              pending -= 1;
              if (pending === 0) tx.oncomplete = () => resolve(true);
            };
            putReq.onerror = () => reject(putReq.error || new Error('Replace gagal'));
          });
        };
        request.onerror = () => reject(request.error || new Error('Clear gagal'));
      });
    },

    async getAll(storeName) {
      const db = await openDB();
      const store = transaction(db, storeName, 'readonly');
      return new Promise((resolve, reject) => {
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error || new Error('GetAll gagal'));
      });
    },

    async clear(storeName) {
      const db = await openDB();
      const store = transaction(db, storeName, 'readwrite');
      return new Promise((resolve, reject) => {
        const request = store.clear();
        request.onsuccess = () => resolve(true);
        request.onerror = () => reject(request.error || new Error('Clear gagal'));
      });
    },

    async saveMasterData(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('master_data', rows);
    },

    async saveConfig(config) {
      return this.replaceStore('workflow_config', config ? [config] : []);
    },

    async saveRaw(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('raw_import', rows);
    },

    async saveDaily(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('daily_data', rows);
    },

    async saveRekap(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('rekap_sdm', rows);
    },

    async saveFinal(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('final_absensi', rows);
    },

    async saveFinalSKP(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('final_skp', rows);
    },

    async saveFinalKombinasi(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('final_kombinasi', rows);
    },

    async saveFinalCombinedSKP(rows) {
      if (!rows || !rows.length) return true;
      return this.replaceStore('final_combined_skp', rows);
    },

    async getMasterData() {
      return this.getAll('master_data');
    },

    async getRekap() {
      return this.getAll('rekap_sdm');
    },

    async getFinal() {
      return this.getAll('final_absensi');
    },

    async resetDatabase() {
      return new Promise((resolve, reject) => {
        const request = indexedDB.deleteDatabase(dbName);
        request.onsuccess = () => resolve(true);
        request.onerror = () => reject(request.error || new Error('Gagal reset database'));
        request.onblocked = () => console.warn('Reset database terblokir oleh tab lain');
      });
    }
  };
})();
