# Web UI — Mobile & Remote Access

`oh webui` launches a small FastAPI server that serves a React SPA. It is
the easiest way to chat with OpenHarness **from your phone, tablet, or
another laptop** without exposing a terminal to the network.

> Looking for the developer / build docs? See
> [`frontend/webui/README.md`](../frontend/webui/README.md).

## Why Web UI

- **Phone-friendly** — the same agent you run in the terminal, but with
  big tap targets, a thumb-reach permission sheet, and Markdown
  rendering. Nothing about your existing config changes.
- **Stay logged in to your provider** — the Mac runs the model session,
  the phone is just a thin client. Your `oh setup` profile, skills,
  and `MEMORY.md` are unchanged.
- **One command** — `oh webui` and you're live. No Docker, no nginx, no
  account.
- **Same runtime as the TUI** — tools, hooks, permissions, subagents,
  cron, MCP servers all behave identically.

```
┌──────────────┐        Wi-Fi / tunnel         ┌─────────────────────┐
│  📱 phone    │ ────────────────────────────▶ │  🖥️  your Mac       │
│  Safari /    │   https://…/?token=…          │   oh webui :8765    │
│  Chrome      │                               │   QueryEngine, tools│
└──────────────┘                               └─────────────────────┘
```

## Quick start (local only)

```bash
oh webui
# 🌐 OpenHarness Web UI ready at:
#    http://127.0.0.1:8765/?token=<token>
```

Open that URL in your desktop browser. The `?token=…` is captured to
`localStorage` so refreshes work without it.

## 1. Local LAN access (phone on the same Wi-Fi)

Bind to all interfaces and pick a port your firewall allows:

```bash
oh webui --host 0.0.0.0 --port 8765
```

Find your Mac's LAN IP:

```bash
ipconfig getifaddr en0          # Wi-Fi
# or
ipconfig getifaddr en1          # Ethernet
```

On the phone (same Wi-Fi), open:

```
http://<your-mac-ip>:8765/?token=<token>
```

Once loaded, the token sticks in `localStorage` — bookmark the URL
without the query string for daily use.

> ⚠️ This sends everything over **plain HTTP**. Fine for your home
> network, **not** fine for café Wi-Fi or anything you don't trust.
> Use a tunnel (below) instead.

## 2. Remote access via Cloudflare Tunnel  *(recommended, free)*

Cloudflare gives you a free HTTPS URL with no port-forwarding and no
account required for quick tunnels.

```bash
brew install cloudflared

# Run oh webui in one terminal (stay on 127.0.0.1 — that's fine!)
oh webui

# In another terminal, expose port 8765:
cloudflared tunnel --url http://localhost:8765
```

`cloudflared` prints something like:

```
Your quick Tunnel has been created! Visit it at:
https://random-words-1234.trycloudflare.com
```

On your phone, open:

```
https://random-words-1234.trycloudflare.com/?token=<token>
```

You now have **HTTPS, end-to-end**, without exposing anything on your
LAN. Stop the tunnel with `Ctrl+C` when you're done — the URL dies with
it. For a stable URL, log in with `cloudflared tunnel login` and create
a named tunnel.

## 3. Remote access via Tailscale  *(recommended for personal use)*

[Tailscale](https://tailscale.com) is a zero-config WireGuard VPN; once
both devices are on your tailnet, your phone can reach your Mac as if
they were on the same LAN, from anywhere.

1. Install the Tailscale app on **both** the Mac and the phone, sign in
   with the same account.
2. Find your Mac's Tailscale IP (starts with `100.`):

   ```bash
   tailscale ip -4
   ```

3. Run the server bound to all interfaces (Tailscale binds a private
   `100.x.x.x` address):

   ```bash
   oh webui --host 0.0.0.0 --port 8765
   ```

4. On the phone:

   ```
   http://100.x.x.x:8765/?token=<token>
   ```

### Tailscale Funnel — public HTTPS, no third-party tunnel

If you want a public HTTPS URL backed by Tailscale (no `cloudflared`
needed):

```bash
oh webui --host 127.0.0.1 --port 8765
tailscale funnel 8765
```

Tailscale prints a `https://<your-mac>.<tailnet>.ts.net/` URL with a
real cert. Combine that with `?token=<token>` and you're done.

## 4. Remote access via ngrok  *(alternative)*

```bash
brew install ngrok        # or download from ngrok.com
oh webui                  # default 127.0.0.1:8765
ngrok http 8765
```

ngrok prints a `https://*.ngrok-free.app` URL. Same drill — append
`?token=<token>`.

## 🔐 Security warnings — read before going public

The Web UI auth model is intentionally minimal. Read this section.

- **The token is the only auth.** Anyone with the URL + token has the
  same privileges as `oh` running on your Mac: it can read your files,
  run shell commands, hit your provider account, etc. **Treat the token
  like an SSH key.**
- **The token is regenerated on every restart.** If you want a stable
  URL across restarts (e.g. for a bookmark), pass a fixed token:

  ```bash
  oh webui --token "$(openssl rand -hex 32)"
  ```

  Store that value in your password manager.
- **Don't bind to `0.0.0.0` on untrusted networks.** Coffee-shop Wi-Fi,
  conference Wi-Fi, hotel Wi-Fi — assume hostile. Use a tunnel
  (Cloudflare / Tailscale / ngrok) and keep `--host 127.0.0.1`.
- **Prefer HTTPS-only tunnels.** Cloudflare Tunnel and Tailscale Funnel
  give you free HTTPS. Plain HTTP over the public internet leaks the
  token in transit.
- **Don't put the token in a public link / screenshot.** It bypasses
  all the above. If a token leaks, restart the server (or pass a new
  `--token`).
- **Disable when not in use.** `Ctrl+C` the server when you're done. It
  takes one second to bring it back up.

## 📱 Mobile UX tips

- **Add to Home Screen.** Safari → Share → *Add to Home Screen* (or
  Chrome → ⋮ → *Add to Home Screen*). The app gets its own icon and
  launches without browser chrome — the SPA already ships with the
  right `viewport` and `theme-color` meta tags.
- **Bookmark the post-login URL** (without `?token=…`). Once the token
  is in `localStorage`, the SPA re-uses it on every visit.
- **Permission modals are bottom-sheets.** Approval prompts slide up
  from the bottom edge so the *Allow* / *Deny* buttons land in
  thumb-reach. No mis-taps when the agent asks for shell access.
- **Long-press a transcript bubble** to copy its content (assistant
  message, tool result, etc.) — works the same as long-pressing a chat
  message in iMessage / WhatsApp.
- **Pull-to-refresh** is disabled inside the chat to prevent accidental
  reloads while scrolling long transcripts.
- **Landscape works**, but the bottom-sheet modals assume portrait —
  rotate back to portrait when an approval pops up.

## New in the Web UI

The Web UI now includes the main workflows that used to be easier to reach from the terminal:

- **History / Resume** — browse past sessions, open a transcript, and resume a session from the same state.
- **Mode toggles** — switch permission mode, effort, passes, fast mode, vim keybindings, output style, and theme from the browser.
- **Settings** — manage modes, providers, models, and agents without editing local config files by hand. The settings UI includes notification and auto-compact controls, provider connection status and batch verify, model search and capability badges, agent prompt preview/clone/validation flows, and consistent dirty-state and unsaved-change feedback.
- **Pipeline dashboard** — view autopilot cards in a kanban-style dashboard, move work through the pipeline, and submit new ideas.
- **Auto review** — inspect review state, see pipeline progress, and follow the review/verification flow from the UI.

For the detailed settings guide, see [`WEBUI-SETTINGS.md`](./WEBUI-SETTINGS.md).
For the pipeline workflow, see [`WEBUI-PIPELINE.md`](./WEBUI-PIPELINE.md).

## Troubleshooting

| Symptom                                 | Likely cause / fix                                                                 |
|-----------------------------------------|------------------------------------------------------------------------------------|
| `401 Invalid or missing token`          | URL is missing `?token=…` and `localStorage` is empty. Re-open the printed URL.    |
| WebSocket closes immediately            | Same as above — WS auth uses the same token via `?token=` query.                   |
| Phone can't reach `http://192.168.x.y:…`| `oh webui` is bound to `127.0.0.1`. Restart with `--host 0.0.0.0`.                 |
| Token changes on every restart          | Pass `--token <fixed>` to keep it stable.                                          |
| Cloudflare URL works once then 404      | `cloudflared` quick tunnels are ephemeral; create a named tunnel for persistence.  |
| SPA loads but shows a blank screen      | You're on a dev build but the server can't find `frontend/webui/dist`. Run `npm run build`. |

## See also

- [`frontend/webui/README.md`](../frontend/webui/README.md) — frontend
  architecture, build, and dev workflow
- [`src/openharness/webui/server/app.py`](../src/openharness/webui/server/app.py)
  — FastAPI routes and WebSocket handler
- [`src/openharness/webui/server/auth.py`](../src/openharness/webui/server/auth.py)
  — token extraction and verification
