# Analysis on your phone (marimo in Safari)

Serve the `analysis/` environment from this Windows machine and open it in mobile
Safari, gated behind Cloudflare Access. The DBs never leave the machine — your
phone just talks to it over an authenticated tunnel, so the data is always live.

## Phase 1 — serve locally (verify on this machine)

```powershell
cd $env:USERPROFILE\Github\data_explorer\analysis
.\serve_mobile.ps1                  # full notebook editor on http://127.0.0.1:2718
# or: .\serve_mobile.ps1 -Mode run  # app-only view of mobile.py (lightest for phone)
```

Open the printed `http://127.0.0.1:2718/...` URL here to confirm it works. The
access token is in `.marimo_token` (gitignored).

## Phase 2 — expose to your phone (Cloudflare Tunnel + Access)

`cloudflared` is **not installed** yet. One-time setup:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login            # browser; pick the ericbackman.com zone
```

Create a named tunnel and point a hostname at the local marimo port:

```powershell
cloudflared tunnel create home-lab
cloudflared tunnel route dns home-lab lab.ericbackman.com
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: home-lab
credentials-file: $env:USERPROFILE\.cloudflared\<TUNNEL_ID>.json
ingress:
  - hostname: lab.ericbackman.com
    service: http://127.0.0.1:2718
  - service: http_status:404
```

Gate it behind Access, then run both halves:

```powershell
# Cloudflare Zero Trust > Access > Applications > Add: Self-hosted,
#   domain lab.ericbackman.com, policy "Allow" emails = your email.
cloudflared tunnel run home-lab     # terminal 1
.\serve_mobile.ps1                  # terminal 2
```

On the iPhone: open `https://lab.ericbackman.com` → Access email login → paste the
marimo token (`.marimo_token`) → Share → **Add to Home Screen**.

### Faster trial (less secure — 2-minute test)

```powershell
cloudflared tunnel --url http://127.0.0.1:2718   # prints a temporary *.trycloudflare.com URL
```

That URL is public (no Access) and relies on the marimo token alone — use it only
for a quick test, then Ctrl-C.

## Security model

- marimo binds to **127.0.0.1 only** — the port is never open to your LAN or the
  internet; the tunnel reaches it locally.
- **Cloudflare Access** email-gates the hostname (same pattern as your other
  sites); the **marimo token** is a second factor.
- DuckDB attaches every DB **read-only** — phone queries can't mutate anything.
- Secrets (`.marimo_token`, tunnel credentials) are gitignored or live under
  `~/.cloudflared`, never in the repo.
- The machine must be on with `cloudflared` running. For always-on, register
  `cloudflared service install` and marimo as a Scheduled Task — a later step.
