# Agent harness installer for Windows (PowerShell 5.1 or 7+).
# macOS, Linux and WSL: use install.sh. Both run lib/install.py.
#
#   ~\.agents\install.ps1 [--dry-run] [--no-plugins]

$installer = Join-Path $PSScriptRoot 'lib\install.py'
$candidates = @(@('py', '-3'), @('python'), @('python3'))
foreach ($candidate in $candidates) {
    $exe = $candidate[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $prefix = @($candidate | Select-Object -Skip 1)
    # The Microsoft Store "python" alias exists without a real interpreter; check it runs.
    & $exe @prefix -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>$null
    if ($LASTEXITCODE -ne 0) { continue }
    & $exe @prefix $installer @args
    exit $LASTEXITCODE
}
Write-Error 'Python 3.8 or later is required (the hooks run on it). Install it from python.org and run this again.'
exit 1
