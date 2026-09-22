param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Get-ListeningConnections([int]$Port) {
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Group-Object OwningProcess | ForEach-Object { $_.Group[0] })
}

function Wait-ListeningPortFree([int]$Port, [int]$TimeoutMilliseconds) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    do {
        if ((Get-ListeningConnections $Port).Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Test-EvkinBackendProcess($Connection, $ProcessInfo, [int]$ExpectedPort, [string]$ExpectedProjectRoot, [bool]$HealthIsEvkin) {
    if (-not $ProcessInfo -or -not $HealthIsEvkin -or $Connection.LocalAddress -ne '127.0.0.1') { return $false }
    $executableName = [IO.Path]::GetFileName([string]$ProcessInfo.ExecutablePath)
    if ($executableName -notmatch '^python(?:w|\d+(?:\.\d+)*)?\.exe$') { return $false }
    $commandLine = [string]$ProcessInfo.CommandLine
    $hasUvicornEntrypoint = $commandLine -match '(?i)(?:^|\s)-m\s+uvicorn(?:\s|$)' -and
        $commandLine -match '(?i)(?:^|\s)backend\.evkin_export_api:app(?:\s|$)'
    $hasExpectedPort = $commandLine -match "(?i)(?:^|\s)--port(?:=|\s+)`"?$ExpectedPort`"?(?:\s|$)"
    $hasLoopbackHost = $commandLine -match '(?i)(?:^|\s)--host(?:=|\s+)"?127\.0\.0\.1"?(?:\s|$)'
    $hasAppDirectory = $commandLine -match '(?i)(?:^|\s)--app-dir(?:=|\s+)'
    $hasCurrentProjectPath = $commandLine.IndexOf($ExpectedProjectRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if ($hasAppDirectory -and -not $hasCurrentProjectPath) { return $false }
    return $hasUvicornEntrypoint -and $hasExpectedPort -and $hasLoopbackHost
}

if (-not $env:EVKIN_DUCKDB_PATH) { $env:EVKIN_DUCKDB_PATH = Join-Path $projectRoot 'backend\data\EVKIN_MASTER.duckdb' }
$port = if ($env:EVKIN_HTTP_PORT) { [int]$env:EVKIN_HTTP_PORT } else { 8000 }
$env:EVKIN_HTTP_PORT = [string]$port
$url = "http://127.0.0.1:$port"
$mutex = New-Object System.Threading.Mutex($false, "Local\EVKIN_Launch_$port")
$owned = $false
try {
    try { $owned = $mutex.WaitOne(30000) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    if (-not $owned) { throw 'Launcher lain masih berjalan. Coba kembali.' }

    $listeners = @(Get-ListeningConnections $port)
    if ($listeners.Count -gt 0) {
        $health = $null
        try { $health = Invoke-RestMethod "$url/health" -TimeoutSec 2 } catch {}
        $healthIsEvkin = $health -and $health.status -eq 'ok' -and $health.service -eq 'evkin-export-api'
        $verifiedOwners = @()
        foreach ($listener in $listeners) {
            $ownerPid = [int]$listener.OwningProcess
            $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
            if (-not (Test-EvkinBackendProcess $listener $processInfo $port $projectRoot $healthIsEvkin)) {
                $processName = if ($processInfo) { $processInfo.Name } else { 'unknown' }
                throw "Port $port sedang digunakan aplikasi lain (PID $ownerPid, process $processName). Tutup aplikasi tersebut atau ubah EVKIN_HTTP_PORT."
            }
            $verifiedOwners += $ownerPid
        }

        Write-Host "Menghentikan backend EVKIN lama pada port $port..."
        foreach ($ownerPid in $verifiedOwners) {
            $runningProcess = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($runningProcess) { $null = $runningProcess.CloseMainWindow() }
        }
        if (-not (Wait-ListeningPortFree $port 1000)) {
            $remainingListeners = @(Get-ListeningConnections $port)
            foreach ($listener in $remainingListeners) {
                $ownerPid = [int]$listener.OwningProcess
                if ($verifiedOwners -contains $ownerPid) {
                    Stop-Process -Id $ownerPid -ErrorAction SilentlyContinue
                }
            }
        }
        if (-not (Wait-ListeningPortFree $port 4000)) {
            $remainingListeners = @(Get-ListeningConnections $port)
            foreach ($listener in $remainingListeners) {
                $ownerPid = [int]$listener.OwningProcess
                if ($verifiedOwners -contains $ownerPid) {
                    Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
                }
            }
            if (-not (Wait-ListeningPortFree $port 5000)) {
                $remaining = @(Get-ListeningConnections $port) | Select-Object -First 1
                $remainingPid = if ($remaining) { [int]$remaining.OwningProcess } else { 0 }
                $remainingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $remainingPid" -ErrorAction SilentlyContinue
                $remainingName = if ($remainingProcess) { $remainingProcess.Name } else { 'unknown' }
                throw "Port $port belum bebas (PID $remainingPid, process $remainingName). Backend baru tidak dijalankan."
            }
        }
    }

    $apiKey = $env:EVKIN_API_KEY
    if (-not $apiKey) {
        $tokenBytes = New-Object byte[] 32
        $tokenGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $tokenGenerator.GetBytes($tokenBytes)
        } finally {
            $tokenGenerator.Dispose()
        }
        $apiKey = [Convert]::ToBase64String($tokenBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        $env:EVKIN_API_KEY = $apiKey
        Write-Host 'EVKIN secure local session initialized.'
    }
    if (-not $env:EVKIN_ALLOWED_ORIGINS) {
        $env:EVKIN_ALLOWED_ORIGINS = "http://127.0.0.1:$port,http://localhost:$port"
    }
    $apiHeaders = @{ 'X-EVKIN-API-Key' = $apiKey }

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
    $quotedProjectRoot = '"' + $projectRoot + '"'
    $server = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','backend.evkin_export_api:app','--app-dir',$quotedProjectRoot,'--host','127.0.0.1','--port',"$port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardError $stderr -RedirectStandardOutput $stdout -PassThru
    $info = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($server.HasExited) { throw "Backend gagal dimulai. Lihat log: $stderr" }
        try { $info = Invoke-RestMethod "$url/api/info" -Headers $apiHeaders -TimeoutSec 1; break } catch {}
    }
    if (-not $info) { throw "Backend belum siap. Lihat log: $stderr. Jangan menjalankan server duplikat." }
    Write-Host "Backend siap: $url"

    if ($OpenBrowser) {
        $browserUrl = "$url/#evkin-api-key=$([uri]::EscapeDataString($apiKey))"
        Start-Process $browserUrl
    }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
