/* EVKIN ABSENSI v3.1 - data.js
   Data master bawaan: hari libur 2026, peta zona provinsi, master jabatan. */
(function () {
  const EVKIN = window.EVKIN || (window.EVKIN = {});
  const D = EVKIN.master = {};

  // Hari libur nasional & cuti bersama 2026 (BAWAAN - dapat diedit administrator).
  // Format: 'yyyy-mm-dd'
  D.holidays2026 = [
    { d: '2026-01-01', n: 'Tahun Baru Masehi' },
    { d: '2026-02-17', n: 'Tahun Baru Imlek 2577' },
    { d: '2026-03-19', n: 'Hari Raya Nyepi (Saka 1948)' },
    { d: '2026-03-20', n: 'Idul Fitri 1447 H' },
    { d: '2026-03-21', n: 'Idul Fitri 1447 H' },
    { d: '2026-04-03', n: 'Wafat Isa Almasih' },
    { d: '2026-05-01', n: 'Hari Buruh Internasional' },
    { d: '2026-05-14', n: 'Kenaikan Isa Almasih' },
    { d: '2026-05-27', n: 'Idul Adha 1447 H' },
    { d: '2026-05-31', n: 'Hari Raya Waisak 2570' },
    { d: '2026-06-01', n: 'Hari Lahir Pancasila' },
    { d: '2026-06-16', n: 'Tahun Baru Islam 1448 H' },
    { d: '2026-08-17', n: 'Hari Kemerdekaan RI' },
    { d: '2026-08-25', n: 'Maulid Nabi Muhammad SAW' },
    { d: '2026-12-25', n: 'Hari Raya Natal' }
  ];

  // Peta provinsi -> zona waktu. Yang tidak terdaftar dianggap WIB.
  D.zoneByProvince = {
    // WITA
    'bali': 'WITA', 'nusa tenggara barat': 'WITA', 'ntb': 'WITA',
    'nusa tenggara timur': 'WITA', 'ntt': 'WITA',
    'kalimantan selatan': 'WITA', 'kalimantan timur': 'WITA', 'kalimantan utara': 'WITA',
    'sulawesi selatan': 'WITA', 'sulawesi tenggara': 'WITA', 'sulawesi tengah': 'WITA',
    'sulawesi utara': 'WITA', 'sulawesi barat': 'WITA', 'gorontalo': 'WITA',
    // WIT
    'maluku': 'WIT', 'maluku utara': 'WIT',
    'papua': 'WIT', 'papua barat': 'WIT', 'papua tengah': 'WIT',
    'papua pegunungan': 'WIT', 'papua selatan': 'WIT', 'papua barat daya': 'WIT'
  };

  // offset menit relatif ke WIB (untuk normalisasi ke WIB)
  D.zoneOffsetMin = { 'WIB': 0, 'WITA': -60, 'WIT': -120 };

  // offset menit untuk penambahan (reverse direction - WIT/WITA -> WIB interpretation)
  D.zoneOffsetMinAdd = { 'WIB': 0, 'WITA': 60, 'WIT': 120 };

  D.detectZone = function (provinsi, zonaField) {
    if (zonaField) {
      const z = String(zonaField).trim().toUpperCase();
      if (z === 'WIB' || z === 'WITA' || z === 'WIT') return z;
    }
    const key = String(provinsi || '').trim().toLowerCase();
    return D.zoneByProvince[key] || 'WIB';
  };

  // Master Jabatan bawaan (metode: 'durasi' | 'reguler')
  D.jabatanDefault = [
    { nama: 'Wali Asuh', metode: 'durasi' },
    { nama: 'Wali Asrama', metode: 'durasi' },
    { nama: 'Satpam', metode: 'durasi' },
    { nama: 'Pendamping Sosial', metode: 'reguler' },
    { nama: 'Penata Layanan Operasional', metode: 'reguler' },
    { nama: 'Pengelola Layanan Operasional', metode: 'reguler' },
    { nama: 'Operator Layanan Operasional', metode: 'reguler' },
    { nama: 'Operator Sekolah', metode: 'reguler' },
    { nama: 'Juru Masak SR', metode: 'reguler' },
    { nama: 'Bendahara SR', metode: 'reguler' },
    { nama: 'Guru SR', metode: 'reguler' },
    { nama: 'Kepala Sekolah', metode: 'reguler' },
    { nama: 'OB/Cleaning Service', metode: 'reguler' }
  ];

  D.jenisNoPotonganDefault = ['Tugas Kedinasan', 'Sakit', 'Cuti Melahirkan', 'Cuti Tahunan', 'Upacara'];
})();
