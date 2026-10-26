[CmdletBinding()]
param(
    [string]$NodePath = 'node',
    [string]$PythonPath = 'python'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

$required = @(
    'README.md',
    'DISCLAIMER.md',
    'LICENSE',
    'windows-cua-fallback\SKILL.md',
    'windows-cua-fallback\agents\openai.yaml',
    'windows-cua-fallback\scripts\cua_fallback.mjs',
    'windows-cua-fallback\scripts\window_snapshot.py',
    'legacy\install-codex-workspace-runtime-win10.mjs',
    'legacy\extract_runtime_tar.py'
)
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relative))) {
        throw "Missing required file: $relative"
    }
}

$skill = Get-Content -LiteralPath (Join-Path $root 'windows-cua-fallback\SKILL.md') -Raw
if ($skill -notmatch '(?ms)^---\s*\r?\nname:\s*windows-cua-fallback\s*\r?\ndescription:\s*.+?\r?\n---') {
    throw 'SKILL.md frontmatter is missing or invalid.'
}

Invoke-Checked $NodePath @('--check', (Join-Path $root 'windows-cua-fallback\scripts\cua_fallback.mjs'))
Invoke-Checked $NodePath @('--check', (Join-Path $root 'legacy\install-codex-workspace-runtime-win10.mjs'))
Invoke-Checked $PythonPath @('-m', 'py_compile', (Join-Path $root 'windows-cua-fallback\scripts\window_snapshot.py'), (Join-Path $root 'legacy\extract_runtime_tar.py'))
$previousTestPython = $env:TEST_PYTHON
try {
    $env:TEST_PYTHON = $PythonPath
    Invoke-Checked $NodePath @('--test', (Join-Path $root 'tests\cua_fallback.test.mjs'), (Join-Path $root 'tests\runtime-installer.test.mjs'))
    Invoke-Checked $PythonPath @('-m', 'unittest', 'discover', '-s', (Join-Path $root 'tests'), '-p', 'test_*.py')
}
finally {
    $env:TEST_PYTHON = $previousTestPython
}

& (Join-Path $root 'tests\Test-SkillInstaller.ps1') -ProjectRoot $root

$forbidden = @(
    [regex]::Escape($env:USERPROFILE),
    [regex]::Escape($root),
    ('S-1-5-' + '21-'),
    'gho_[A-Za-z0-9]+'
)
$textFiles = Get-ChildItem -LiteralPath $root -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]\.git[\\/]' -and $_.Extension -in @('.md', '.mjs', '.js', '.py', '.ps1', '.json', '.yaml', '.yml', '.txt')
}
foreach ($pattern in $forbidden) {
    $hit = $textFiles | Select-String -Pattern $pattern
    if ($hit) {
        $hitPaths = @($hit.Path | Select-Object -Unique -First 3)
        throw "Privacy residue matched '$pattern': $($hitPaths -join ', ')"
    }
}

Write-Host 'Project validation passed.'
