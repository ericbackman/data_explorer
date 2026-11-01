# Serve JupyterLab on localhost for phone/remote access via the same tunnel as
# marimo (see MOBILE.md). Binds 127.0.0.1 only; put an auth gate on the hostname.
#
#   .\serve_jupyter.ps1 -Origin https://your-host.example
[CmdletBinding()]
param(
    [int]$Port = 8888,
    [Parameter(Mandatory)]
    [string]$Origin
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Stable token (defense-in-depth behind Access). Gitignored.
$tokenFile = Join-Path $here '.jupyter_token'
if (-not (Test-Path $tokenFile)) {
    [guid]::NewGuid().ToString('N') | Out-File -FilePath $tokenFile -Encoding ascii -NoNewline
    Write-Host "Generated a new Jupyter token -> .jupyter_token"
}
$token = (Get-Content $tokenFile -Raw).Trim()

# allow_remote_access + allow_origin let Jupyter accept the proxied hostname and
# its websockets (it otherwise rejects non-localhost Host/Origin headers).
$jargs = @(
    'lab', '--no-browser', '--ip', '127.0.0.1', '--port', "$Port",
    "--ServerApp.token=$token",
    '--ServerApp.allow_remote_access=True',
    "--ServerApp.allow_origin=$Origin",
    '--ServerApp.trust_xheaders=True'
)
Write-Host "Serving JupyterLab on http://127.0.0.1:$Port   (token in .jupyter_token)"
python -m uv run --directory $here jupyter @jargs
