param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$runtimeDirectory = Join-Path $PSScriptRoot ".runtime"
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

function Get-SourceFingerprint {
    $sourceEntries = @(
        "docker-compose.yml",
        ".dockerignore",
        "package.json",
        "pnpm-workspace.yaml",
        "pnpm-lock.yaml",
        "docker",
        "apps\api\pyproject.toml",
        "apps\api\README.md",
        "apps\api\alembic.ini",
        "apps\api\alembic",
        "apps\api\app",
        "apps\web"
    )
    $files = foreach ($entry in $sourceEntries) {
        $path = Join-Path $PSScriptRoot $entry
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Get-Item -LiteralPath $path
        } elseif (Test-Path -LiteralPath $path -PathType Container) {
            Get-ChildItem -LiteralPath $path -File -Recurse | Where-Object {
                $_.FullName -notmatch '[\\/](node_modules|\.next|\.venv|\.pytest_cache|\.ruff_cache|__pycache__)[\\/]'
            }
        }
    }
    $manifest = foreach ($file in ($files | Sort-Object FullName -Unique)) {
        $relativePath = $file.FullName.Substring($PSScriptRoot.Length).TrimStart([char[]]@('\', '/'))
        "$relativePath`t$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash)"
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($manifest -join "`n"))
        return ([System.BitConverter]::ToString($sha256.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    Write-Host "[ERROR] Node.js was not found; the dedicated Edge login helper cannot start." -ForegroundColor Red
    exit 1
}

$helperScript = Join-Path $PSScriptRoot "tools\xianyu-edge-login-helper.mjs"
$helperVersion = (Get-FileHash -LiteralPath $helperScript -Algorithm SHA256).Hash.ToLowerInvariant()
$helperReady = $false
try {
    $helperHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
    $helperReady = $helperHealth.status -eq "ok" -and $helperHealth.version -eq $helperVersion
} catch {}
if (-not $helperReady) {
    $staleHelpers = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "node.exe" -and $_.CommandLine -and $_.CommandLine.Contains($helperScript)
    }
    foreach ($staleHelper in $staleHelpers) {
        Write-Host "[SETUP] Restarting the updated Edge login helper..." -ForegroundColor Yellow
        Stop-Process -Id $staleHelper.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[SETUP] Starting dedicated Edge login helper..." -ForegroundColor Yellow
    $previousHelperVersion = $env:XIANYU_HELPER_VERSION
    $env:XIANYU_HELPER_VERSION = $helperVersion
    try {
        Start-Process -FilePath $nodeCommand.Source -ArgumentList @($helperScript) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    } finally {
        if ($null -eq $previousHelperVersion) {
            Remove-Item Env:\XIANYU_HELPER_VERSION -ErrorAction SilentlyContinue
        } else {
            $env:XIANYU_HELPER_VERSION = $previousHelperVersion
        }
    }
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $helperHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
            if ($helperHealth.status -eq "ok" -and $helperHealth.version -eq $helperVersion) { $helperReady = $true; break }
        } catch {}
    }
    if (-not $helperReady) {
        Write-Host "[ERROR] Dedicated Edge login helper failed to start." -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Xianyu AI Customer Service - Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$dockerCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
)

$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $dockerExe = $dockerCommand.Source
} else {
    $dockerExe = $dockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $dockerExe) {
    Write-Host "[ERROR] Docker CLI was not found. Install Docker Desktop first." -ForegroundColor Red
    exit 1
}

function Test-DockerReady {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & $dockerExe info 2>&1 | Out-Null
    $dockerExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    return $dockerExitCode -eq 0
}

if (-not (Test-Path -LiteralPath ".env") -and (Test-Path -LiteralPath ".env.example")) {
    Write-Host "[SETUP] Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
}

if (-not (Test-DockerReady)) {
    $desktopCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )
    $desktopExe = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $desktopExe) {
        Write-Host "[ERROR] Docker Desktop was not found." -ForegroundColor Red
        exit 1
    }

    Write-Host "[SETUP] Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process -FilePath $desktopExe

    $dockerReady = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-DockerReady) {
            $dockerReady = $true
            break
        }
        Write-Host -NoNewline "."
    }
    Write-Host ""

    if (-not $dockerReady) {
        Write-Host "[ERROR] Docker Desktop did not become ready within 120 seconds." -ForegroundColor Red
        exit 1
    }
}

# Fail fast when another host process owns the Web port. Without this check,
# Docker only reports the conflict after images have finished building.
$webPort = 3000
$webContainerRunning = $false
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$runningComposeServices = @(& $dockerExe compose ps --status running --services 2>$null)
$ErrorActionPreference = $previousPreference
$webContainerRunning = $runningComposeServices -contains "web"

if (-not $webContainerRunning) {
    $webPortListeners = @(Get-NetTCPConnection -LocalPort $webPort -State Listen -ErrorAction SilentlyContinue)
    if ($webPortListeners.Count -gt 0) {
        $ownerPids = @($webPortListeners | Select-Object -ExpandProperty OwningProcess -Unique)
        $ownerDescriptions = foreach ($ownerPid in $ownerPids) {
            $owner = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($owner) { "$($owner.ProcessName) (PID $ownerPid)" } else { "PID $ownerPid" }
        }
        Write-Host "[ERROR] Web port $webPort is already in use by: $($ownerDescriptions -join ', ')." -ForegroundColor Red
        Write-Host "[HINT] Close that program, or run: Stop-Process -Id $($ownerPids -join ',')" -ForegroundColor Yellow
        exit 1
    }
}

$requiredImages = @("wo-xi-api:latest", "wo-xi-listener:latest", "wo-xi-web:latest")
$missingImages = @(
    foreach ($image in $requiredImages) {
        & $dockerExe image inspect $image 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $image }
    }
)
$sourceFingerprint = Get-SourceFingerprint
$sourceStampPath = Join-Path $runtimeDirectory "launcher-image-source.sha256"
$previousFingerprint = if (Test-Path -LiteralPath $sourceStampPath) {
    (Get-Content -LiteralPath $sourceStampPath -Raw).Trim()
} else {
    ""
}
$sourceChanged = $previousFingerprint -ne $sourceFingerprint
$shouldBuild = $Rebuild -or $missingImages.Count -gt 0 -or $sourceChanged

if ($shouldBuild) {
    if ($missingImages.Count -gt 0) {
        Write-Host "[SETUP] Local images are missing; the first startup needs network access." -ForegroundColor Yellow
        Write-Host "[SETUP] Missing: $($missingImages -join ', ')" -ForegroundColor Yellow
    }
    if ($sourceChanged -and $missingImages.Count -eq 0) {
        Write-Host "[UPDATE] Program changes detected; rebuilding affected local images..." -ForegroundColor Yellow
    }
    Write-Host "[START] Building and starting database, Redis, API, Xianyu listener and Web..." -ForegroundColor Green
    & $dockerExe compose up -d --build
} else {
    Write-Host "[START] Starting from local images (no Docker Hub access required)..." -ForegroundColor Green
    & $dockerExe compose up -d --no-build
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker compose up failed." -ForegroundColor Red
    exit $LASTEXITCODE
}
if ($shouldBuild) {
    Set-Content -LiteralPath $sourceStampPath -Value $sourceFingerprint -Encoding ASCII
}

Write-Host "[WAIT] Waiting for http://localhost:3000 ..." -ForegroundColor Yellow
$webReady = $false
for ($attempt = 1; $attempt -le 90; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            $webReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $webReady) {
    Write-Host "[ERROR] Containers started, but the Web page was not ready in time." -ForegroundColor Red
    & $dockerExe compose ps
    exit 1
}

Write-Host "[OK] System is ready: http://localhost:3000" -ForegroundColor Green
Write-Host "[OK] Dedicated Edge login helper: http://127.0.0.1:8765" -ForegroundColor Green
Start-Process "http://localhost:3000"
exit 0
