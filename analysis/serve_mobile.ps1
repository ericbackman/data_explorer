# Serve the analysis env as a notebook server on localhost, for phone access via
# a Cloudflare Tunnel (see MOBILE.md). Binds to 127.0.0.1 ONLY — never expose this
# port directly; the tunnel reaches it locally and Cloudflare Access gates it.
#
#   .\serve_mobile.ps1              # full notebook editor (default)
#   .\serve_mobile.ps1 -Mode run    # app view of mobile.py (lightest for phone)
[CmdletBinding()]
param(
    [int]$Port = 2718,
    [ValidateSet('edit', 'run')]
    [string]$Mode = 'edit'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Stable access token (defense-in-depth behind Cloudflare Access). Gitignored.
$tokenFile = Join-Path $here '.marimo_token'
if (-not (Test-Path $tokenFile)) {
    [guid]::NewGuid().ToString('N') | Out-File -FilePath $tokenFile -Encoding ascii -NoNewline
    Write-Host "Generated a new marimo token -> .marimo_token"
}
$token = (Get-Content $tokenFile -Raw).Trim()

$common = @('--headless', '--host', '127.0.0.1', '--port', "$Port")
if ($Mode -eq 'edit') {
    $marimoArgs = @('edit') + $common + @('--token-password', $token)
}
else {
    $marimoArgs = @('run', 'mobile.py') + $common + @('--token-password', $token)
}

Write-Host "Serving marimo ($Mode) on http://127.0.0.1:$Port   (token in .marimo_token)"
python -m uv run --directory $here marimo @marimoArgs
