# OpenHarness Web UI (frontend)

A React + Vite single-page app that talks to the OpenHarness runtime over a
single WebSocket. It is the third front-end alongside the CLI and the React
TUI, and it ships in the same wheel as the Python package.

## Overview

The Web UI gives you the full `oh` interactive experience inside a browser:

- **Mobile-friendly chat** — usable from a phone over Wi-Fi or a tunnel
  (see [`docs/WEBUI.md`](../../docs/WEBUI.md))
- **Full tool stream** — same transcript model as the React TUI: assistant
  messages, tool calls, tool results, system events
- **Permission modals** — interactive approval dialogs rendered as
  bottom-sheets, optimised for thumb reach
- **Session sidebar** — switch between sessions, see background tasks and
  cron jobs at a glance

It does **not** replace the CLI or TUI; it just adds a remote-access surface
that uses the same `BackendHost` runtime under the hood.

## Architecture

```
                ┌──────────────────────┐
                │      Browser         │
                │  React SPA  +  WS    │
                └─────────┬────────────┘
                          │  /api/ws/{session_id}?token=…
                          ▼
                ┌──────────────────────┐
                │   FastAPI server     │   src/openharness/webui/server/
                │  app.py · auth.py    │
                │  sessions.py         │
                └─────────┬────────────┘
                          │  bridge.py
                          ▼
                ┌──────────────────────┐
                │  WebSocketBackendHost│   ReactBackendHost subclass —
                │  (one per session)   │   same protocol as the TUI
                └─────────┬────────────┘
                          │
                          ▼
                ┌──────────────────────┐
                │     QueryEngine      │   tools, skills, hooks,
                │  (OpenHarness core)  │   permissions, providers
                └──────────────────────┘
```

The HTTP surface is intentionally tiny — most of the action happens on the
WebSocket. REST endpoints exist only to bootstrap a session and to back the
sidebar:

| Endpoint              | Auth     | Purpose                                  |
|-----------------------|----------|------------------------------------------|
| `GET  /api/health`    | none     | Liveness ping                            |
| `GET  /api/meta`      | bearer   | cwd / model / permission mode            |
| `POST /api/sessions`  | bearer   | Create a new session, returns id         |
| `GET  /api/sessions`  | bearer   | List sessions                            |
| `GET  /api/tasks`     | bearer   | Snapshot of background tasks             |
| `GET  /api/cron/jobs` | bearer   | Snapshot of cron jobs                    |
| `WS   /api/ws/{id}`   | token    | Bidirectional event stream for a session |

## Quick start

### Production mode — one command

```bash
oh webui
```

This starts the FastAPI server on `127.0.0.1:8765` and serves the bundled
SPA from inside the wheel. The terminal prints a URL like:

```
🌐 OpenHarness Web UI ready at:
   http://127.0.0.1:8765/?token=<random-token>
```

Open that URL in any browser. The token is captured from `?token=…` and
stored in `localStorage` so subsequent visits don't need it in the URL.

### Dev mode — Vite + hot reload

In one terminal, run the Python server (no bundled SPA needed):

```bash
python -m openharness webui
# or: oh webui
```

In another terminal, run the Vite dev server:

```bash
cd frontend/webui
npm install      # first time only
npm run dev
```

Vite serves the SPA on `http://localhost:5173/` and proxies `/api/*` and
the WebSocket to `127.0.0.1:8765` (see [`vite.config.ts`](./vite.config.ts)).
Visit `http://localhost:5173/?token=<token>` once to seed the token.

## Build

```bash
cd frontend/webui
npm install
npm run build
```

Output lands in `frontend/webui/dist/`. The FastAPI app picks this up
automatically when running from a repo checkout — see `_frontend_dist_dir()`
in [`server/app.py`](../../src/openharness/webui/server/app.py). When
packaged as a wheel, the same files are bundled at
`openharness/_webui_frontend/`.

## Project layout

```
frontend/webui/
├── index.html              # Vite entry, sets viewport + theme-color
├── vite.config.ts          # /api proxy → 127.0.0.1:8765
├── package.json            # React 19 + Zustand + react-markdown + Tailwind 4
├── public/
└── src/
    ├── main.tsx            # React root
    ├── App.tsx             # Layout: <Header> + <Sidebar> + <Transcript> + modals
    ├── index.css           # Tailwind entry
    ├── api/
    │   ├── client.ts       # fetch + WebSocket wrappers, token handling
    │   └── types.ts        # Shared event / message shapes
    ├── store/
    │   └── session.ts      # Zustand store: transcript, modals, status
    └── components/
        ├── Header.tsx          # cwd, model, status pill
        ├── Sidebar.tsx         # sessions / tasks / cron
        ├── Transcript.tsx      # message bubbles, tool blocks
        ├── InputBar.tsx        # composer + send
        ├── PermissionModal.tsx # approval bottom-sheet
        ├── QuestionModal.tsx   # ask-user-question
        └── SelectModal.tsx     # select-from-options
```

The frontend has no build-time coupling to the Python tree — it talks to
the server purely through `/api/*` and `/api/ws/{id}`.

## Auth model

Single-user bearer token, kept deliberately simple:

1. **Server start.** A 32-byte URL-safe token is generated by
   `WebUIConfig` (or you supply your own with `--token`).
2. **URL bootstrap.** The server prints
   `http://<host>:<port>/?token=<token>`. The SPA reads `?token=` on first
   load and stores it in `localStorage` under `oh:token`. The query string
   is then stripped from the address bar.
3. **HTTP requests.** `api/client.ts` adds
   `Authorization: Bearer <token>` to every fetch.
4. **WebSocket.** Browsers can't set headers on `WebSocket`, so the token
   is appended as `?token=` on the WS URL. The server accepts
   `Authorization` header, `?token=` query, or `oh_token` cookie — see
   [`server/auth.py`](../../src/openharness/webui/server/auth.py).
5. **Token lifetime.** Tokens are regenerated on every restart unless you
   pass `--token <fixed>`. There is **no** user/password, no refresh, no
   role separation — treat the token as a password and only expose the
   server through a trusted tunnel.

For deployment guidance, mobile use, Cloudflare / Tailscale tunnels, and
the security caveats around `--host 0.0.0.0`, see
[`docs/WEBUI.md`](../../docs/WEBUI.md).
