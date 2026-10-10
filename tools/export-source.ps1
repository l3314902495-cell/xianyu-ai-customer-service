param(
    [string]$OutputPath = "outputs/xianyu-ai-source.zip"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

# Include current edits and new project files without committing or staging.
$files = @(& git -c core.quotepath=false ls-files --cached --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw "Cannot read the Git source manifest." }
$files = @($files | Sort-Object -Unique)
$privatePathPattern = '(^|/)(\.git|\.agents|\.codex|\.runtime|\.venv|node_modules|\.next|outputs|work|__pycache__|\.pytest_cache|\.ruff_cache|\.tmp-npm-cache|test-results|playwright-report)(/|$)|(^|/)\.env($|\.(?!example$))|\.(db(?:-.*)?|sqlite(?:3)?(?:-.*)?|pem|key|log|pyc|tsbuildinfo)$|^[^/]+\.(docx|xlsx|pdf)$'
$secretPattern = 'sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----'

foreach ($relativePath in $files) {
    if ($relativePath -match $privatePathPattern) {
        throw "Private/generated file is tracked; remove it from Git before exporting: $relativePath"
    }
    $sourcePath = [IO.Path]::GetFullPath((Join-Path $projectRoot $relativePath))
    if (-not $sourcePath.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Source path is outside the project: $relativePath"
    }
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Tracked file is missing: $relativePath"
    }
    if ((Get-Item -LiteralPath $sourcePath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Symbolic links must be reviewed before exporting: $relativePath"
    }
    if ([IO.File]::ReadAllText($sourcePath) -match $secretPattern) {
        throw "Possible credential found; inspect locally before exporting: $relativePath"
    }
}

$archivePath = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
if ($files | Where-Object { [IO.Path]::GetFullPath((Join-Path $projectRoot $_)) -eq $archivePath }) {
    throw "Archive output must not overwrite a source file."
}
New-Item -ItemType Directory -Path (Split-Path -Parent $archivePath) -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stream = [IO.File]::Open($archivePath, [IO.FileMode]::CreateNew)
try {
    $archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($relativePath in $files) {
            $entryName = "xianyu-ai-customer-service/" + $relativePath.Replace('\', '/')
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive, (Join-Path $projectRoot $relativePath), $entryName,
                [IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    } finally { $archive.Dispose() }
} finally { $stream.Dispose() }

Write-Host "Exported $($files.Count) source files: $archivePath"
Write-Host "SHA256: $((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash)"
