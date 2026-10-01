$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules') -PathType Container)) {
    throw 'Frontend dependencies are missing. Install them explicitly in frontend before building.'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js / npm is missing. Install the build tools before building.'
}
Push-Location -LiteralPath $frontendPath
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed; do not start the production server.' }
    $indexPath = Join-Path $frontendPath 'dist/index.html'
    if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) {
        throw 'The build did not produce frontend/dist/index.html.'
    }
    Write-Host "[DONE] Production frontend: $(Split-Path -Parent $indexPath)"
} finally {
    Pop-Location
}
