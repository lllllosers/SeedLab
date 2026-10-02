# Builds the portable distribution. Dependencies must already be installed.
[CmdletBinding()]
param(
    [ValidatePattern('^portable(?:-[a-z0-9]+)*$')]
    [string]$OutputName = 'portable'
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Missing .venv. Install backend[test,control,packaging] first.' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'npm is needed for building only.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'frontend\node_modules') -PathType Container)) { throw 'Frontend dependencies missing. Install them before building.' }
& $taskPython -c "import PyInstaller, PySide6, app.version; assert PyInstaller.__version__.startswith('6.'); print('PyInstaller '+PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Packaging dependencies missing or unsupported.' }

function Initialize-OwnedDirectory([string]$taskPath) {
    $taskResolved = [IO.Path]::GetFullPath($taskPath)
    if (-not $taskResolved.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build target escapes repository.' }
    $taskAncestor = $taskResolved
    while ($taskAncestor -and $taskAncestor.StartsWith($taskRoot, [StringComparison]::OrdinalIgnoreCase)) {
        if ((Test-Path -LiteralPath $taskAncestor) -and ((Get-Item -LiteralPath $taskAncestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Redirected build target refused: $taskAncestor" }
        $taskAncestor = Split-Path -Parent $taskAncestor
    }
    $taskMarker = Join-Path $taskResolved '.seedlab-build-owned'
    if (Test-Path -LiteralPath $taskResolved) {
        if (-not (Test-Path -LiteralPath $taskMarker -PathType Leaf)) { throw "Existing unowned build directory preserved: $taskResolved" }
        # Reject descendant redirects before recursive removal.
        foreach ($taskChild in Get-ChildItem -LiteralPath $taskResolved -Recurse -Force) {
            if ($taskChild.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Redirected build artifact preserved: $($taskChild.FullName)" }
            if ($taskChild.Name -in @('installation.json','instance.json','seedlab.json','bootstrap.token','.env') -or
                ($taskChild.PSIsContainer -and $taskChild.Name -in @('data','backups','logs')) -or
                $taskChild.Name -match '\.db(?:-(?:wal|shm|journal))?$') {
                throw "Runtime data found in build output; preserved: $($taskChild.FullName). Move this deployed copy out of build output before rebuilding."
            }
        }
        Write-Host "[REMOVE owned build directory] $taskResolved"
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
    New-Item -ItemType Directory -Path $taskResolved -Force | Out-Null
    Set-Content -LiteralPath $taskMarker -Value 'SeedLab portable build output; no user data' -Encoding UTF8
}

$taskWork = Join-Path $taskRoot 'build\portable-pyinstaller'
$taskCache = Join-Path $taskRoot 'build\portable-cache'
$taskDist = Join-Path $taskRoot "dist\$OutputName"
foreach ($taskOwned in @($taskWork,$taskCache,$taskDist)) { Initialize-OwnedDirectory $taskOwned }
$taskOldCache = $env:PYINSTALLER_CONFIG_DIR
$taskOldUtf8 = $env:PYTHONUTF8
try {
    $env:PYINSTALLER_CONFIG_DIR=$taskCache
    $env:PYTHONUTF8='1'
    Push-Location (Join-Path $taskRoot 'frontend')
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } } finally { Pop-Location }
    $taskWeb=Join-Path $taskRoot 'frontend\dist'
    if (-not (Test-Path -LiteralPath (Join-Path $taskWeb 'index.html') -PathType Leaf)) { throw 'Frontend index.html missing.' }
    & $taskPython -m PyInstaller --noconfirm --workpath $taskWork --distpath $taskDist (Join-Path $taskRoot 'packaging\seedlab.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $taskPackage=Join-Path $taskDist 'SeedLab'
    New-Item -ItemType Directory -Path (Join-Path $taskPackage 'app\migrations'),(Join-Path $taskPackage 'config') -Force | Out-Null
    Copy-Item -LiteralPath $taskWeb -Destination (Join-Path $taskPackage 'app\web') -Recurse
    Copy-Item -LiteralPath (Join-Path $taskRoot 'backend\alembic\env.py') -Destination (Join-Path $taskPackage 'app\migrations\env.py')
    New-Item -ItemType Directory -Path (Join-Path $taskPackage 'app\migrations\versions') -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $taskRoot 'backend\alembic\versions') -File -Filter '*.py' | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) {throw 'Redirected migration source refused'}
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $taskPackage 'app\migrations\versions')
    }
    foreach ($taskName in @('LICENSE','AUTHORS.md')) { Copy-Item -LiteralPath (Join-Path $taskRoot $taskName) -Destination $taskPackage }
    Copy-Item -LiteralPath (Join-Path $taskRoot 'packaging\使用说明.txt') -Destination $taskPackage
    & $taskPython -B -c "from app.services.migrations import migration_heads; assert migration_heads(r'$taskPackage\app\migrations') == ('c6d91f28a405',)"
    if ($LASTEXITCODE -ne 0) { throw 'Packaged migration resources failed head verification.' }
    & $taskPython (Join-Path $taskRoot 'scripts\check_portable.py') --directory $taskPackage
    if ($LASTEXITCODE -ne 0) { throw 'Portable directory safety gate failed.' }
    $taskVersion=(& $taskPython -c 'from app.version import VERSION; print(VERSION)').Trim()
    $taskZip=Join-Path $taskDist "SeedLab-v$taskVersion-portable.zip"
    Compress-Archive -LiteralPath $taskPackage -DestinationPath $taskZip -CompressionLevel Optimal
    & $taskPython (Join-Path $taskRoot 'scripts\check_portable.py') --directory $taskPackage --zip $taskZip --report (Join-Path $taskDist 'artifact-report.json')
    if ($LASTEXITCODE -ne 0) { throw 'Portable ZIP safety gate failed.' }
    Write-Host "[DONE] Portable directory: $taskPackage"
    Write-Host "[DONE] Portable ZIP: $taskZip"
} finally {
    $env:PYINSTALLER_CONFIG_DIR=$taskOldCache
    $env:PYTHONUTF8=$taskOldUtf8
}
