/* EVKIN ABSENSI v3.1 - export-backend.js
   Browser-side helper untuk export melalui backend Python/FastAPI.
   Tidak menggantikan export worker, tapi menjadi fallback untuk dataset besar.
*/
(function () {
  const EVKIN = window.EVKIN || {};
  EVKIN.exportBackend = EVKIN.exportBackend || {};
  const backend = EVKIN.exportBackend;

  function normalizeApiBase(value) {
    const candidate = String(value || '').trim();
    try {
      const parsed = new URL(candidate || 'http://localhost:8000');
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') throw new Error('Unsupported protocol');
      return parsed.toString().replace(/\/$/, '');
    } catch (error) {
      console.warn('URL backend tidak valid, menggunakan localhost:8000:', candidate);
      return 'http://localhost:8000';
    }
  }

  function resolveApiBase() {
    if (backend.apiBase) return normalizeApiBase(backend.apiBase);
    if (typeof window !== 'undefined' && window.location && window.location.protocol.startsWith('http')) {
      return normalizeApiBase(window.location.origin);
    }
    return 'http://localhost:8000';
  }

  backend.apiBase = resolveApiBase();
  backend.enabled = false;
  backend.syncQueue = Promise.resolve();
  const API_KEY_STORAGE = 'evkin.localApiKey';
  const API_KEY_HEADER = 'X-EVKIN-API-Key';
  const nativeFetch = typeof globalThis.fetch === 'function' ? globalThis.fetch.bind(globalThis) : null;
  const authenticatedOrigins = new Set();

  function storageGet() {
    try { return typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(API_KEY_STORAGE) || '' : ''; }
    catch (_) { return ''; }
  }

  function storageSet(value) {
    try {
      if (typeof sessionStorage === 'undefined') return;
      if (value) sessionStorage.setItem(API_KEY_STORAGE, value);
      else sessionStorage.removeItem(API_KEY_STORAGE);
    } catch (_) { /* Session storage may be disabled by browser policy. */ }
  }

  backend.setApiKey = function (value) {
    backend.apiKey = String(value || '').trim();
    storageSet(backend.apiKey);
  };
  backend.getApiKey = function () { return backend.apiKey || storageGet(); };
  backend.registerAuthenticatedOrigin = function (value) {
    try { authenticatedOrigins.add(new URL(normalizeApiBase(value)).origin); } catch (_) { /* Invalid URLs are rejected elsewhere. */ }
  };
  backend.registerAuthenticatedOrigin(backend.apiBase);

  (function captureApiKeyFromFragment() {
    if (typeof location === 'undefined' || typeof URLSearchParams === 'undefined') return;
    const fragment = new URLSearchParams(String(location.hash || '').replace(/^#/, ''));
    const supplied = fragment.get('evkin-api-key');
    if (!supplied) return;
    backend.setApiKey(supplied);
    fragment.delete('evkin-api-key');
    if (typeof history !== 'undefined' && history.replaceState) {
      const remaining = fragment.toString();
      history.replaceState(null, '', location.pathname + location.search + (remaining ? '#' + remaining : ''));
    }
  })();

  function requestUrl(input) {
    const value = input && typeof input === 'object' && input.url ? input.url : input;
    try {
      const base = typeof location !== 'undefined' && location.href ? location.href : backend.apiBase + '/';
      return new URL(String(value), base);
    } catch (_) { return null; }
  }

  function authenticatedFetch(input, options) {
    if (!nativeFetch) return Promise.reject(new Error('Fetch API tidak tersedia.'));
    const target = requestUrl(input);
    const key = backend.getApiKey();
    if (!target || !key || !authenticatedOrigins.has(target.origin)) return nativeFetch(input, options);
    const next = { ...(options || {}) };
    if (typeof Headers !== 'undefined') {
      const inherited = input && typeof input === 'object' ? input.headers : undefined;
      const headers = new Headers(next.headers || inherited || {});
      if (!headers.has(API_KEY_HEADER)) headers.set(API_KEY_HEADER, key);
      next.headers = headers;
    } else {
      next.headers = { ...((input && input.headers) || {}), ...(next.headers || {}) };
      if (!next.headers[API_KEY_HEADER]) next.headers[API_KEY_HEADER] = key;
    }
    return nativeFetch(input, next);
  }

  backend.apiFetch = authenticatedFetch;
  if (nativeFetch) globalThis.fetch = authenticatedFetch;

  backend.downloadAuthenticated = async function (value) {
    const response = await authenticatedFetch(value, { method: 'GET', cache: 'no-store' });
    if (!response.ok) throw new Error('Download gagal: HTTP ' + response.status);
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    const filename = match ? decodeURIComponent(match[1].replace(/\"$/, '')) : 'download';
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl; anchor.download = filename; anchor.hidden = true;
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
  };

  backend.openAuthenticated = async function (value) {
    const response = await authenticatedFetch(value, { method: 'GET', cache: 'no-store' });
    if (!response.ok) throw new Error('Permintaan gagal: HTTP ' + response.status);
    const objectUrl = URL.createObjectURL(await response.blob());
    window.open(objectUrl, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  };

  if (typeof window !== 'undefined' && typeof window.open === 'function') {
    const nativeOpen = window.open.bind(window);
    window.open = function (value, target, features) {
      const destination = requestUrl(value);
      if (destination && authenticatedOrigins.has(destination.origin) && /^\/(api|analytics|pengembalian)(\/|$)/.test(destination.pathname)) {
        backend.openAuthenticated(destination.toString()).catch(error => {
          if (EVKIN.toast) EVKIN.toast(error.message, 'error');
        });
        return null;
      }
      return nativeOpen(value, target, features);
    };
  }

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('click', event => {
      const anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
      if (!anchor) return;
      const target = requestUrl(anchor.href);
      if (!target || !authenticatedOrigins.has(target.origin) || !/^\/(api|analytics|pengembalian)(\/|$)/.test(target.pathname)) return;
      event.preventDefault();
      backend.downloadAuthenticated(target.toString()).catch(error => {
        if (EVKIN.toast) EVKIN.toast(error.message, 'error');
      });
    }, true);
  }
  backend.isHttpServed = function () {
    return typeof window !== 'undefined' && window.location.protocol.startsWith('http');
  };

  backend.health = async function (apiBase = backend.apiBase) {
    const base = normalizeApiBase(apiBase);
    const response = await fetch(new URL('/health', base).toString(), {
      method: 'GET',
      cache: 'no-store'
    });
    if (!response.ok) throw new Error('Backend merespons dengan status ' + response.status);
    const result = await response.json();
    if (result.status !== 'ok') throw new Error('Status backend tidak valid');
    return result;
  };

  backend.activate = async function (apiBase = backend.apiBase) {
    const requestedBase = normalizeApiBase(apiBase);
    const candidates = [requestedBase];
    if (typeof window !== 'undefined' && window.location && requestedBase === window.location.origin.replace(/\/$/, '')) {
      const localBackend = 'http://127.0.0.1:8000';
      if (!candidates.includes(localBackend)) candidates.push(localBackend);
    }

    let lastError = null;
    for (const candidate of candidates) {
      try {
        await backend.health(candidate);
        backend.apiBase = candidate;
        backend.registerAuthenticatedOrigin(candidate);
        backend.analyticsBase = backend.apiBase.replace(/\/$/, '') + '/analytics';
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) throw lastError;

    let info = null;
    try {
      const response = await fetch(new URL('/api/info', backend.apiBase).toString(), {
        method: 'GET',
        cache: 'no-store'
      });
      if (response.ok) {
        info = await response.json().catch(() => null);
      }
    } catch (err) {
      console.warn('Backend info check failed, assuming non-export backend:', err);
    }

    const hasExportApi = !!(info && (info.service === 'evkin-export-api' || info.frontend_served !== undefined));
    if (!hasExportApi) {
      backend.enabled = false;
      throw new Error('Backend yang terhubung bukan EVKIN export API. Export job tidak tersedia.');
    }

    backend.enabled = true;
    return backend.apiBase;
  };

  backend.syncWorkflow = async function (workflow, apiBase = backend.apiBase) {
    if (EVKIN.deletingAbsensi) throw new Error('Reset sedang berlangsung; sinkronisasi ditunda.');
    const onProgress = arguments.length > 2 && typeof arguments[2] === 'function' ? arguments[2] : null;
    // Capture one immutable snapshot and commit all tables in a single transaction.
    const body = JSON.stringify(workflow || {});
    const write = async () => {
      if (onProgress) onProgress('Workflow', 0, 1);
      const response = await fetch(new URL('/api/workflow/sync', apiBase), {
        method:'POST', headers:{'Content-Type':'application/json'}, body,
        signal:AbortSignal.timeout(300000)
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      if (onProgress) onProgress('Workflow', 1, 1);
      return result;
    };
    const result = backend.syncQueue.then(write, write);
    backend.syncQueue = result.catch(() => undefined);
    return result;
  };

  async function syncTable(source, rows, replace, apiBase) {
    const response = await fetch(new URL('/api/workflow/sync-table', normalizeApiBase(apiBase)).toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, rows, replace }),
      signal: AbortSignal.timeout(60000)
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Sinkronisasi tabel ke backend gagal: ' + source);
    }
    return response.json();
  }

  // Expose syncTable for direct use by import flow
  backend.syncTable = syncTable;

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
      a.remove();
    }, 1200);
  }

  EVKIN.exportBackend.downloadFinalExcel = async function (opts = {}) {
    const {
      bulan = '2026-08',
      unit = null,
      smartMode = false,
      apiBase = backend.apiBase
    } = opts;

    const url = new URL('/api/export/final', apiBase);
    url.searchParams.set('bulan', bulan);
    if (unit) url.searchParams.set('unit', unit);
    url.searchParams.set('smart_mode', String(Boolean(smartMode)));

    const response = await fetch(url.toString(), {
      method: 'POST'
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Export backend gagal');
    }

    const blob = await response.blob();
    const filename = `EVKIN_FINAL_${bulan}_${smartMode ? 'SMART' : 'FULL'}.xlsx`;
    triggerDownload(blob, filename);
    return { ok: true, filename };
  };

  EVKIN.exportBackend.downloadWorkbook = async function (opts = {}) {
    const {
      bulan = '2026-08',
      unit = null,
      sheetNames = ['HITUNG HARIAN', 'REKAP SDM', 'FINAL ABSENSI'],
      apiBase = backend.apiBase
    } = opts;

    const url = new URL('/api/export/workbook', apiBase);
    url.searchParams.set('bulan', bulan);
    if (unit) url.searchParams.set('unit', unit);
    if (sheetNames && sheetNames.length) {
      url.searchParams.set('sheet_names', sheetNames.join(','));
    }

    const response = await fetch(url.toString(), {
      method: 'POST'
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Export workbook gagal');
    }

    const blob = await response.blob();
    triggerDownload(blob, `EVKIN_EXPORT_${bulan}.xlsx`);
    return { ok: true, filename: `EVKIN_EXPORT_${bulan}.xlsx` };
  };

  EVKIN.exportBackend.seedDemoData = async function (apiBase = backend.apiBase) {
    const response = await fetch(new URL('/api/export/seed-demo', apiBase).toString(), {
      method: 'POST'
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'Seed demo data gagal');
    }
    return response.json();
  };

  // Background export job APIs: create job, poll status, download result
  backend.finalManifest = async function (rows) {
    const values = rows.map(row => {
      const nip = String(row.nip || '').trim();
      if (!nip) throw new Error('NIP Final kosong');
      return [nip, ...['tukin', 'nominal', 'finalDibayar'].map(key => {
        if (row[key] == null || row[key] === '' || !Number.isFinite(Number(row[key]))) throw new Error('Nominal Final belum lengkap');
        const amount = Number(row[key]);
        return String(Math.sign(amount) * Math.round(Math.abs(amount)));
      })];
    });
    const input = values.map(row => JSON.stringify(row)).sort().join('\n');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
    const sum = i => values.reduce((total, row) => total + BigInt(row[i]), 0n).toString();
    return {row_count: values.length, unique_nip: new Set(values.map(row => row[0])).size,
      gross: sum(1), deduction: sum(2), paid: sum(3),
      sha256: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')};
  };

  EVKIN.exportBackend.createExportJob = async function (opts = {}) {
    const { bulan = '2026-08', unit = null, sheetNames = [], format = 'xlsx', apiBase = backend.apiBase } = opts;
    const url = new URL('/api/jobs/export', apiBase);
    const response = await fetch(url.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bulan, unit, sheet_names: sheetNames, format, expected_final: opts.expectedFinal }),
      signal: AbortSignal.timeout(30000)
    });
    if (!response.ok) {
      const text = await response.text().catch(() => '<no body>');
      throw new Error('Create export job failed: ' + (text || response.status));
    }
    return response.json();
  };

  EVKIN.exportBackend.pollJob = async function (jobId, opts = {}) {
    const { apiBase = backend.apiBase, intervalMs = 2000, onProgress = null, timeoutMs = 60 * 60 * 1000 } = opts;
    const start = Date.now();
    const url = new URL('/api/jobs/' + jobId, apiBase).toString();
    while (true) {
      const resp = await fetch(url, { method: 'GET', cache: 'no-store', signal: AbortSignal.timeout(30000) });
      if (!resp.ok) {
        const text = await resp.text().catch(() => '<no body>');
        throw new Error('Polling job failed: ' + text);
      }
      const json = await resp.json();
      if (onProgress && typeof onProgress === 'function') {
        try { onProgress(json.progress || 0, json.message || json.status); } catch (e) { /* ignore */ }
      }
      if (json.status === 'finished') return json;
      if (json.status === 'failed' || json.status === 'cancelled') throw new Error('Job ' + json.status + ': ' + (json.message || ''));
      if (Date.now() - start > timeoutMs) throw new Error('Job polling timeout');
      await new Promise(r => setTimeout(r, intervalMs));
    }
  };

  EVKIN.exportBackend.downloadJobResult = async function (jobId, opts = {}) {
    const { apiBase = backend.apiBase } = opts;
    const url = new URL('/api/jobs/' + jobId + '/download', apiBase).toString();
    const resp = await fetch(url, { method: 'GET' });
    if (!resp.ok) {
      const text = await resp.text().catch(() => '<no body>');
      throw new Error('Download job result failed: ' + text);
    }
    const blob = await resp.blob();
    const disp = resp.headers.get('content-disposition') || '';
    let filename = 'evkin_export_' + jobId;
    const m = /filename="?([^";]+)"?/.exec(disp);
    if (m) filename = m[1];
    triggerDownload(blob, filename);
    return { ok: true, filename };
  };

  EVKIN.exportBackend.startExportJob = async function (opts = {}, onProgress = null) {
    const create = await EVKIN.exportBackend.createExportJob(opts);
    const jobId = create.job_id || create.jobId || create.id;
    if (!jobId) throw new Error('Invalid job id from server');
    const pol = await EVKIN.exportBackend.pollJob(jobId, { apiBase: opts.apiBase || backend.apiBase, onProgress });
    // when finished, download
    return EVKIN.exportBackend.downloadJobResult(jobId, { apiBase: opts.apiBase || backend.apiBase });
  };


  // Lightweight mark: avoid resending the full workflow payload when only the semifinal verified flag changes.
  EVKIN.exportBackend.markSemifinalVerified = async function (opts = {}) {
    const { bulan = '2026-08', verified = true, apiBase = backend.apiBase, timeoutMs = 8000 } = opts;
    const url = new URL('/api/workflow/mark-semifinal', apiBase);
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url.toString(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bulan, verified }),
        signal: controller.signal
      });
      clearTimeout(id);
      if (!response.ok) {
        const text = await response.text().catch(() => '<no body>');
        console.error('markSemifinalVerified failed', url.toString(), 'status', response.status, 'body:', text);
        throw new Error(text || 'Gagal menandai verifikasi semifinal di backend');
      }
      return response.json();
    } catch (err) {
      clearTimeout(id);
      // Normalize abort error for clearer messaging
      if (err && err.name === 'AbortError') {
        console.warn('markSemifinalVerified: request aborted after timeout', timeoutMs);
        throw new Error('Timeout saat menandai verifikasi semifinal ke backend');
      }
      console.error('markSemifinalVerified network/error:', err);
      throw err;
    }
  };

  // Analytics helpers (use analytics mounted under /analytics on same backend or standalone service)
  backend.analyticsBase = backend.apiBase + '/analytics';

  EVKIN.exportBackend.getWorkflowFlags = async function (bulan = null, apiBase = null) {
    // Try main API path first (/api/workflow/flags), then analytics sub-app if available.
    // Missing or partial backend responses should not surface as a red frontend "Server error"
    // because the workflow can still continue without the flag metadata being present.
    const mainBase = backend.apiBase;
    const analyticsBase = backend.analyticsBase || (backend.apiBase + '/analytics');
    const tryUrls = [];
    tryUrls.push(new URL('/api/workflow/flags', mainBase).toString());
    tryUrls.push(new URL('workflow/flags', analyticsBase.replace(/\/$/, '') + '/').toString());

    let lastErr = null;
    for (const u of tryUrls) {
      const url = new URL(u);
      if (bulan) url.searchParams.set('bulan', bulan);
      try {
        const response = await fetch(url.toString(), { method: 'GET' });
        if (!response.ok) {
          const text = await response.text().catch(() => '<no body>');
          console.warn('Failed to fetch workflow flags from', url.toString(), 'status', response.status, 'body:', text);
          lastErr = new Error('HTTP ' + response.status + ': ' + text);
          continue;
        }
        const data = await response.json().catch(async () => {
          const raw = await response.text().catch(() => '<no body>');
          console.warn('Invalid JSON from workflow flags endpoint', url.toString(), raw);
          return null;
        });
        if (!data) {
          lastErr = new Error('Invalid JSON in response from ' + url.toString());
          continue;
        }
        return data;
      } catch (err) {
        console.warn('Network/error fetching workflow flags from', url.toString(), err);
        lastErr = err;
        continue;
      }
    }

    const fallback = { status: 'ok', flags: {} };
    if (lastErr) console.warn('getWorkflowFlags: all attempts failed; returning empty flag set:', lastErr);
    return fallback;
  };

  EVKIN.exportBackend.getStatsCounts = async function (bulan = null, apiBase = backend.analyticsBase) {
    const url = new URL('stats/counts', apiBase.replace(/\/$/, '') + '/');
    if (bulan) url.searchParams.set('bulan', bulan);
    try {
      const response = await fetch(url.toString(), { method: 'GET' });
      if (!response.ok) {
        const text = await response.text().catch(() => '<no body>');
        console.error('getStatsCounts failed', url.toString(), 'status', response.status, 'body:', text);
        throw new Error('Gagal ambil stats: ' + response.status + ' - ' + text);
      }
      return response.json();
    } catch (err) {
      console.error('getStatsCounts network/error:', err);
      throw err;
    }
  };

  EVKIN.exportBackend.downloadAggregatesCSV = async function (tipe = 'per-unit', bulan = null, unit = null, apiBase = backend.analyticsBase) {
    const url = new URL('export/aggregates', apiBase.replace(/\/$/, '') + '/');
    url.searchParams.set('tipe', tipe);
    if (bulan) url.searchParams.set('bulan', bulan);
    if (unit) url.searchParams.set('unit', unit);
    const response = await fetch(url.toString(), { method: 'GET' });
    if (!response.ok) {
      const text = await response.text().catch(() => '<no body>');
      console.error('downloadAggregatesCSV failed', url.toString(), 'status', response.status, 'body:', text);
      throw new Error(text || 'Gagal download aggregates');
    }
    const blob = await response.blob();
    const filename = `evkin_aggregates_${tipe}_${(unit?unit+'_' : '')}${bulan || 'all'}.csv`;
    triggerDownload(blob, filename);
    return { ok: true, filename };
  };

  // Lightweight connectivity test endpoint used by UI to verify network/backend reachability.
  EVKIN.exportBackend.testConnectivity = async function (apiBase = backend.apiBase, timeoutMs = 5000) {
    const mainPing = new URL('/api/ping', backend.apiBase).toString();
    const analyticsBase = backend.analyticsBase || (backend.apiBase + '/analytics');
    const analyticsPing = new URL('ping', analyticsBase.replace(/\/$/, '') + '/').toString();
    const tryUrls = [mainPing, analyticsPing];
    let lastErr = null;
    for (const u of tryUrls) {
      try {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeoutMs);
        const resp = await fetch(u, { method: 'GET', cache: 'no-store', signal: controller.signal });
        clearTimeout(id);
        if (!resp.ok) {
          const text = await resp.text().catch(() => '<no body>');
          console.error('testConnectivity failed', u, 'status', resp.status, 'body:', text);
          lastErr = new Error('HTTP ' + resp.status + ': ' + text);
          continue;
        }
        const data = await resp.json().catch(async () => {
          const raw = await resp.text().catch(() => '<no body>');
          console.error('testConnectivity invalid json from', u, 'body:', raw);
          return null;
        });
        if (!data) {
          lastErr = new Error('Invalid JSON from ' + u);
          continue;
        }
        return { ok: true, url: u, data };
      } catch (err) {
        console.error('testConnectivity network/error for', u, err && err.name ? err.name : err);
        lastErr = err;
        continue;
      }
    }
    console.error('testConnectivity: all attempts failed', lastErr);
    throw lastErr || new Error('Tidak bisa menghubungi backend');
  };

})();
