#!/bin/bash
# EVKIN ABSENSI v1.5 - Quick Setup & Test Script

## SETUP BACKEND (One-time)
echo "📦 Installing Python dependencies..."
cd backend
pip install -r requirements.txt
echo "✓ Dependencies installed"

## START BACKEND
echo ""

---

**Copyright © Dio Fajrul Iman**
echo "🚀 Starting backend..."
echo "Command: uvicorn evkin_export_api:app --reload --port 8000"
echo ""
echo "Jika error 'Address already in use :8000':"
echo "  1. Kill process: netstat -ano | findstr :8000"
echo "  2. Lalu: taskkill /PID <PID> /F"
echo ""
echo "Backend akan berjalan di: http://localhost:8000"
echo "API docs akan tersedia di: http://localhost:8000/docs"
echo ""
echo "Jalankan di terminal baru:"
echo "uvicorn evkin_export_api:app --reload --port 8000"
echo ""

## TEST BACKEND
echo "📝 Testing backend endpoints..."
echo ""
echo "1. Health check:"
echo "   curl http://localhost:8000/api/health"
echo ""
echo "2. Seed demo:"
echo "   curl http://localhost:8000/api/export/seed-demo"
echo ""

## OPEN APP
echo "🌐 Opening app in browser..."
echo "File: file:///C:/Users/USER/Downloads/EVKIN_ABSENSI_v1.5 diocode/index.html"
echo ""

## TEST WORKFLOW
echo "✅ Test Workflow:"
echo ""
echo "1. Import data (contoh_absensi.csv)"
echo "2. Config (default settings OK)"
echo "3. Hitung Harian → wait for DB save"
echo "4. Rekap SDM → wait for DB save"
echo "5. Semi Final"
echo "6. Final → wait for DB save"
echo "7. Export:"
echo "   a. ① Simpan ke Database (verify in DevTools → Application → IndexedDB)"
echo "   b. ② Web Worker (watch progress bar)"
echo "   c. ③ Backend Export (if backend running)"
echo "   d. ⭐ Smart Export (RECOMMENDED)"
echo ""
echo "8. Download .xlsx file → Open in Excel"
echo "9. Verify sheets:"
echo "   - HITUNG HARIAN"
echo "   - REKAP SDM"
echo "   - FINAL ABSENSI"
echo "   - SEMI FINAL"
echo "   - ANOMALI"
echo ""

## VERIFY OUTPUT
echo "✨ Verify Excel Output:"
echo ""
echo "□ File dapat dibuka di Excel"
echo "□ Ada multiple sheets"
echo "□ Data HITUNG HARIAN:"
echo "    NIP, Nama, Jabatan, Tanggal, Jam Masuk/Pulang, Durasi"
echo "    Status (Duplikasi, Lengkap), Potongan (%)"
echo "□ Data REKAP SDM:"
echo "    NIP, Nama, Hari Efektif, Hari Ada Absensi, Total Potongan"
echo "□ Data FINAL ABSENSI:"
echo "    NIP, Nama, Tukin Bruto, Potongan Kehadiran, Final Dibayar"
echo "□ Header frozen (bisa scroll)"
echo "□ Autofilter aktif"
echo "□ Format number OK (%, Rp)"
echo ""
