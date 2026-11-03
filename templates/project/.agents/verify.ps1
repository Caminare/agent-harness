# Pass/fail check that agents run before finishing a turn (via the harness Stop
# hook) and before calling a task done. PowerShell twin of verify.sh: on Windows
# the hook prefers this file, elsewhere it prefers verify.sh. Keep one of them,
# or both if contributors use different systems. Keep it fast: the hook times
# out after 280 seconds by default (AGENTS_VERIFY_TIMEOUT).
#
# This starter auto-detects .NET, Flutter/Dart and npm projects up to three
# folders deep. Replace it with this repository's real commands once known.
$ErrorActionPreference = 'Stop'
Set-Location (git rev-parse --show-toplevel)

function Invoke-Step([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Find-First([string]$filter) {
    Get-ChildItem -Recurse -Depth 3 -File -Filter $filter -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '[\\/](node_modules|\.dart_tool)[\\/]' } |
        Select-Object -First 1
}

$ran = $false

$solution = Find-First '*.sln'
if (-not $solution) { $solution = Find-First '*.slnx' }
if ($solution) {
    Invoke-Step dotnet @('build', $solution.FullName, '--nologo', '-v', 'q', '-nodeReuse:false')
    Invoke-Step dotnet @('test', $solution.FullName, '--nologo', '-v', 'q', '--no-build')
    $ran = $true
}

$pubspec = Find-First 'pubspec.yaml'
if ($pubspec) {
    Push-Location $pubspec.DirectoryName
    $targets = @('lib', 'test', 'bin') | Where-Object { Test-Path $_ }
    if ($targets) { Invoke-Step dart (@('format', '--output=none', '--set-exit-if-changed') + $targets) }
    if (Select-String -Path 'pubspec.yaml' -Pattern 'sdk: flutter' -Quiet) {
        Invoke-Step flutter @('analyze', '--no-fatal-infos')
        if (Test-Path 'test') { Invoke-Step flutter @('test') }
    } else {
        Invoke-Step dart @('analyze', '--no-fatal-warnings')
        if (Test-Path 'test') { Invoke-Step dart @('test') }
    }
    Pop-Location
    $ran = $true
}

if ((Test-Path 'package.json') -and (Select-String -Path 'package.json' -Pattern '"test"\s*:' -Quiet)) {
    Invoke-Step npm @('test', '--silent')
    $ran = $true
}

if (-not $ran) {
    [Console]::Error.WriteLine('verify.ps1: no known stack detected, nothing verified. Edit .agents/verify.ps1 for this repo.')
}
exit 0
