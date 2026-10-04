# Builds the standalone importer only; does not touch the accepted portable.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Build requires the existing packaging environment.' }
$taskCommit = (& git -C $taskRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify importer source commit.' }
$taskChanges = & git -C $taskRoot status --porcelain --untracked-files=normal
if ($taskChanges) { throw 'Commit importer source before building so provenance identifies the reviewed code.' }
$taskWork = Join-Path $taskRoot ('build\legacy-importer-' + [guid]::NewGuid().ToString('N'))
$taskDist = Join-Path $taskRoot 'dist\legacy-importer-v1'
foreach ($taskPath in @($taskWork,$taskDist)) {
    $taskFull = [IO.Path]::GetFullPath($taskPath)
    if (-not $taskFull.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Build target escapes repository.' }
    $taskAncestor = $taskFull
    while ($taskAncestor) {
        if ((Test-Path -LiteralPath $taskAncestor) -and ((Get-Item -LiteralPath $taskAncestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Redirected build directory refused.' }
        $taskAncestor = Split-Path -Parent $taskAncestor
    }
    New-Item -ItemType Directory -Path $taskPath -Force | Out-Null
}
$taskProvenance = Join-Path $taskWork 'legacy_build_provenance.json'
@{ importer_version='1.0.0'; git_commit=$taskCommit; compatible_seedlab='0.5.1'; alembic_revision='d2e7a46b910c' } |
    ConvertTo-Json | Set-Content -LiteralPath $taskProvenance -Encoding utf8NoBOM
$taskOldProvenance = $env:SEEDLAB_IMPORTER_PROVENANCE
$taskOldCache = $env:PYINSTALLER_CONFIG_DIR
$taskOldUtf8 = $env:PYTHONUTF8
try {
    $env:SEEDLAB_IMPORTER_PROVENANCE=$taskProvenance
    $env:PYINSTALLER_CONFIG_DIR=Join-Path $taskWork 'cache'
    $env:PYTHONUTF8='1'
    & $taskPython -m PyInstaller --noconfirm --workpath $taskWork --distpath $taskDist (Join-Path $taskRoot 'packaging\legacy_importer.spec')
    if ($LASTEXITCODE -ne 0) { throw 'Importer build failed.' }
    $taskExe = Join-Path $taskDist 'SeedLabLegacyImport-v1.0.0.exe'
    & $taskPython (Join-Path $taskRoot 'scripts\maintenance\check_legacy_importer.py') --exe $taskExe --commit $taskCommit --report (Join-Path $taskDist 'artifact-report.json')
    if ($LASTEXITCODE -ne 0) { throw 'Importer artifact safety gate failed.' }
    Write-Host "[DONE] $taskExe"
} finally {
    $env:SEEDLAB_IMPORTER_PROVENANCE=$taskOldProvenance
    $env:PYINSTALLER_CONFIG_DIR=$taskOldCache
    $env:PYTHONUTF8=$taskOldUtf8
}
