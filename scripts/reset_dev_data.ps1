param([switch]$DryRun, [switch]$Yes)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按照 README 安装后端开发环境。' }
$resetArguments = @('-m', 'app.cli', 'reset-dev-data')
if ($DryRun) { $resetArguments += '--dry-run' }
if ($Yes) { $resetArguments += '--yes' }
Push-Location (Join-Path $projectRoot 'backend')
try { & $pythonPath @resetArguments; $resetExit = $LASTEXITCODE } finally { Pop-Location }
exit $resetExit
