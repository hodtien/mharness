# my-harness — Hướng dẫn toàn diện

Fork tùy biến của OpenHarness, tích hợp **bidirectional bridge** với
`~/.claude/settings.json` để dùng chung cấu hình proxy router với Claude Code,
hỗ trợ **per-agent model mapping** và **fallback chain** khi model lỗi.

---

## 1. Cài đặt

### Yêu cầu

- Python ≥ 3.12
- macOS / Linux
- Claude Code CLI đã cài và có file `~/.claude/settings.json`

### Bước cài

```bash
# Clone (nếu chưa có)
cd ~/harness/my-harness

# Tạo venv & cài
python3.12 -m venv .venv
source .venv/bin/activate
~/.local/bin/uv pip install -e .

# Thêm vào PATH (one-time)
echo 'export PATH="$HOME/harness/my-harness/.venv/bin:$PATH"' >> ~/.zshrc
exec zsh

# Verify
oh --help
```

### File cấu hình chính

- `~/.claude/settings.json` — **single source of truth** (model, agent_models, env)
- `~/.openharness/settings.json` — overrides cục bộ (tùy chọn)

---

## 2. Khởi động nhanh

```bash
# Activate bridge (đọc Claude config làm provider profile mặc định)
oh profile use claude-router

# Liệt kê profile
oh profile list

# Liệt kê model có sẵn (đọc từ ~/.claude/settings.json::models)
oh model list

# Switch model active
oh model use claude-architect-backup

# Spawn agent test
oh run "Hello, who are you?"
```

Nếu `claude-router [ready]` xuất hiện → bridge OK, auth token đã được đẩy
vào `ANTHROPIC_API_KEY` từ `env.ANTHROPIC_AUTH_TOKEN`.

---

## 3. Kiến trúc tổng quan

```
┌──────────────────────────────────────┐
│  ~/.claude/settings.json             │  ← single source of truth
│  - env.ANTHROPIC_BASE_URL            │
│  - env.ANTHROPIC_AUTH_TOKEN          │
│  - model (active)                    │
│  - models: { ... }                   │
│  - agent_models: { agent: chain }    │
└────────────┬─────────────────────────┘
             │ read (claude_bridge.py)
             ▼
┌──────────────────────────────────────┐
│  apply_claude_bridge(settings)       │
│  ├─ build_router_profile()           │
│  ├─ export_claude_auth_env()         │  ← inject ANTHROPIC_API_KEY
│  └─ register `claude-router` profile │
└────────────┬─────────────────────────┘
             ▼
┌──────────────────────────────────────┐
│  resolve_agent_model(settings,agent) │
│  Precedence:                         │
│    1. agent_override (CLI flag)      │
│    2. agent_map (claude settings)    │
│    3. profile.last_model/default     │
│    4. claude.active_model            │
└────────────┬─────────────────────────┘
             ▼
┌──────────────────────────────────────┐
│  AgentTool spawn                     │
│  - Filter chain by allowed_models    │
│  - Promote first valid → primary     │
└──────────────────────────────────────┘
```

---

## 4. Claude bridge — cốt lõi của fork

**Module:** `src/openharness/config/claude_bridge.py`

### Read direction (Claude → OpenHarness)

`read_claude_settings()` parse:

- `env.ANTHROPIC_BASE_URL` → `ProviderProfile.base_url`
- `env.ANTHROPIC_AUTH_TOKEN` → injected vào `ANTHROPIC_API_KEY` env
- `env.API_TIMEOUT_MS` → `ClaudeSettings.timeout_ms`
- `model` → active model
- `models{}` → `allowed_models` của profile `claude-router`
- `agent_models{}` → per-agent fallback chain (string hoặc list)

### Write direction (OpenHarness → Claude)

- `write_claude_model(name)` — đổi `model` (atomic + file lock)
- `write_agent_model(agent, chain)` — set `agent_models[agent]`
- `delete_agent_model(agent)` — xóa entry

### Auth bridge

`export_claude_auth_env()` chỉ inject env var khi **chưa có**
`ANTHROPIC_API_KEY` — không bao giờ ghi đè user override. Idempotent.

---

## 5. Quản lý model

```bash
# List
oh model list

# Switch active
oh model use claude-architect

# Show current
oh model current
```

Mọi thay đổi đều persist vào `~/.claude/settings.json::model` qua atomic
write + exclusive file lock — Claude Code & OpenHarness chạy song song
không thấy file half-written.

---

## 6. Per-agent model mapping

Map agent (planner, code-reviewer, worker…) sang model cụ thể.

```bash
# Set single
oh model agent set planner claude-architect

# Set fallback chain (comma-separated, no spaces)
oh model agent set planner "claude-architect,claude-architect-backup,claude-review"

# List
oh model agent list

# Get
oh model agent get planner
# → planner → claude-architect (fallbacks: claude-architect-backup, claude-review)

# Delete
oh model agent delete planner
```

### Lưu trữ trong JSON

Single chain → string (cho dễ đọc):

```json
"agent_models": { "planner": "claude-architect" }
```

Multi chain → list:

```json
"agent_models": {
  "planner": ["claude-architect", "claude-architect-backup", "claude-review"]
}
```

In-memory đều normalize về `list[str]` để xử lý đồng nhất.

### Precedence (cao → thấp)

1. **agent_override** — CLI flag runtime: `--agent-model planner=claude-x`
2. **agent_map** — `agent_models[agent]` trong `~/.claude/settings.json`
3. **profile_default** — `profile.last_model` hoặc `default_model`
4. **claude_active** — top-level `model` của Claude settings

---

## 7. Fallback chain (3-layer retry)

Khi model lỗi, harness có 3 lớp retry chạy theo thứ tự:

### Layer 1: HTTP-level retry (trong `AnthropicApiClient`)

`src/openharness/api/client.py:160-196`:

- `MAX_RETRIES=3`, exponential backoff với jitter ±25%
- `RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}`
- Tôn trọng header `retry-after` khi server cung cấp
- Trong suốt với caller — chỉ raise `RequestFailure`/`RateLimitFailure` khi
  đã exhaust toàn bộ retry

### Layer 2: Spawn-time chain filter (cho agent con)

`src/openharness/tools/agent_tool.py:69-93`:

1. Resolve full chain từ `resolve_agent_model()`
2. Filter chain bởi `profile.allowed_models`
3. Promote phần tử đầu tiên hợp lệ làm primary
4. Pass cho subprocess executor

Chỉ chạy 1 lần lúc spawn, không retry sau khi subprocess đã start.

### Layer 3: Runtime model switching (`FallbackApiClient`)

`src/openharness/api/fallback.py`, wired tại
`src/openharness/ui/runtime.py:_resolve_api_client_from_settings`:

- Wrap inner client; intercept `RequestFailure`/`RateLimitFailure` *sau khi*
  Layer 1 đã exhaust
- Replay request với model kế tiếp trong chain
- Yield `ModelSwitchEvent` để UI hiển thị "đang switch"
- `AuthenticationFailure` luôn propagate ngay (sai cred không fix bằng đổi model)

Chain cho main session lấy từ `agent_models["main"]` trong
`~/.claude/settings.json`. Nếu chỉ có 1 model thì wrapper passthrough.

### Cấu hình

```json
{
  "agent_models": {
    "main": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "worker": "claude-haiku-4-5"
  }
}
```

```bash
# Production agent: stable + backup + budget
oh model agent set worker "claude-haiku,claude-architect-backup"

# Critical agent: opus + sonnet + haiku
oh model agent set planner "claude-opus-4-7,claude-sonnet-4-6,claude-haiku-4-5"
```

### Flow tổng quan

```
request → Layer 1 (HTTP retry 3x) ──ok──→ stream
              │
              └─exhausted─→ Layer 3 (switch model) → Layer 1 (lại) → stream
                                  │
                                  └─chain hết─→ raise last error
```

---

## 8. Provider profiles

Mỗi profile chứa: `base_url`, `default_model`, `allowed_models`,
`credential_slot`, `context_window_tokens`, `auto_compact_threshold_tokens`.

```bash
oh profile list
oh profile use claude-router
oh profile show claude-router
```

`claude-router` được generate động từ Claude config — không cần khai báo
trong `~/.openharness/settings.json`.

---

## 9. Authentication

### Auth resolution chain (cao → thấp)

1. **Scoped credential** — `oh auth login --profile claude-router`
2. **ENV `ANTHROPIC_API_KEY`** — injected từ Claude bridge hoặc user export
3. **`settings.api_key`** — từ `~/.openharness/settings.json`
4. **Generic keyring storage**

### Bridge auto-inject

Khi `apply_claude_bridge()` chạy:

- Đọc `env.ANTHROPIC_AUTH_TOKEN` từ Claude
- Nếu `ANTHROPIC_API_KEY` chưa có → inject (in-memory, không persist)
- Nếu có rồi → giữ nguyên (tôn trọng user override)

### Verify

```bash
oh auth status
# → claude-router: env (ANTHROPIC_API_KEY)  [ready]
```

---

## 10. Auto-compaction cho long sessions

Profile `claude-router` mặc định:

- `context_window_tokens = 200_000`
- `auto_compact_threshold_tokens = 160_000` (~80%)

Khi conversation đạt threshold, engine trigger compact tự động — không
chờ context overflow.

Override per-profile trong `~/.openharness/settings.json`:

```json
{
  "profiles": {
    "claude-router": {
      "context_window_tokens": 200000,
      "auto_compact_threshold_tokens": 140000
    }
  }
}
```

---

## 11. CLI reference

```bash
# Profile
oh profile list
oh profile use <name>
oh profile show <name>

# Model
oh model list
oh model use <name>
oh model current

# Per-agent model
oh model agent list
oh model agent set <agent> <model>[,<fallback1>,<fallback2>]
oh model agent get <agent>
oh model agent delete <agent>

# Auth
oh auth login [--profile <name>]
oh auth status
oh auth logout

# Run
oh run "<prompt>"
oh run --agent <type> "<prompt>"
oh run --agent-model planner=claude-x "<prompt>"  # runtime override

# Provider
oh provider list

# Web UI (xem section 12b)
oh webui [--host 127.0.0.1] [--port 8765] [--token <fixed>] [--cwd <path>] \
         [--model <alias>] [--api-format anthropic|openai|copilot] \
         [--permission-mode <mode>] [--debug]
```

---

## 12. Cấu hình `~/.claude/settings.json`

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:20128/v1",
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "API_TIMEOUT_MS": "60000"
  },
  "model": "claude-architect-backup",
  "models": {
    "claude-architect": {
      "model": "claude-architect",
      "description": "Primary architect"
    },
    "claude-architect-backup": {
      "model": "claude-architect-backup",
      "description": "Backup architect"
    },
    "claude-review": {
      "model": "claude-review",
      "description": "Reviewer"
    }
  },
  "agent_models": {
    "planner": ["claude-architect", "claude-architect-backup"],
    "code-reviewer": "claude-review",
    "worker": ["claude-haiku", "claude-architect-backup"]
  }
}
```

### Field semantics

| Field                        | Type                 | Mục đích                                |
| ---------------------------- | -------------------- | ------------------------------------------ |
| `env.ANTHROPIC_BASE_URL`   | string               | Proxy router URL                           |
| `env.ANTHROPIC_AUTH_TOKEN` | string               | Token → inject vào `ANTHROPIC_API_KEY` |
| `env.API_TIMEOUT_MS`       | string (int)         | HTTP timeout                               |
| `model`                    | string               | Active model                               |
| `models`                   | dict                 | Catalog allowed models                     |
| `agent_models`             | dict[str, str\|list] | Per-agent override                         |

---

## 12b. Web UI

Web UI là một SPA (React 19 + Vite + Tailwind v4 + zustand) chạy qua FastAPI
server, dùng chung `ReactBackendHost` với CLI/TUI. Mục đích: chat với agent từ
**điện thoại / tablet / máy khác** mà không cần expose terminal. Khi bạn đang
ngồi ở máy, vẫn dùng `oh run` / TUI như thường — Web UI chỉ thêm một remote
surface, không thay thế.

### Khởi động nhanh

```bash
# Build frontend (one-time, hoặc sau khi pull update)
cd frontend/webui && npm install && npm run build

# Start server (auto-generate token, bind 127.0.0.1:8765)
oh webui
# 🌐 OpenHarness Web UI ready at:
#    http://127.0.0.1:8765/?token=<token>
```

Mở URL trên trong browser. Token được capture từ `?token=…` rồi lưu vào
`localStorage` (`oh_token`), nên các lần refresh sau không cần query string.

### Các flag chính (`oh webui --help`)

| Flag                | Default        | Mục đích                                     |
| ------------------- | -------------- | -------------------------------------------- |
| `--host`            | `127.0.0.1`    | Bind address. Đặt `0.0.0.0` để expose ra LAN |
| `--port`            | `8765`         | HTTP port                                    |
| `--token`           | random 32-byte | Bearer token. Pass cố định để URL stable     |
| `--cwd`             | cwd hiện tại   | Working directory cho mọi session            |
| `--model`, `-m`     | từ profile     | Default model alias / id                     |
| `--api-format`      | auto           | `anthropic` \| `openai` \| `copilot`         |
| `--permission-mode` | từ settings    | Override permission mode (vd. `acceptEdits`) |
| `--debug`, `-d`     | `false`        | Verbose logging                              |

### Truy cập từ mobile / từ xa

- **LAN (cùng Wi-Fi):** `oh webui --host 0.0.0.0 --port 8765`, lấy IP máy
  bằng `ipconfig getifaddr en0`, mở `http://<ip>:8765/?token=<token>` trên
  điện thoại. Plain HTTP — chỉ dùng trong mạng tin cậy.
- **Cloudflare Tunnel** (HTTPS miễn phí, không port-forward): giữ
  `--host 127.0.0.1`, chạy `cloudflared tunnel --url http://localhost:8765`
  ở terminal khác. Xem [`docs/WEBUI.md`](docs/WEBUI.md) để biết chi tiết.
- **Tailscale / Tailscale Funnel** (zero-config VPN, hoặc public HTTPS):
  hướng dẫn đầy đủ trong [`docs/WEBUI.md`](docs/WEBUI.md).
- **ngrok**: `ngrok http 8765` rồi append `?token=<token>` vào URL ngrok.

### Bảo mật — đọc trước khi expose

- **Token là cách auth duy nhất.** Ai có URL + token là có quyền tương đương
  `oh` chạy trên máy bạn (đọc file, run shell, dùng provider account).
  Đối xử như SSH key / password.
- **Không bind `0.0.0.0` trên mạng public thuần** (Wi-Fi quán cà phê, hội
  nghị, hotel). Dùng tunnel có HTTPS và giữ `--host 127.0.0.1`.
- **Ưu tiên tunnel HTTPS** (Cloudflare / Tailscale Funnel). Plain HTTP qua
  Internet sẽ leak token trong transit.
- **Token regenerate mỗi lần restart.** Nếu muốn URL ổn định để bookmark:
  `oh webui --token "$(openssl rand -hex 32)"` rồi cất vào password manager.
- **Ctrl+C khi không dùng.** Bring lại chỉ tốn 1 giây.

### Kiến trúc tóm tắt

```
┌──────────┐   /api/* + /api/ws/{id}?token=…   ┌──────────────────────┐
│ Browser  │ ────────────────────────────────▶ │  FastAPI server      │
│ React SPA│                                   │  (webui/server/)     │
└──────────┘ ◀──────────────────────────────── └──────────┬───────────┘
                  WebSocket events                        │
                                                          ▼
                                              ┌──────────────────────┐
                                              │ WebSocketBackendHost │
                                              │ (extends             │
                                              │  ReactBackendHost)   │
                                              └──────────┬───────────┘
                                                         ▼
                                              ┌──────────────────────┐
                                              │     QueryEngine      │
                                              │  tools / hooks /     │
                                              │  permissions / MCP   │
                                              └──────────────────────┘
```

REST endpoints chỉ dùng để bootstrap (`/api/health`, `/api/meta`,
`/api/sessions`, `/api/tasks`, `/api/cron/jobs`); mọi event stream của
session đi qua một WebSocket `/api/ws/{session_id}`.

### Dev mode (Vite HMR)

```bash
# Terminal 1: backend
oh webui --port 8765

# Terminal 2: frontend với HMR (Vite proxy /api → 8765)
cd frontend/webui && npm run dev
# → http://localhost:5173/?token=<token>
```

Vite proxy cấu hình trong `frontend/webui/vite.config.ts`. Mở URL kèm
`?token=…` đúng 1 lần để seed `localStorage`, sau đó reload thoải mái.

### Liên quan

- [`docs/WEBUI.md`](docs/WEBUI.md) — hướng dẫn đầy đủ về remote access
  (Cloudflare Tunnel, Tailscale, ngrok), mobile UX, security.
- [`frontend/webui/README.md`](frontend/webui/README.md) — kiến trúc &
  build/dev workflow của SPA.

---

## 13. Phát triển & test

```bash
# Cài dev deps
.venv/bin/pip install pytest pytest-asyncio

# Run tests
pytest

# Run claude_bridge tests
pytest tests/test_config/test_claude_bridge.py -v

# Run with coverage
pytest --cov=src --cov-report=term-missing
```

### Test isolation

`tests/test_config/test_claude_bridge.py` dùng `tmp_path` + `monkeypatch`
để patch `claude_bridge.CLAUDE_SETTINGS_PATH` — không đụng file thật của
user.

---

## 13b. Sử dụng harness — workflow phát triển software

### CLI thật sự có gì

`oh` là **interactive AI coding assistant** (giống Claude Code CLI). Không có
`oh run` — dùng:

| Mode | Command | Mục đích |
|------|---------|----------|
| Interactive | `oh` | Mở session UI, chat liên tục |
| Non-interactive | `oh -p "<prompt>"` | One-shot, output ra stdout |
| Dry-run | `oh -p "<prompt>" --dry-run` | Preview config, skills, tools — không gọi model |
| JSON output | `oh -p "..." --output-format json` | Parse được, dùng trong script |
| Stream JSON | `oh -p "..." --output-format stream-json` | Streaming events |

### Subcommands hữu ích

```bash
oh setup            # Wizard: chọn workflow → auth → set model
oh model list       # Xem catalog model
oh model use <m>    # Đổi active
oh model agent ...  # Per-agent map (xem section 6)
oh mcp list         # MCP servers đã cấu hình
oh mcp add <name>   # Add MCP server
oh profile list     # Provider profiles
```

### Built-in tools (37)

Harness pre-load các tool sau cho agent (xem `src/openharness/tools/`):

- **File ops:** `file_read_tool`, `file_write_tool`, `file_edit_tool`, `glob_tool`, `grep_tool`
- **Shell:** `bash_tool`
- **Web:** `web_fetch_tool`, `web_search_tool`
- **Spawn:** `agent_tool` (delegate sub-agent), `team_create_tool`, `send_message_tool`
- **Tasks:** `task_create_tool`, `task_list_tool`, `task_update_tool`, `task_output_tool`, `task_stop_tool`
- **Plan mode:** `enter_plan_mode_tool`, `exit_plan_mode_tool`
- **Worktree:** `enter_worktree_tool`, `exit_worktree_tool`
- **Schedule:** `cron_create_tool`, `cron_list_tool`, `cron_delete_tool`, `cron_toggle_tool`
- **Skills/MCP:** `skill_tool`, `mcp_tool`, `mcp_auth_tool`, `lsp_tool`
- **Misc:** `todo_write_tool`, `brief_tool`, `config_tool`, `tool_search_tool`

### Skills & slash commands

Dry-run cho thấy: 7 skills + 61 slash commands được load tự động từ
`~/.claude/` (chia sẻ với Claude Code). Không phải config lại.

### Workflow #1 — Bug fix nhanh

```bash
cd ~/projects/my-app

# One-shot fix
oh -p "Fix the null pointer in src/auth.ts line 42" \
   --output-format text

# Hoặc interactive (review từng step)
oh
> Fix the null pointer in src/auth.ts line 42
```

Set agent model phù hợp:
```bash
oh model agent set worker "claude-haiku,claude-architect-backup"
```

### Workflow #2 — Feature mới (TDD)

```bash
oh
> Use planner agent to design user-profile API endpoint
> Then use tdd-guide to write failing tests first
> Implement, verify coverage ≥80%
> Use code-reviewer before commit
```

Map từng vai:
```bash
oh model agent set planner       "claude-opus-4-7,claude-architect"
oh model agent set tdd-guide     "claude-sonnet-4-6"
oh model agent set code-reviewer "claude-review,claude-sonnet-4-6"
oh model agent set worker        "claude-haiku,claude-architect-backup"
```

### Workflow #3 — Refactor lớn (Plan mode + worktree)

```bash
oh
> Enter plan mode
> Plan the migration from REST to GraphQL for /api/users
> [review plan, exit plan mode]
> Enter worktree feature/graphql-migration
> Implement phase 1 of the plan
> Run tests
> Exit worktree (keep)
```

Plan mode an toàn (không edit), worktree cô lập (không đụng main branch).

### Workflow #4 — Multi-agent parallel

```bash
oh
> Spawn 3 agents in parallel:
>   1. security-reviewer — audit auth module
>   2. performance-optimizer — profile /search endpoint
>   3. code-explorer — map dependencies of payments/
> Aggregate findings, prioritize CRITICAL issues
```

`agent_tool` dùng subprocess backend → mỗi agent có task_id riêng,
pollable qua `task_list_tool`.

### Workflow #5 — Non-interactive script

```bash
#!/usr/bin/env bash
# review-pr.sh — chạy review tự động trong CI
set -euo pipefail

PR_DIFF=$(git diff origin/main...HEAD)

oh -p "Review this PR diff for security issues, return JSON with severity levels:
$PR_DIFF" \
  --output-format json \
  > review.json

jq '.issues[] | select(.severity == "CRITICAL")' review.json
```

### Workflow #6 — MCP integration

```bash
# Add Context7 docs server
oh mcp add context7 --type stdio --command "npx -y @upstash/context7-mcp"

# Add GitHub MCP
oh mcp add github --type stdio --env GITHUB_TOKEN=$GH_TOKEN \
  --command "npx -y @modelcontextprotocol/server-github"

oh mcp list

# Trong session
oh
> Use context7 to fetch latest React docs
> Use github MCP to search issues labeled "bug"
```

### Workflow #7 — Cron / scheduled task

```bash
oh
> Create a cron task: every weekday at 9am, run smoke tests against staging,
> post failures to #alerts via send_message_tool
```

`cron_create_tool` persist vào `.claude/scheduled_tasks.json` nếu chọn durable.

### Workflow #8 — Coding với cost-aware routing

```bash
# Worker = Haiku (cheap, frequent)
oh model agent set worker "claude-haiku-4-5"

# Critical decisions = Opus (deep reason)
oh model agent set planner   "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set architect "claude-opus-4-7,claude-sonnet-4-6"

# Reviewers = Sonnet (balanced)
oh model agent set code-reviewer     "claude-sonnet-4-6"
oh model agent set security-reviewer "claude-opus-4-7,claude-sonnet-4-6"
```

Fallback chain đảm bảo nếu Opus rate-limited / disallowed → tự rớt về Sonnet.

### Workflow #9 — Debug khi agent fail

```bash
# Dry-run xem config trước
oh -p "<your prompt>" --dry-run

# Check resolved model
oh model current
oh model agent get planner

# Check auth
oh auth status

# Verbose log
oh --debug -p "..."
```

---

## 13c. Best practices

### Do
- Dùng `oh -p "..." --dry-run` trước khi chạy prompt phức tạp
- Set fallback chain cho mọi agent quan trọng
- Worker agent = Haiku (3× rẻ hơn Sonnet, đủ cho task lặp)
- Critical agent (planner, architect) = Opus với fallback Sonnet
- Plan mode trước khi refactor lớn
- Worktree cho feature branch độc lập

### Don't
- Đừng hardcode model name trong code → dùng `resolve_agent_model()`
- Đừng skip `oh model agent` setup rồi than agent dùng sai model
- Đừng commit `~/.claude/settings.json` (chứa auth token)
- Đừng chạy `oh` trên dir chứa secrets không gitignore
- Đừng spam parallel agents nếu không cần — mỗi subprocess tốn RAM

### Gợi ý mapping cho team Python

```bash
oh model agent set planner          "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set architect        "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set tdd-guide        "claude-sonnet-4-6"
oh model agent set python-reviewer  "claude-sonnet-4-6,claude-haiku-4-5"
oh model agent set code-reviewer    "claude-sonnet-4-6"
oh model agent set security-reviewer "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set worker           "claude-haiku-4-5,claude-architect-backup"
oh model agent set Explore          "claude-haiku-4-5"
```

---

## 14. Troubleshooting

### "No API key configured"

- Check `cat ~/.claude/settings.json | jq .env.ANTHROPIC_AUTH_TOKEN` có giá trị không
- Verify bridge đang active: `oh profile current` → `claude-router`
- Manual: `export ANTHROPIC_API_KEY=$(jq -r .env.ANTHROPIC_AUTH_TOKEN ~/.claude/settings.json)`

### "Unknown model 'X'"

- Model phải có trong `~/.claude/settings.json::models`
- `oh model list` để xem catalog hiện tại

### zsh syntax error trong bash shell

- Default shell là zsh nhưng đang chạy bash → `~/.zshrc` syntax không tương thích
- Fix: `exec zsh`

### Bridge không pick up changes

- Kill các process OpenHarness đang chạy → restart
- Bridge đọc 1 lần khi `load_settings()` — không hot-reload

### Claude Code & OpenHarness ghi cùng lúc

- Cả 2 dùng `exclusive_file_lock` + `atomic_write_text` → an toàn
- Lock file: `~/.claude/settings.json.lock` (auto cleanup)

### Web UI hiện trang trắng / `Frontend bundle not found`

- Frontend chưa build → server không tìm thấy `frontend/webui/dist/`.
- Fix: `cd frontend/webui && npm install && npm run build`, rồi restart
  `oh webui`. Trong wheel đã đóng gói thì bundle nằm sẵn ở
  `openharness/_webui_frontend/` — chỉ cần build khi chạy từ repo checkout.

### Web UI: mất token / phải copy URL mỗi lần restart

- Default `--token` random theo mỗi lần start → URL đổi liên tục.
- Fix: pass token cố định và cất vào password manager:
  `oh webui --token "$(openssl rand -hex 32)"`. Sau đó bookmark URL không
  kèm `?token=` (token đã ở `localStorage`).

### Web UI không truy cập được từ điện thoại trên cùng Wi-Fi

- Mặc định bind `127.0.0.1` → chỉ máy local connect được.
- Fix: chạy `oh webui --host 0.0.0.0 --port 8765`, kiểm tra firewall macOS
  (System Settings → Network → Firewall) cho phép Python listen ở port đó.
- Lấy IP LAN bằng `ipconfig getifaddr en0` (Wi-Fi) / `en1` (Ethernet).

---

## 15. FAQ

**Q: Tại sao không lưu auth token trong keyring?**
A: Tránh 2 sources of truth. Bridge inject in-memory mỗi session — restart
tự re-read từ Claude config. Đỡ phải sync 2 chỗ.

**Q: Single chain vs multi chain trong JSON?**
A: 1 model → string (dễ đọc). Multi → list. Read back đều normalize về list.

**Q: Override CLI có persist không?**
A: Không. `--agent-model X=Y` chỉ áp cho session đó. Persist phải qua
`oh model agent set`.

**Q: Có hot-reload Claude config không?**
A: Chưa. Phải restart OpenHarness process sau khi sửa `~/.claude/settings.json`.

**Q: Model nào nên dùng cho từng agent?**
A: Gợi ý:

- `planner` → opus/architect (deep reasoning)
- `code-reviewer` → sonnet/review (balanced)
- `worker` → haiku (cost-efficient, frequent calls)
- `tdd-guide` → sonnet
- `security-reviewer` → opus

**Q: Test fallback hoạt động không?**
A: `pytest tests/test_config/test_claude_bridge.py::TestResolveAgentModel -v`
covers override chain + agent_map chain + filter by allowed_models.

---

## Các file quan trọng

| File                                        | Vai trò                          |
| ------------------------------------------- | --------------------------------- |
| `src/openharness/config/claude_bridge.py` | Bridge core, read/write/resolve   |
| `src/openharness/config/settings.py`      | `Settings`, `ProviderProfile` |
| `src/openharness/tools/agent_tool.py`     | Spawn agent + chain filtering     |
| `src/openharness/cli.py`                  | CLI commands `oh model agent`   |
| `src/openharness/webui/`                  | Module Web UI server (FastAPI + WebSocket) |
| `frontend/webui/`                         | React SPA (build → `dist/` được bundle vào wheel) |
| `docs/WEBUI.md`                           | Hướng dẫn chi tiết Web UI + remote access |
| `tests/test_config/test_claude_bridge.py` | 24 tests, 7 classes               |

---

**License:** kế thừa từ OpenHarness upstream.
**Maintainer:** local fork — không push lên remote công khai.
