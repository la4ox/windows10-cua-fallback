[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = [System.IO.Path]::GetFullPath($ProjectRoot)
$temporaryRoot = Join-Path $root '.tmp'
$caseRoot = Join-Path $temporaryRoot "skill-installer-$([guid]::NewGuid().ToString('N'))"
$installer = Join-Path $root 'scripts\Install-WindowsCuaFallback.ps1'
$source = Join-Path $root 'windows-cua-fallback'
$relativeFiles = @(
    'SKILL.md',
    'agents\openai.yaml',
    'scripts\cua_fallback.mjs',
    'scripts\window_snapshot.py'
)

function Assert-MatchingFiles {
    param([string]$ActualRoot)
    foreach ($relative in $relativeFiles) {
        $expectedHash = (Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash
        $actualHash = (Get-FileHash -LiteralPath (Join-Path $ActualRoot $relative) -Algorithm SHA256).Hash
        if ($expectedHash -ne $actualHash) {
            throw "Installed file differs from source: $relative"
        }
    }
}

try {
    & $installer -CodexHome $caseRoot
    $installed = Join-Path $caseRoot 'skills\windows-cua-fallback'
    Assert-MatchingFiles -ActualRoot $installed

    $refused = $false
    try {
        & $installer -CodexHome $caseRoot
    }
    catch {
        $refused = $_.Exception.Message -match 'Destination already exists'
    }
    if (-not $refused) {
        throw 'Repeated installation without -Force was not rejected.'
    }

    & $installer -CodexHome $caseRoot -Force
    Assert-MatchingFiles -ActualRoot $installed
    $backups = @(Get-ChildItem -LiteralPath (Join-Path $caseRoot 'skill-backups') -Directory)
    if ($backups.Count -ne 1) {
        throw "Expected one retained backup, found $($backups.Count)."
    }
    Assert-MatchingFiles -ActualRoot $backups[0].FullName
    Write-Host 'Skill installer test passed.'
}
finally {
    if (Test-Path -LiteralPath $caseRoot) {
        $temporaryFull = [System.IO.Path]::GetFullPath($temporaryRoot).TrimEnd('\') + '\'
        $caseFull = [System.IO.Path]::GetFullPath($caseRoot)
        if (-not $caseFull.StartsWith($temporaryFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean unexpected test path: $caseFull"
        }
        Remove-Item -LiteralPath $caseRoot -Recurse -Force
    }
}
