param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
if (-not $env:EVKIN_DUCKDB_PATH) { $env:EVKIN_DUCKDB_PATH = Join-Path $projectRoot 'backend\data\EVKIN_MASTER.duckdb' }
$port = if ($env:EVKIN_HTTP_PORT) { [int]$env:EVKIN_HTTP_PORT } else { 8000 }
$env:EVKIN_HTTP_PORT = [string]$port
$insecureDev = $env:EVKIN_ALLOW_INSECURE_LOCAL_DEV -eq '1'
$apiKey = if ($env:EVKIN_API_KEY) { $env:EVKIN_API_KEY } else { $env:EVKIN_ANALYTICS_API_KEY }
if (-not $apiKey -and -not $insecureDev) {
    throw 'EVKIN_API_KEY wajib diatur sebelum backend dijalankan. Gunakan EVKIN_ALLOW_INSECURE_LOCAL_DEV=1 hanya untuk test/development lokal.'
}
if (-not $env:EVKIN_ALLOWED_ORIGINS) {
    $env:EVKIN_ALLOWED_ORIGINS = "http://127.0.0.1:$port,http://localhost:$port"
}
$url = "http://127.0.0.1:$port"
$apiHeaders = if ($apiKey) { @{ 'X-EVKIN-API-Key' = $apiKey } } else { @{} }
$mutex = New-Object System.Threading.Mutex($false, "Local\EVKIN_Launch_$port")
$owned = $false
try {
    try { $owned = $mutex.WaitOne(30000) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { throw 'Launcher lain masih berjalan. Coba kembali.' }
    $info = $null
    try { $info = Invoke-RestMethod "$url/api/info" -Headers $apiHeaders -TimeoutSec 3 } catch {}
    if ($info) {
        if ($info.service -ne 'evkin-export-api' -or $info.app_root -ne $projectRoot) { throw "Port $port dipakai aplikasi lain. Tidak ada proses yang dihentikan." }
        Write-Host "Menggunakan backend aktif: $url"
    } else {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port sedang digunakan. Periksa backend aktif; server kedua tidak dijalankan." }
        $pythonExe = $null
        foreach ($candidate in @('backend\.venv\Scripts\python.exe', '.venv\Scripts\python.exe')) {
            $candidatePath = Join-Path $projectRoot $candidate
            if (Test-Path -LiteralPath $candidatePath) { $pythonExe = $candidatePath; break }
        }
        if (-not $pythonExe) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
        $logDir = Join-Path $projectRoot 'backend\data'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $stderr = Join-Path $logDir "runtime-$stamp.stderr.log"
        $stdout = Join-Path $logDir "runtime-$stamp.stdout.log"
        $server = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','backend.evkin_export_api:app','--host','127.0.0.1','--port',"$port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardError $stderr -RedirectStandardOutput $stdout -PassThru
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Milliseconds 500
            if ($server.HasExited) { throw "Backend gagal dimulai. Lihat log: $stderr" }
            try { $info = Invoke-RestMethod "$url/api/info" -Headers $apiHeaders -TimeoutSec 1; break } catch {}
        }
        if (-not $info) { throw "Backend belum siap. Lihat log: $stderr. Jangan menjalankan server duplikat." }
        Write-Host "Backend siap: $url"
    }
    if ($OpenBrowser) {
        $browserUrl = if ($apiKey) { "$url/#evkin-api-key=$([uri]::EscapeDataString($apiKey))" } else { $url }
        Start-Process $browserUrl
    }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
