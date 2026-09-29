param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\', '/')
$rootPrefix = $repoRoot + [IO.Path]::DirectorySeparatorChar

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot '.git') -PathType Container)) {
    throw 'Cannot find the SeedLab Git repository. No files were removed.'
}

$removed = 0
$skipped = 0

function Remove-ApprovedItem {
    param([IO.FileSystemInfo]$Item)

    $fullPath = [IO.Path]::GetFullPath($Item.FullName)
    if (-not $fullPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the repository: $fullPath"
    }
    if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Write-Output "[SKIP] Link: $fullPath"
        $script:skipped++
        return
    }
    if ($DryRun) {
        Write-Output "[SKIP] Dry run: $fullPath"
        $script:skipped++
        return
    }

    try {
        if ($Item.PSIsContainer) {
            Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction Stop
        } else {
            Remove-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        }
    } catch {
        Write-Output "[SKIP] Could not remove $fullPath`: $($_.Exception.Message)"
        $script:skipped++
        return
    }
    Write-Output "[REMOVE] $fullPath"
    $script:removed++
}

# Only these temporary directory names may be removed, and only at the project,
# backend, or frontend root. Other .tmp-* directories are deliberately retained.
foreach ($base in @($repoRoot, (Join-Path $repoRoot 'backend'), (Join-Path $repoRoot 'frontend'))) {
    foreach ($item in Get-ChildItem -LiteralPath $base -Force -Directory) {
        if ($item.Name -match '^(\.test-temp-|\.tmp-pytest-|\.tmp-round2-)') {
            Remove-ApprovedItem $item
        }
    }
}

$dist = Join-Path $repoRoot 'frontend\dist'
if (Test-Path -LiteralPath $dist -PathType Container) {
    Remove-ApprovedItem (Get-Item -LiteralPath $dist -Force)
}

# Walk source folders without entering user data, dependencies, migrations,
# unknown temporary directories, or links.
$protectedNames = @('.git', '.venv', 'node_modules', 'data', 'uploads', 'logs', 'backups', 'migrations', 'alembic', '.agents', '.codex')
$pending = [System.Collections.Generic.Stack[string]]::new()
$pending.Push($repoRoot)
while ($pending.Count -gt 0) {
    $directory = $pending.Pop()
    foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
        if ($item.PSIsContainer) {
            if ($item.Name -eq '__pycache__' -or $item.Name -eq '.pytest_cache') {
                Remove-ApprovedItem $item
            } elseif ($protectedNames -contains $item.Name -or
                      $item.Name -like '.tmp-*' -or
                      $item.Name -like '.test-temp*' -or
                      ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                continue
            } else {
                $pending.Push($item.FullName)
            }
        } elseif ($item.Extension -eq '.pyc') {
            Remove-ApprovedItem $item
        }
    }
}

Write-Output "[DONE] Removed $removed items; skipped $skipped items."
