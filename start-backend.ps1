# Start the development API at the exact address used by the mini-program.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$configPath = Join-Path $projectRoot 'miniprogram\config\index.js'
$configSource = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$addressMatch = [regex]::Match($configSource, 'baseURL\s*:\s*[''"]([^''"]+)[''"]')
if (-not $addressMatch.Success) { throw 'Cannot read baseURL from miniprogram/config/index.js.' }
$apiAddress = [Uri]$addressMatch.Groups[1].Value
if ($apiAddress.Scheme -ne 'http') { throw 'This launcher is for the local HTTP development API only.' }
$listenAddress = $apiAddress.DnsSafeHost
$localAddresses = @('127.0.0.1', 'localhost')
foreach ($nic in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
    foreach ($unicast in $nic.GetIPProperties().UnicastAddresses) {
        if ($unicast.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
            $localAddresses += $unicast.Address.ToString()
        }
    }
}
if ($listenAddress -notin $localAddresses) {
    throw "The configured API address $listenAddress does not belong to this computer. Update the mini-program address and backend allowed_hosts together."
}
$healthAddress = $apiAddress.AbsoluteUri.TrimEnd('/') + '/health'
function Test-ProjectHealth {
    try {
        $result = Invoke-RestMethod -Uri $healthAddress -TimeoutSec 2
        return $result.status -eq 'ok' -and $result.storage -eq 'sqlite_local'
    } catch { return $false }
}
if (Test-ProjectHealth) {
    Write-Output "Backend is already ready: $($apiAddress.AbsoluteUri)"
    exit 0
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $apiAddress.Port -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    throw "Port $($apiAddress.Port) is occupied but this API did not pass its health check. No process was stopped."
}
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Install the backend virtual environment first; see README.md.' }
$logDirectory = Join-Path $projectRoot '.work'
New-Item -Path $logDirectory -ItemType Directory -Force | Out-Null
$outLog = Join-Path $logDirectory 'backend-service.out.log'
$errLog = Join-Path $logDirectory 'backend-service.err.log'
$server = Start-Process -FilePath $pythonPath -ArgumentList @('-X', 'utf8', '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', $listenAddress, '--port', [string]$apiAddress.Port, '--no-access-log') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
$deadline = (Get-Date).AddSeconds(20)
do {
    if (Test-ProjectHealth) {
        Write-Output "Backend is ready: $($apiAddress.AbsoluteUri)"
        Write-Output "Logs: $errLog"
        exit 0
    }
    Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)
throw "The backend did not become ready. Check $errLog. No existing process was stopped."
