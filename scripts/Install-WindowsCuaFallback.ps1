[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$CodexHome,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($CodexHome)) {
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        $CodexHome = $env:CODEX_HOME
    }
    else {
        $CodexHome = Join-Path $env:USERPROFILE '.codex'
    }
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $repositoryRoot 'windows-cua-fallback')).Path
$codexHomeFull = [System.IO.Path]::GetFullPath($CodexHome)
$skillsRoot = Join-Path $codexHomeFull 'skills'
$destination = Join-Path $skillsRoot 'windows-cua-fallback'
$backupRoot = Join-Path $codexHomeFull 'skill-backups'
$stamp = '{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmssfff'), ([guid]::NewGuid().ToString('N').Substring(0, 8))
$backup = Join-Path $backupRoot "windows-cua-fallback-$stamp"
$staging = Join-Path $skillsRoot ".windows-cua-fallback-staging-$([guid]::NewGuid().ToString('N'))"

function Assert-ContainedPath {
    param(
        [Parameter(Mandatory)] [string]$Parent,
        [Parameter(Mandatory)] [string]$Child,
        [Parameter(Mandatory)] [string]$Label
    )
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $childFull = [System.IO.Path]::GetFullPath($Child)
    if (-not $childFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label escapes its intended parent: $childFull"
    }
}

Assert-ContainedPath -Parent $codexHomeFull -Child $skillsRoot -Label 'Skills root'
Assert-ContainedPath -Parent $skillsRoot -Child $destination -Label 'Destination'
Assert-ContainedPath -Parent $skillsRoot -Child $staging -Label 'Staging directory'
Assert-ContainedPath -Parent $codexHomeFull -Child $backup -Label 'Backup directory'

$expected = @(
    'SKILL.md',
    'agents\openai.yaml',
    'scripts\cua_fallback.mjs',
    'scripts\window_snapshot.py'
)

$actual = Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc'
} | ForEach-Object {
    $_.FullName.Substring($sourceRoot.Length + 1)
}

$unexpected = @($actual | Where-Object { $_ -notin $expected })
$missing = @($expected | Where-Object { $_ -notin $actual })
if ($unexpected.Count -or $missing.Count) {
    throw "Skill package mismatch. Missing: $($missing -join ', '); unexpected: $($unexpected -join ', ')"
}

if ((Test-Path -LiteralPath $destination) -and -not $Force) {
    throw "Destination already exists: $destination. Re-run with -Force after inspecting it."
}

if (-not $PSCmdlet.ShouldProcess($destination, 'Install Windows CUA fallback skill')) {
    return
}

New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$movedExisting = $false
try {
    foreach ($relative in $expected) {
        $source = Join-Path $sourceRoot $relative
        $target = Join-Path $staging $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
            throw "Staged file hash mismatch: $relative"
        }
    }

    if (Test-Path -LiteralPath $destination) {
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        Move-Item -LiteralPath $destination -Destination $backup
        $movedExisting = $true
    }

    Move-Item -LiteralPath $staging -Destination $destination
    Write-Host "Installed: $destination"
    if ($movedExisting) {
        Write-Host "Previous version retained: $backup"
    }
    Write-Host 'Restart Codex if the skill is not discovered immediately.'
}
catch {
    if (-not (Test-Path -LiteralPath $destination) -and $movedExisting -and (Test-Path -LiteralPath $backup)) {
        Move-Item -LiteralPath $backup -Destination $destination
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Assert-ContainedPath -Parent $skillsRoot -Child $staging -Label 'Staging cleanup target'
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
