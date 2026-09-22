/* EVKIN ABSENSI v3.1 - utils.js
   Fungsi bantu: parsing tanggal/jam, format, zona waktu. */
(function () {
  const EVKIN = window.EVKIN || (window.EVKIN = {});
  const U = EVKIN.util = {};

  const MONTHS_ID = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];
  const DAYS_ID = ['Minggu','Senin','Selasa','Rabu','Kamis','Jumat','Sabtu'];
  U.MONTHS_ID = MONTHS_ID;
  U.DAYS_ID = DAYS_ID;

  U.pad = (n) => String(n).padStart(2, '0');

  // Excel serial number -> {y,m,d,minutes}
  U.excelSerialToDate = function (serial) {
    const utcDays = Math.floor(serial - 25569);
    const utcValue = utcDays * 86400;
    const d = new Date(utcValue * 1000);
    return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate() };
  };

  // Parse tanggal ke {y,m,d, key:'yyyy-mm-dd', str:'dd/mm/yyyy'} atau null
  U.parseDate = function (v) {
    if (v === null || v === undefined || v === '') return null;
    let y, m, d;
    if (v instanceof Date) {
      y = v.getFullYear(); m = v.getMonth() + 1; d = v.getDate();
    } else if (typeof v === 'number') {
      if (v < 60) return null;
      const r = U.excelSerialToDate(v); y = r.y; m = r.m; d = r.d;
    } else {
      const s = String(v).trim();
      let mt;
      if ((mt = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/))) {
        y = +mt[1]; m = +mt[2]; d = +mt[3];
      } else if ((mt = s.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})/))) {
        d = +mt[1]; m = +mt[2]; y = +mt[3];
      } else if ((mt = s.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{2})$/))) {
        d = +mt[1]; m = +mt[2]; y = 2000 + (+mt[3]);
      } else {
        const dt = new Date(s);
        if (!isNaN(dt.getTime())) { y = dt.getFullYear(); m = dt.getMonth() + 1; d = dt.getDate(); }
        else return null;
      }
    }
    if (!y || !m || !d || m < 1 || m > 12 || d < 1 || d > 31) return null;
    return U.makeDate(y, m, d);
  };

  U.makeDate = function (y, m, d) {
    return {
      y, m, d,
      key: `${y}-${U.pad(m)}-${U.pad(d)}`,
      str: `${U.pad(d)}/${U.pad(m)}/${y}`,
      monthKey: `${y}-${U.pad(m)}`
    };
  };

  // day of week 0=Minggu ... 6=Sabtu
  U.dow = function (dObj) {
    const dt = new Date(Date.UTC(dObj.y, dObj.m - 1, dObj.d));
    return dt.getUTCDay();
  };
  U.dayName = function (dObj) { return DAYS_ID[U.dow(dObj)]; };
  U.isWeekend = function (dObj) { const w = U.dow(dObj); return w === 0 || w === 6; };

  U.addDays = function (dObj, n) {
    const dt = new Date(Date.UTC(dObj.y, dObj.m - 1, dObj.d + n));
    return U.makeDate(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
  };

  // Parse jam -> menit sejak tengah malam, atau null
  U.parseTime = function (v) {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'number') {
      let frac = v;
      if (v >= 1) frac = v - Math.floor(v);
      if (frac === 0 && v >= 1) return null; // tanggal tanpa jam
      let mins = Math.round(frac * 1440);
      if (mins >= 1440) mins -= 1440;
      return mins;
    }
    let s = String(v).trim();
    if (s === '') return null;
    let ampm = null;
    const am = s.match(/(am|pm)$/i);
    if (am) { ampm = am[1].toLowerCase(); s = s.replace(/(am|pm)$/i, '').trim(); }
    let mt;
    let h, mi;
    if ((mt = s.match(/^(\d{1,2})[:.](\d{2})(?::\d{2})?$/))) { h = +mt[1]; mi = +mt[2]; }
    else if ((mt = s.match(/^(\d{2})(\d{2})$/))) { h = +mt[1]; mi = +mt[2]; }
    else if ((mt = s.match(/^(\d{1,2})$/))) { h = +mt[1]; mi = 0; }
    else return null;
    if (ampm === 'pm' && h < 12) h += 12;
    if (ampm === 'am' && h === 12) h = 0;
    if (h > 23 || mi > 59) return null;
    return h * 60 + mi;
  };

  U.fmtTime = function (mins) {
    if (mins === null || mins === undefined || mins === '') return '';
    let m = ((mins % 1440) + 1440) % 1440;
    return `${U.pad(Math.floor(m / 60))}:${U.pad(m % 60)}`;
  };

  // durasi menit (dukung lintas tengah malam)
  U.durationMin = function (masuk, pulang) {
    if (masuk === null || pulang === null) return null;
    let d = pulang - masuk;
    if (d <= 0) d += 1440;
    return d;
  };

  U.fmtDur = function (mins) {
    if (mins === null || mins === undefined) return '';
    const h = Math.floor(mins / 60), m = mins % 60;
    return `${h}j ${U.pad(m)}m`;
  };
  U.hours = (mins) => (mins === null ? null : mins / 60);

  U.fmtRupiah = function (n) {
    n = Math.round(+n || 0);
    return 'Rp' + n.toLocaleString('id-ID');
  };
  U.fmtPct = function (n) { return (Math.round((+n || 0) * 100) / 100) + '%'; };
  U.round2 = function (n) { return Math.round((+n || 0) * 100) / 100; };

  U.monthLabel = function (monthKey) {
    if (!monthKey) return '';
    const [y, m] = monthKey.split('-');
    return `${MONTHS_ID[(+m) - 1]} ${y}`;
  };

  U.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  };

  U.uid = () => 'id' + Math.random().toString(36).slice(2, 9);
})();
