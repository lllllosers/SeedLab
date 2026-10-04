# Read-only inventory. Never remove files, change permissions, or open a database.
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
$inventoryDirectories = [Collections.Generic.List[string]]::new()

function Get-InventoryFiles {
    param([string]$Root)
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force -ErrorAction Stop) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                Write-Host "[SKIP] Link: $($item.FullName)"
            } elseif ($item.PSIsContainer) {
                $script:inventoryDirectories.Add($item.FullName)
                $pending.Push($item.FullName)
            } else {
                $item
            }
        }
    }
}

Push-Location $repoRoot
try {
    Write-Output '[GIT] Branch and status'
    git branch --show-current
    git status --short
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'Install the local backend environment before resolving the database configuration.'
    }
    Push-Location (Join-Path $repoRoot 'backend')
    try {
        $configurationCode = @'
from pathlib import Path
from sqlalchemy.engine import make_url
from app.core.config import get_settings
url = make_url(get_settings().seedlab_database_url)
print(str(Path(url.database).resolve()) if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:" else "NON_FILE_DATABASE")
'@
        $databasePath = $configurationCode | & $pythonPath -B -
        if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the configured database.' }
    } finally { Pop-Location }
    Write-Output "ACTIVE_DATABASE = $databasePath"
    $files = @(Get-InventoryFiles $repoRoot)
    $directories = @('backend/app', 'backend/tests', 'backend/alembic', 'backend/data', 'backend/backups',
        'frontend/src', 'frontend/tests', 'frontend/node_modules', '.venv', 'docs', 'scripts', '.git')
    Write-Output '[SIZE] Major directories (bytes)'
    foreach ($relative in $directories) {
        $prefix = [IO.Path]::GetFullPath((Join-Path $repoRoot $relative)).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        $matches = @($files | Where-Object { $_.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) })
        $bytes = ($matches | Measure-Object Length -Sum).Sum
        Write-Output ("{0}: {1} files, {2} bytes" -f $relative, $matches.Count, ([long]$bytes))
    }
    $dataPrefix = (Join-Path $repoRoot 'backend\data') + '\'
    $databases = @($files | Where-Object { $_.FullName.StartsWith($dataPrefix, [StringComparison]::OrdinalIgnoreCase) -and $_.Name -match '\.(db|sqlite|sqlite3)($|-(wal|shm|journal)$)' })
    Write-Output '[DATABASES] backend/data database files'
    $databases | Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize
    Write-Output '[VERIFICATION] Historical database candidates (requires manual review)'
    $databases | Where-Object { $_.FullName -ne $databasePath -and $_.Name -match 'stage|verification|roundtrip|manual|test|dag-semantics' } |
        Select-Object FullName, Length | Format-Table -AutoSize
    $backupPrefix = (Join-Path $repoRoot 'backend\backups') + '\'
    $backups = @($files | Where-Object { $_.FullName.StartsWith($backupPrefix, [StringComparison]::OrdinalIgnoreCase) })
    Write-Output ("[BACKUPS] {0} files, {1} bytes; dev-reset: {2}" -f $backups.Count,
        ([long](($backups | Measure-Object Length -Sum).Sum)), @($backups | Where-Object { $_.Name -like 'dev-reset-*.db' }).Count)
    $backups | Select-Object Name, Length, LastWriteTime, @{Name='Category'; Expression={
        if ($_.Name -like 'dev-reset-*.db') { 'dev-reset' }
        elseif ($_.Name -like 'stage3-final-acceptance-*.db') { 'stage3 final' }
        elseif ($_.Name -like 'stage31-data-inventory-*') { 'stage31 inventory' }
        elseif ($_.Name -like 'seedlab-pre-*') { 'manual upgrade snapshot' }
        elseif ($_.Name -match '^stage31-.*\.png$') { 'browser diagnostics' }
        else { 'manual review' }
    }} | Format-Table -AutoSize
    # Environment-owned caches are reported in environment totals, not as source cleanup targets.
    $sourceFiles = @($files | Where-Object { $_.FullName -notmatch '[\\/](\.venv|node_modules|\.git)[\\/]' })
    Write-Output '[ARTIFACTS] Temporary/cache/build file counts outside dependencies'
    foreach ($pattern in @('[\\/]\.test-temp', '[\\/]\.tmp-', '[\\/]pytest-', '[\\/]\.pytest_cache[\\/]',
        '[\\/]\.(ruff|mypy)_cache[\\/]', '[\\/]__pycache__[\\/]', '\.pyc$', '[\\/]frontend[\\/]dist[\\/]',
        '[\\/](coverage|htmlcov|playwright-report|test-results)[\\/]', '[\\/]\.coverage($|\.)')) {
        $matches = @($sourceFiles | Where-Object { $_.FullName -match $pattern })
        Write-Output ("{0}: {1} files, {2} bytes" -f $pattern, $matches.Count, ([long](($matches | Measure-Object Length -Sum).Sum)))
    }
    Write-Output '[ARTIFACT DIRECTORIES] Includes empty directories'
    $inventoryDirectories | Where-Object {
        $_ -notmatch '[\\/](\.venv|node_modules|\.git)[\\/]' -and
        $_ -match '[\\/](\.test-temp[^\\/]*|\.tmp-[^\\/]*|pytest-[^\\/]*|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|dist|coverage|htmlcov|playwright-report|test-results|browser-profiles|\.browser-profile[^\\/]*)$'
    }
    Write-Output '[LARGEST] Top 20 files'
    $files | Sort-Object Length -Descending | Select-Object -First 20 FullName, Length | Format-Table -AutoSize
    Write-Output '[LARGE] Files over 100 MiB'
    $files | Where-Object { $_.Length -gt 100MB } | Select-Object FullName, Length | Format-Table -AutoSize
    Write-Output '[GIT] Object storage'
    git count-objects -vH
    $ignored = @(git ls-files --others --ignored --exclude-standard --directory)
    Write-Output "[IGNORED] $($ignored.Count) ignored paths (directory summary)"
    $ignored
    Write-Output '[GIT] Final status'
    git status --short
    Write-Output '[DONE] Read-only check complete.'
} finally { Pop-Location }
