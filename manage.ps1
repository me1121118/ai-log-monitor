param(
    [ValidateSet('Start','Stop','Restart','Status','Test','Open','Clean')]
    [string]$Action = 'Status'
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $Root 'data'
$PidFile = Join-Path $Root 'server.pid'
$SecretsFile = Join-Path $Root 'server\secrets.env'
$Port = 8888
$LocalUrl = "http://127.0.0.1:$Port/"
$HealthUrl = "http://127.0.0.1:$Port/health"
$TestCommandText = "python -m unittest discover -s tests -v"

function Import-LocalSecrets {
    if (-not (Test-Path -LiteralPath $SecretsFile)) {
        Write-Host "No server\secrets.env found; using current environment."
        return
    }

    Get-Content -LiteralPath $SecretsFile | ForEach-Object {
        $line = $_.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith('#')) {
            return
        }
        if ($line -match '^\s*([^#=\s][^=]*)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
}

function Set-LocalEnvironment {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    [Environment]::SetEnvironmentVariable('AI_LOG_DATA_DIR', $DataDir, 'Process')
    [Environment]::SetEnvironmentVariable('AI_LOG_HOST', '0.0.0.0', 'Process')
    [Environment]::SetEnvironmentVariable('AI_LOG_PORT', [string]$Port, 'Process')
    Import-LocalSecrets
}

function Get-Listener {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-PidFromFile {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }
    $raw = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($raw -match '^\d+$') {
        return [int]$raw
    }
    return $null
}

function Test-IsProjectServerProcess {
    param([int]$ServerProcessId)

    $fileProcessId = Get-PidFromFile
    if ($null -ne $fileProcessId -and $fileProcessId -eq $ServerProcessId) {
        return $true
    }

    try {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ServerProcessId" -ErrorAction Stop
        if ($null -ne $processInfo.CommandLine -and $processInfo.CommandLine -match 'server\.main') {
            return $true
        }
    }
    catch {
        return $false
    }

    return $false
}

function Test-Health {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

function Wait-ForHealth {
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-Health) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Start-Server {
    Set-LocalEnvironment

    $listener = Get-Listener
    if ($null -ne $listener) {
        $ownerProcessId = [int]$listener.OwningProcess
        if (Test-Health) {
            Set-Content -LiteralPath $PidFile -Value $ownerProcessId -Encoding ASCII
            Write-Host "AI Log Monitor is already running on $LocalUrl (PID $ownerProcessId)."
            return
        }
        Write-Warning "Port $Port is already in use by PID $ownerProcessId, but health check did not pass."
        exit 1
    }

    $pythonCommand = Get-Command python -ErrorAction Stop
    $process = Start-Process -FilePath $pythonCommand.Source -ArgumentList @('-B', '-m', 'server.main') -WorkingDirectory $Root -WindowStyle Hidden -PassThru

    if (-not (Wait-ForHealth)) {
        Write-Warning "Started PID $($process.Id), but $HealthUrl did not become healthy."
        exit 1
    }

    $listener = Get-Listener
    if ($null -ne $listener) {
        $ownerProcessId = [int]$listener.OwningProcess
        Set-Content -LiteralPath $PidFile -Value $ownerProcessId -Encoding ASCII
        Write-Host "AI Log Monitor started on $LocalUrl (PID $ownerProcessId)."
        return
    }

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII
    Write-Host "AI Log Monitor started on $LocalUrl (PID $($process.Id))."
}

function Stop-Server {
    $listener = Get-Listener
    if ($null -eq $listener) {
        if (Test-Path -LiteralPath $PidFile) {
            Remove-Item -LiteralPath $PidFile -Force
        }
        Write-Host "AI Log Monitor is not running on port $Port."
        return
    }

    $ownerProcessId = [int]$listener.OwningProcess
    if (-not (Test-IsProjectServerProcess -ServerProcessId $ownerProcessId)) {
        Write-Warning "Port $Port is used by PID $ownerProcessId, but it does not look like this project's server. I will not stop it."
        exit 1
    }

    Stop-Process -Id $ownerProcessId -Force
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    Write-Host "AI Log Monitor stopped (PID $ownerProcessId)."
}

function Show-Status {
    Set-LocalEnvironment
    $listener = Get-Listener
    $adminUser = $env:ADMIN_USER
    if ([string]::IsNullOrWhiteSpace($adminUser)) {
        $adminUser = '(not set)'
    }

    if ($null -eq $listener) {
        Write-Host "Status: stopped"
        Write-Host "URL: $LocalUrl"
        Write-Host "Login user: $adminUser"
        return
    }

    $ownerProcessId = [int]$listener.OwningProcess
    $health = if (Test-Health) { 'healthy' } else { 'not healthy' }
    Write-Host "Status: running ($health)"
    Write-Host "PID: $ownerProcessId"
    Write-Host "URL: $LocalUrl"
    Write-Host "Login user: $adminUser"
}

function Invoke-ProjectTests {
    Write-Host "Running: $TestCommandText"
    Push-Location $Root
    try {
        $pythonCommand = Get-Command python -ErrorAction Stop
        & $pythonCommand.Source -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    finally {
        Pop-Location
    }
}

function Open-Dashboard {
    if ($null -eq (Get-Listener)) {
        Start-Server
    }
    Start-Process $LocalUrl
    Write-Host "Opened $LocalUrl"
}

function Remove-LocalCache {
    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $removed = 0

    Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Directory -Filter '__pycache__' | ForEach-Object {
        $resolvedTarget = (Resolve-Path -LiteralPath $_.FullName).Path
        if (-not $resolvedTarget.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove path outside project: $resolvedTarget"
        }
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
        $removed += 1
    }

    Write-Host "Cleaned $removed Python cache folder(s)."
}

switch ($Action) {
    'Start' { Start-Server }
    'Stop' { Stop-Server }
    'Restart' {
        Stop-Server
        Start-Server
    }
    'Status' { Show-Status }
    'Test' { Invoke-ProjectTests }
    'Open' { Open-Dashboard }
    'Clean' { Remove-LocalCache }
}
