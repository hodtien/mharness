# my-harness Changelog

> Generated: 2026-05-12
> Sources: `GUIDE.md`, `AUTOPILOT.md`, `TASKS.md`
>
> Tài liệu này ghi lại các thay đổi chính của fork `my-harness` dựa trên ba tài liệu nguồn hiện tại. Trạng thái `DONE`/backlog phản ánh nội dung đã được ghi trong các tài liệu đó, không thay thế git history hay PR history.

---

## Tổng quan hiện trạng

`my-harness` là fork tùy biến của OpenHarness tập trung vào ba trục chính:

- Dùng chung cấu hình Claude Code qua bridge hai chiều với `~/.claude/settings.json`.
- Bổ sung routing model theo agent, fallback chain, retry, và auto-compaction cho long sessions.
- Mở rộng Web UI và Autopilot thành bề mặt vận hành repo-wide: chat, history, settings, projects, jobs, pipeline/autopilot board, review, CI, merge, cron.

Theo tài liệu hiện tại:

- WebUI upgrade P0–P11 được mô tả là đã có trong codebase hiện tại.
- Phase 13 đã DONE: task resilience, preflight, pending/resume, auto-merge và bug fixes liên quan.
- Phase 14 đã DONE: settings review/polish và integration coverage.
- Phase 12 và Phase 15 đang được mô tả như backlog/next scope trong `TASKS.md`.

---

## Core runtime và Claude bridge

### Claude Code bridge

- `~/.claude/settings.json` trở thành single source of truth cho model, catalog model, agent model mapping, và env proxy/auth.
- Thêm bridge đọc cấu hình Claude sang OpenHarness:
  - `env.ANTHROPIC_BASE_URL` -> provider profile base URL.
  - `env.ANTHROPIC_AUTH_TOKEN` -> inject in-memory vào `ANTHROPIC_API_KEY` nếu env này chưa tồn tại.
  - `env.API_TIMEOUT_MS` -> timeout runtime.
  - `model` -> active model.
  - `models{}` -> allowed models cho profile `claude-router`.
  - `agent_models{}` -> per-agent fallback chain.
- Thêm bridge ghi ngược OpenHarness sang Claude settings:
  - `write_claude_model(name)` đổi active model.
  - `write_agent_model(agent, chain)` ghi per-agent mapping.
  - `delete_agent_model(agent)` xóa per-agent mapping.
- Ghi settings dùng atomic write và exclusive file lock để tránh file half-written khi Claude Code và OpenHarness chạy song song.

### Provider profile `claude-router`

- `claude-router` được generate động từ Claude config, không cần khai báo thủ công trong `~/.openharness/settings.json`.
- Profile chứa base URL, default model, allowed models, credential slot, context window, và auto-compact threshold.
- Auth bridge tôn trọng user override: nếu `ANTHROPIC_API_KEY` đã tồn tại thì không ghi đè.

### Per-agent model mapping

- Thêm CLI để map từng agent sang một model hoặc fallback chain:
  - `oh model agent set <agent> <model>[,<fallback>]`
  - `oh model agent list`
  - `oh model agent get <agent>`
  - `oh model agent delete|unset <agent>`
- Chuỗi một model được lưu dạng string cho dễ đọc; nhiều model được lưu dạng list.
- Runtime normalize tất cả mapping về `list[str]`.
- Precedence model resolution:
  1. CLI `agent_override`.
  2. `agent_models[agent]` trong Claude settings.
  3. `profile.last_model` hoặc `profile.default_model`.
  4. Top-level Claude `model`.

### Fallback và retry

- Thêm retry HTTP-level trong `AnthropicApiClient`:
  - retry 3 lần.
  - exponential backoff với jitter.
  - retry các status `429`, `500`, `502`, `503`, `529`.
  - tôn trọng `retry-after`.
- Thêm spawn-time chain filtering cho sub-agent:
  - resolve full chain.
  - filter theo `profile.allowed_models`.
  - promote model hợp lệ đầu tiên làm primary.
- Thêm runtime fallback client:
  - sau khi HTTP retry exhaust, tự chuyển sang model tiếp theo trong chain.
  - yield `ModelSwitchEvent` để UI có thể hiển thị model switching.
  - `AuthenticationFailure` propagate ngay, không fallback model.

### Auto-compaction

- Profile `claude-router` mặc định dùng context window `200_000` tokens.
- Auto-compact threshold mặc định `160_000` tokens, khoảng 80% context window.
- Cho phép override `context_window_tokens` và `auto_compact_threshold_tokens` theo profile trong `~/.openharness/settings.json`.

---

## CLI, tools, skills và workflow phát triển

### CLI entrypoints và commands

- Entry points `oh`, `openharness`, `openh` cùng trỏ về `openharness.cli:app`.
- CLI hỗ trợ các nhóm lệnh chính:
  - provider management.
  - model management.
  - per-agent model mapping.
  - auth.
  - non-interactive run.
  - JSON và stream-json output.
  - MCP server management.
  - plugin management.
  - cron.
  - autopilot.
  - Web UI.
  - setup wizard.

### Dry-run và output modes

- `oh -p "..." --dry-run` preview cấu hình, skills, tools, model/auth state mà không gọi model.
- `--output-format json` hỗ trợ script/CI parse output.
- `--output-format stream-json` stream runtime events.

### Built-in tools và slash commands

- Harness preload nhiều nhóm tool: file ops, shell, web, agent spawn, tasks, plan mode, worktree, schedule, MCP, skills/config, LSP, ask-user, sleep, remote trigger.
- Slash commands được load tự động, bao gồm các lệnh như `/help`, `/status`, `/model`, `/provider`, `/permissions`, `/plan`, `/diff`, `/commit`, `/autopilot`, `/tasks`, `/agents`, `/skills`, `/mcp`, `/doctor`, `/hooks`.

### Workflow được tài liệu hóa

- Bug fix nhanh bằng one-shot hoặc interactive session.
- Feature mới theo TDD: planner -> tdd-guide -> implement -> code-reviewer.
- Refactor lớn bằng plan mode và worktree.
- Multi-agent parallel cho security/performance/dependency exploration.
- Non-interactive script/CI review.
- MCP integration với Context7/GitHub MCP.
- Cron/scheduled task.
- Cost-aware model routing theo agent role.
- Debug workflow khi agent fail: dry-run, model current, agent mapping, auth status, debug logs.

---

## Web UI platform

### Web UI server và remote access

- Web UI là React SPA chạy qua FastAPI server, dùng chung runtime với CLI/TUI.
- Hỗ trợ dùng từ phone, tablet hoặc máy khác mà không expose terminal.
- Token auth được seed qua `?token=...` và lưu trong `localStorage`.
- Hỗ trợ local, LAN, Cloudflare Tunnel, Tailscale/Tailscale Funnel, và ngrok.
- Tài liệu nhấn mạnh token là auth duy nhất và phải được xử lý như SSH key/password.

### Web UI routes/API surface

Web UI REST/WebSocket được tài liệu hóa theo nhóm:

- Sessions/core: health, meta, sessions, modes, WebSocket stream.
- History: list/load/delete session snapshots.
- Providers/models: provider list/activate/credentials/verify, model list/add/delete.
- Agents/tasks: agent list/detail/update, task list/detail/output/stop/retry.
- Cron: cron jobs.
- Projects: project list/create/update/delete/activate.
- Pipeline/autopilot: cards, actions, model override, stream, checkpoint, resume, journal, policy, run-next, review, run/verification reports.
- Review: saved review markdown and rerun endpoint.

---

## Autopilot runtime

### Two autopilot modes

- `full_auto` mode: một session, một prompt, agent tự chạy tool/edit/spawn không hỏi confirmation.
- `oh autopilot`: repo-wide queue, scan -> run -> PR -> CI -> merge liên tục, có thể chạy qua cron.

### `full_auto` updates

- `--permission-mode full_auto` và `--dangerously-skip-permissions` được mô tả như chế độ tự động hóa toàn bộ.
- Tài liệu cảnh báo chỉ dùng trong sandbox/worktree/VM/throwaway branch và nên set `--max-turns` để tránh loop vô hạn.

### Repo-wide queue lifecycle

Autopilot lifecycle được chuẩn hóa với các trạng thái:

- `queued`
- `accepted`
- `preparing`
- `running`
- `verifying`
- `waiting_ci`
- `code_review`
- `repairing`
- `completed`
- `merged`
- `failed`
- `rejected`
- `killed`
- `superseded`

### Source kinds

Autopilot hỗ trợ enqueue từ:

- `manual_idea`
- `ohmo_request`
- `github_issue`
- `github_pr`
- `claude_code_candidate`

### Autopilot commands

CLI và slash command surface được mở rộng cho:

- status/list/show.
- add/accept/start/complete/fail/reject.
- context/journal.
- scan.
- run-next.
- tick.
- install-cron.
- export-dashboard.

### End-to-end tick flow

`oh autopilot tick` được mô tả là:

1. Scan sources và enqueue cards theo score.
2. Chọn card cao điểm nhất khi còn capacity.
3. Checkout worktree isolated branch.
4. Agent implement code/test.
5. Run local verification.
6. Push/upsert PR.
7. Rebase PR branch theo base trước khi push.
8. Wait CI.
9. Run code-reviewer diff vs `origin/main`.
10. Auto-merge khi CI pass và review không block.
11. Pull/rebase post-merge.
12. Ghi journal transitions.

### Capacity và parallel execution

- `max_parallel_runs` trong policy giới hạn số card active đồng thời.
- `run_next` báo lỗi khi hết capacity.
- Cron/tick chỉ chạy khi còn slot.
- Task list P9 định nghĩa roadmap parallel execution: file locks, atomic claim, main checkout lock, per-card model, model override API, capacity gate, worktree cleanup, rebase strategy, integration tests.

### Auto-merge và review policy

- Autopilot auto-merge khi CI pass, remote code review không có CRITICAL issue, và `auto_merge.mode` cho phép.
- Policy hỗ trợ `always`, `label_gated`, `disabled`.
- Remote code review có thể block theo severity.
- Autopilot-managed PR với CI pass được xử lý để không kẹt trong repair/rerun.

### Branch sync và post-merge sync

- Trước push PR branch, autopilot fetch base và remote head branch.
- Rebase local head lên `origin/<base_branch>` theo strategy `rebase`.
- Conflict chuyển card sang repairing/human gate.
- Push bị reject có retry sync.
- `allow_force_push_pr_branch` chỉ cho phép `--force-with-lease`, không plain force.
- Sau merge, autopilot pull base branch và rebase in-flight worktrees.

### Persistence

Autopilot state được lưu trong:

- `.openharness/autopilot/registry.json`
- `.openharness/autopilot/journal.jsonl`
- `.openharness/autopilot/context.md`
- `.openharness/autopilot/autopilot_policy.yaml`
- `.openharness/autopilot/verification_policy.yaml`
- `.openharness/autopilot/runs/`

---

## WebUI upgrade task history

### P0 — Foundation

- Tách backend WebUI thành FastAPI routers.
- Thêm React Router vào WebUI frontend.
- Tạo sidebar navigation cho Chat, History, Pipeline, Tasks, Settings.

### P1 — History & Resume

- Thêm API list/load/delete session history.
- Thêm resume session qua `POST /api/sessions` với `resume_id`.
- Thêm HistoryPanel và `/history` route.
- Thêm header dropdown sessions.
- Thêm route tests cho history.

### P2 — Modes Toggle

- Thêm `/api/modes` GET/PATCH.
- Thêm Settings/Modes page cho permission mode, effort, passes, fast mode, output style, theme.
- Thêm quick-switch permission mode trong Header.
- Thêm visual indicator cho `full_auto`.
- Thêm tests cho modes routes.

### P3 — Provider Settings

- Thêm provider profiles API.
- Thêm activate provider endpoint.
- Thêm credentials endpoint.
- Thêm provider verify endpoint.
- Thêm Settings/Provider page.
- Thêm tests provider routes.

### P4 — Models & Agents

- Thêm models API group theo provider.
- Thêm add/delete custom model.
- Thêm Settings/Models page.
- Thêm agents API list/update.
- Thêm Settings/Agents page.
- Thêm tests cho models và agents routes.

### P5 — Pipeline & Tasks

- Thêm pipeline cards API.
- Thêm enqueue manual idea.
- Thêm action endpoint cho cards.
- Thêm journal endpoint.
- Thêm policy GET/PATCH.
- Thêm task detail/output/stop endpoints.
- Thêm Pipeline kanban page.
- Thêm New idea form và policy editor.
- Mở rộng Tasks page.
- Thêm pipeline và task detail tests.

### P6 — Auto Code-Review

- Tạo code-reviewer agent definition.
- Thêm review route GET/rerun.
- Thêm review tab trong pipeline card detail.
- Thêm review badge trong tasks list.
- Narrowed/skip một số scope trùng với remote code-review policy.
- Thêm review route tests.

### P7 — WebUI Integration Gap Fixes

- Thêm history detail drawer/modal.
- Thêm `vim_enabled` toggle trong Settings/Modes.
- Tasks drawer fetch full detail bằng API.
- Pipeline auto-refresh khi không có WebSocket live updates.
- Edit/update custom model UI.
- Agent detail modal.
- Pipeline card journal inline.
- Gap coverage tests cho history, modes, tasks.

### P8 — Autopilot UI Polish

- Rebuild Autopilot Kanban board theo lifecycle thật.
- Đổi tên Pipeline thành Autopilot.
- Làm rõ Tasks tab thành Jobs.
- Fix Activity drawer scroll/viewport height.
- Activity item truncate + expand.
- Activity filter theo event type.
- Current blocker alert trong card detail.

### P9 — Parallel Autopilot Execution

- Thiết kế interprocess lock cho registry/journal.
- Atomic card claim bằng `pick_and_claim_card()`.
- Lock shared main checkout cho pull/install.
- Per-card model field.
- API card model override.
- Frontend model dropdown trong card detail.
- Configurable `max_parallel_runs`.
- Capacity-based concurrency gate.
- Worktree cleanup finally block.
- Rebase strategy cho in-flight worktrees.
- Integration tests cho two-card parallel execution.

### P10 — WebUI UX/UI Polish & Bug Fixes

- Sidebar/status visual hierarchy.
- Collapsible Settings section.
- Docs/Help link trong sidebar.
- Responsive header breadcrumb truncation.
- Kanban column count badge styling.
- Better empty states cho queue/in-progress columns.
- Chronological grouped autopilot log viewer.
- History skeleton loader, grouping, search/filter, copy action.
- Background jobs status styling và inline log viewer.
- Modes passes input polish.
- YAML syntax highlighting cho autopilot policy editor.
- Chat connected/disconnected messaging.

### Cross-cutting

- Cập nhật WebUI docs và tạo WebUI settings/pipeline docs.
- Chuẩn hóa loading, error, empty, toast states trên các pages.

### P11 — Multi-Project Support

- Thêm project model và registry.
- Thêm Project CRUD API.
- Thêm project switching logic trong WebUI state.
- Audit session/chat isolation theo project.
- Thêm ProjectSelector và active project state.
- Thêm project API client/types.
- Thêm Projects management page.
- Switch project không reload và reconnect đúng cách.
- Thêm CLI project commands.
- Thêm multi-project integration coverage.
- Thêm multi-project user guide.
- Refresh docs/test snapshot sau multi-project.

### P12 — Autopilot Cron Scheduling Configuration

- Backlog cấu hình cron schedule model/persistence.
- Backlog GET/PATCH cron scheduling API.
- Backlog cron preview và next-run computation.
- Backlog install-cron endpoint/command integration.
- Backlog cron scheduling settings UI.
- Backlog preset schedule shortcuts.
- Backlog install/apply cron feedback.
- Backlog cron scheduling integration tests.

### P13 — Autopilot Task Resilience

Status: DONE.

- Thêm preflight checks trước khi chạy card.
- Thêm trạng thái `pending` và retry metadata.
- Thêm preflight API endpoint.
- Thêm pending retry scheduler và resume logic.
- Thêm auto-merge cho autopilot-managed PR khi CI pass.
- Thêm Pipeline API support cho pending status.
- Thêm frontend Pending status trong board.
- Thêm task resilience integration tests.
- Hoàn thiện public preflight contract cho WebUI/CLI.

Bug fixes sau P13:

- `local_verification_failed` có repeated-failure guard.
- CRITICAL/HIGH feedback từ `agent:code-reviewer` được inject vào repair prompt.
- Clamp max attempts để tránh loop vô hạn.
- Autopilot-managed PR có CI pass được merge thay vì kẹt repair/rerun.
- `/api/pipeline/preflight` delegate qua `RepoAutopilotStore.run_preflight(...)` để honor `use_worktree`, model resolution, và run path thật.
- Reset/rerun stale P13.8 card `ap-e573e3ef`; PR #127 đã merge.

### P14 — Settings Review & Polish

Status: DONE.

- P14.1: Modes page thêm notification preferences và auto-compact settings.
- P14.2: Provider page thêm connection status và Verify all configured providers.
- P14.3: Models page thêm capabilities info và search/filter.
- P14.4: Agents page thêm system prompt preview, clone/copy agent flow, validation/test action, source file path và changed status.
- P14.5: Cross-cutting settings UX: dirty state, unsaved warning, inline validation, save/apply success state, keyboard/focus polish.
- P14.6: Integration tests cho settings improvements.

Bug fixes trong P14:

- Agent clone endpoint hardening: safe filename validation, destination containment trong source agent directory, no overwrite, exclusive file creation để tránh race/data loss.

### P15 — UI/UX Upgrade & Semantic Operator Experience

Status: DONE.

- P15.1: Design tokens và shared visual primitives — expand `index.css` thành design-token layer với spacing scale, radius scale, typography scale, semantic status colors, priority colors, shadows, transitions, focus-visible style. Replace hardcoded palette/spacing trong Sidebar.tsx, Header.tsx, PipelinePage.tsx, TasksPage.tsx.
- P15.2: Standardized PageHeader component — tạo `PageHeader.tsx` với title, description, actions slot, metadata row. Apply cho Autopilot, Jobs, Projects, History, Settings pages.
- P15.3: Sidebar noise reduction — refactor Sidebar.tsx thành 3 zones: primary nav, collapsible Settings nav, collapsible System Status. Jobs snippet top 3 + View all.
- P15.4: Top bar runtime summary — upgrade Header.tsx với active project, connection health, running job count, active model/provider, permission mode, primary interrupt action khi busy.
- P15.5: Autopilot board card hierarchy và completed de-emphasis — card padding/line-height thoáng hơn, title hierarchy rõ hơn, semantic badges, sticky column headers, Completed column collapsed mặc định.
- P15.6: Semantic activity feed cho autopilot logs — unified chronological stream, newest-first, tag filters (#agent, #tool, #error), semantic event cards thay raw JSON, inspector panel, raw payload ẩn sau "View raw event".
- P15.7: Collapsible semantic tool execution cards trong chat transcript — default collapsed tool cards với tool name/status/duration/summary, expand on click, auto-collapse theo output size, group consecutive tool calls, extract ToolCard.tsx.
- P15.8: Jobs UX — search input, status/type/review filters, sort control, richer status badges, review state copy rõ ràng, row expansion với prompt summary/duration/model/log preview.
- P15.9: Projects UX safety polish và path ergonomics — active project pinned/visually prioritized, clearer Active badge, truncate path thành ~/relative/path, copy path button + full path tooltip, client-side search, empty state với Add project CTA.
- P15.10: Settings UX contextual microcopy và help states — Modes permission/effort/passes descriptions, Providers clearer status/verify/latency, Models capability/search clarity, Agents prompt preview/clone/test clarity.
- P15.11: Cross-cutting empty/loading/error/toast states — standardize guidance states across Chat, Autopilot, Jobs, Projects, Settings. Reuse EmptyState/ErrorBanner/LoadingSkeleton/ToastContainer.
- P15.12: Accessibility foundation audit và fixes — WCAG AA contrast trên dark surfaces, focus-visible ring nhất quán, aria-label cho icon-only buttons, modal/drawer labels explicit, keyboard navigation logical, Escape closes modals/drawers, status không dựa hoàn toàn vào màu sắc.
- P15.13: Playwright E2E core WebUI flows — coverage cho Sidebar navigation, Header runtime badges, Autopilot board card lifecycle, Autopilot log feed filters, ToolCard collapse/expand, Jobs filter/sort/row-expand, Projects active highlight + path copy + delete safety, Settings microcopy visibility, cross-cutting empty/loading/error states.

Delivered: P15.1 design tokens (#135), P15.2 PageHeader (#136), P15.3 Sidebar (#138), P15.4 Header runtime summary (#137), P15.5 Autopilot board (#139), P15.6 Autopilot logs (#140), P15.7 ToolCard (#141), P15.8 Jobs UX (#142), P15.9 Projects UX (no PR#), P15.10 Settings microcopy (#144), P15.11 Empty/loading/error states (#145), P15.12 Accessibility (#146), P15.13 E2E (#147).

### P16 — Header Runtime Controls & Per-Tab Project Context

Status: DONE (một phần — P16.1, P16.2a, P16.2, P16.3a, P16.3 đã merge).

- P16.1: Header — xóa SessionsDropdown, thay bằng plain nav link dẫn đến `/history`. Loại bỏ toàn bộ dropdown logic, fetch sessions, `RECENT_HISTORY_ENDPOINT`, và state liên quan trong `Header.tsx`.
- P16.2a: Backend — thêm field `model` vào `ModesPatch` và `ModesPayload` trong `routes/modes.py`. Validate model tồn tại, persist vào settings, broadcast `state_snapshot` cho mọi active session. Thêm tests cho `PATCH /api/modes {model: ...}`.
- P16.2: UI — model badge trong Header từ read-only thành clickable. Mở dropdown picker, fetch `GET /api/models`, `PATCH /api/modes({model})` với optimistic update + rollback. Dropdown hiển thị active model với checkmark.
- P16.3a: Backend — tách project context khỏi global server state. `POST /api/sessions` nhận optional `project_id`. `Session`/`WebUIState` lưu `cwd` riêng theo session. Chat/WebSocket lấy project từ session thay vì đọc `active_project_id` global. Tests chứng minh 2 sessions với project khác nhau có `cwd` độc lập.
- P16.3: UI — per-tab project isolation qua URL param `?project=id`. `ProjectSelector` đọc/ghi URL param thay vì gọi `POST /api/projects/{id}/activate`. `api.createSession` truyền `project_id` từ URL. Bỏ `window.location.reload()` sau project switch. Param giữ nguyên khi navigate giữa các pages trong cùng tab.

Delivered: P16.1 (#148, #152), P16.2 (#149), P16.2a (#151, #155), P16.3a (#154), P16.3 (#156).

---

## Testing và quality coverage

- Claude bridge tests cover model resolution, override chain, agent map chain, và allowed model filtering.
- History, modes, providers, models, agents, pipeline, tasks, review routes đều có task-level test coverage trong roadmap.
- P13 bổ sung integration tests cho pending/resume/preflight/retry exhaustion/manual retry-now.
- P14 bổ sung `tests/test_settings_improvements.py` cho:
  - Modes advanced fields.
  - Provider batch verify flow.
  - Model search/filter.
  - Agent prompt preview/clone flow.
  - Dirty-state và unsaved warning behavior.
- P15 bổ sung coverage cho: design tokens smoke pass, PageHeader render tests, Sidebar collapse/a11y, Header runtime state badges, PipelinePage board hierarchy, log transform unit tests, ToolCard collapse/expand, TasksPage filter/sort/badges, ProjectsPage active highlight/search/path copy/delete safety, Settings help text visibility, cross-cutting empty/loading/error states.
- P15.13 bổ sung Playwright E2E suite cho toàn bộ upgraded core flows (Sidebar nav, Header badges, Autopilot board, log feed, Jobs, Projects, Settings).
- P16 bổ sung: `PATCH /api/modes {model}` tests, per-session project isolation tests (2 sessions với project khác nhau có `cwd` độc lập), Header model picker optimistic update + rollback, nav link History tests.

---

## Security và safety notes

- Web UI token là auth duy nhất; ai có URL + token có quyền tương đương process `oh` trên máy user.
- Không nên bind Web UI ra `0.0.0.0` trên mạng public; ưu tiên HTTPS tunnel.
- `full_auto` có thể tự edit/run/spawn và cần sandbox/worktree/VM/throwaway branch.
- Branch sync dùng `--force-with-lease` nếu force push được bật; không dùng plain `--force`.
- Agent clone endpoint đã được harden để tránh path traversal, overwrite và race-related data loss.

---

## File quan trọng

- `src/openharness/config/claude_bridge.py` — Claude bridge read/write/resolve.
- `src/openharness/config/settings.py` — settings và provider profiles.
- `src/openharness/api/client.py` — HTTP retry layer.
- `src/openharness/api/fallback.py` — runtime model fallback.
- `src/openharness/tools/agent_tool.py` — sub-agent spawn và chain filtering.
- `src/openharness/autopilot/service.py` — autopilot core logic.
- `src/openharness/autopilot/types.py` — card/registry/journal models.
- `src/openharness/webui/` — FastAPI WebUI server và routes.
- `frontend/webui/` — React SPA.
- `.openharness/autopilot/` — local autopilot state, policy, journal, runs.
- `GUIDE.md` — comprehensive fork guide.
- `AUTOPILOT.md` — autopilot operation guide.
- `TASKS.md` — WebUI/autopilot phase task list.
