# WebUI Upgrade — Autopilot Task List

> Generated: 2026-04-29
> Cách dùng: copy từng block lệnh `oh autopilot add` chạy trong terminal tại thư mục project root (`/Users/hodtien/harness/my-harness`).

## Mục lục
- [WebUI Upgrade — Autopilot Task List](#webui-upgrade--autopilot-task-list)
  - [Mục lục](#mục-lục)
  - [P0 — Foundation](#p0--foundation)
  - [P1 — F1: History \& Resume](#p1--f1-history--resume)
  - [P2 — F2: Modes Toggle](#p2--f2-modes-toggle)
  - [P3 — F3a: Provider Settings](#p3--f3a-provider-settings)
  - [P4 — F3b/c: Models \& Agents](#p4--f3bc-models--agents)
  - [P5 — F4: Pipeline \& Tasks](#p5--f4-pipeline--tasks)
  - [P6 — F5: Auto Code-Review](#p6--f5-auto-code-review)
  - [P7 — Gap Fixes: WebUI Integration](#p7--gap-fixes-webui-integration)
  - [P8 — Autopilot UI Polish](#p8--autopilot-ui-polish)
  - [P9 — Parallel Autopilot Execution](#p9--parallel-autopilot-execution)
  - [P10 — WebUI UX/UI Polish \& Bug Fixes](#p10--webui-uxui-polish--bug-fixes)
    - [P10.A — Sidebar \& Navigation](#p10a--sidebar--navigation)
    - [P10.B — Autopilot Board](#p10b--autopilot-board)
    - [P10.C — History Page](#p10c--history-page)
    - [P10.D — Jobs Page](#p10d--jobs-page)
    - [P10.E — Settings Pages](#p10e--settings-pages)
    - [P10.F — Chat \& Misc](#p10f--chat--misc)
  - [Cross-cutting](#cross-cutting)
  - [P11 — Multi-Project Support](#p11--multi-project-support)
    - [P11.A — Backend](#p11a--backend)
    - [P11.B — Frontend](#p11b--frontend)
    - [P11.C — CLI, Tests, Docs](#p11c--cli-tests-docs)
  - [P12 — Autopilot Cron Scheduling Configuration](#p12--autopilot-cron-scheduling-configuration)
    - [P12.A — Backend](#p12a--backend)
    - [P12.B — Frontend](#p12b--frontend)
    - [P12.C — CLI \& Tests](#p12c--cli--tests)
  - [P13 — Autopilot Task Resilience (Pre-flight + Pending/Resume)](#p13--autopilot-task-resilience-pre-flight--pendingresume)
    - [P13.A — Status \& Pre-flight](#p13a--status--pre-flight)
    - [P13.B — Core Logic](#p13b--core-logic)
    - [P13.C — API, Frontend \& Tests](#p13c--api-frontend--tests)
  - [P14 — Settings Review \& Polish](#p14--settings-review--polish)

---

## P0 — Foundation

```bash
oh autopilot add idea "[P0.1] Tách backend webui thành routers" --body "Refactor src/openharness/webui/server/app.py: tách các endpoint hiện tại ra thành các FastAPI router riêng biệt trong thư mục routes/: routes/health.py, routes/sessions.py, routes/tasks.py, routes/cron.py. app.py chỉ còn create_app() mount các router. Giữ nguyên logic, chỉ tổ chức lại code. Test: tất cả endpoint hiện có vẫn hoạt động."

oh autopilot add idea "[P0.2] Thêm react-router-dom vào frontend webui" --body "Thêm react-router-dom@^6 vào frontend/webui/package.json. Cấu hình BrowserRouter trong main.tsx. Tạo layout component với Sidebar + Header persistent, Outlet cho nội dung. Route mặc định / redirect tới /chat. Trang /chat chứa Transcript + InputBar hiện tại. Đảm bảo SPA fallback trong backend vẫn hoạt động (mọi path non-api trả index.html)."

oh autopilot add idea "[P0.3] Tạo Navigation trong Sidebar" --body "Cập nhật frontend/webui/src/components/Sidebar.tsx: thêm navigation links dùng react-router NavLink cho các route: Chat (/chat), History (/history), Pipeline (/pipeline), Tasks (/tasks), Settings (/settings). Giữ nguyên các section status/tasks/cron hiện tại phía dưới nav. Active route highlight bằng border-left hoặc bg khác."
```

---

## P1 — F1: History & Resume

```bash
oh autopilot add idea "[P1.1] Backend: GET /api/history — list session snapshots" --body "Tạo src/openharness/webui/server/routes/history.py. Endpoint GET /api/history?limit=20 gọi services/session_storage.list_session_snapshots(cwd, limit) trả về danh sách {session_id, summary, message_count, model, created_at}. Cwd lấy từ app.state.webui_config.cwd. Mount router vào app."

oh autopilot add idea "[P1.2] Backend: GET /api/history/{session_id} — load session detail" --body "Thêm endpoint GET /api/history/{session_id} trong routes/history.py. Gọi services/session_storage.load_session_by_id(cwd, session_id). Trả về full snapshot nhưng truncate tool_result content >500 chars. Return 404 nếu không tìm thấy."

oh autopilot add idea "[P1.3] Backend: DELETE /api/history/{session_id}" --body "Thêm endpoint DELETE /api/history/{session_id} trong routes/history.py. Xoá file session-{id}.json trong project session dir. Nếu latest.json trỏ tới session này thì cũng xoá. Return 204 on success, 404 nếu không tồn tại."

oh autopilot add idea "[P1.4] Backend: POST /api/sessions hỗ trợ resume" --body "Mở rộng POST /api/sessions trong routes/sessions.py: chấp nhận optional JSON body {resume_id: string}. Khi có resume_id: load snapshot qua load_session_by_id(), tạo BackendHostConfig với initial_messages từ snapshot messages. Cần kiểm tra BackendHostConfig có hỗ trợ initial_messages không, nếu chưa thì thêm field này và wire vào engine/query_engine.py để prepend messages."

oh autopilot add idea "[P1.5] Frontend: HistoryPanel component" --body "Tạo frontend/webui/src/components/HistoryPanel.tsx. Fetch GET /api/history on mount. Hiển thị list card: summary (truncate 60 chars), model badge, message count, relative time (vd: 2h ago). Nút Resume và Delete cho mỗi item. Loading skeleton khi fetch. Empty state: 'No previous sessions'."

oh autopilot add idea "[P1.6] Frontend: Route /history và tích hợp resume" --body "Tạo page /history render HistoryPanel. Khi click Resume: gọi POST /api/sessions {resume_id}, nhận session_id mới, navigate tới /chat, reconnect WebSocket với session mới. Hiển thị banner 'Resumed from session <id>' trong Transcript."

oh autopilot add idea "[P1.7] Frontend: Header dropdown Sessions" --body "Thêm dropdown button trong Header.tsx cạnh tên OpenHarness. Click mở mini-list 5 sessions gần nhất (fetch /api/history?limit=5). Click item → resume. Link 'View all' → navigate /history."

oh autopilot add idea "[P1.8] Test: history routes happy path + error path" --body "Tạo tests/webui/test_history_routes.py. Dùng FastAPI TestClient. Test: list empty → []; tạo fake session file → list trả về 1 item; load by id → trả đúng data; load unknown id → 404; delete → file bị xoá. Mock cwd."
```

---

## P2 — F2: Modes Toggle

```bash
oh autopilot add idea "[P2.1] Backend: GET /api/modes — trả về current modes" --body "Tạo src/openharness/webui/server/routes/modes.py. GET /api/modes đọc AppState từ active session host (hoặc từ settings nếu chưa có session): permission_mode, fast_mode, vim_enabled, effort, passes, output_style, theme. Trả JSON object với tất cả các field."

oh autopilot add idea "[P2.2] Backend: PATCH /api/modes — thay đổi modes runtime" --body "Endpoint PATCH /api/modes nhận body Pydantic model ModesPatch(permission_mode?: str, effort?: str, passes?: int, fast_mode?: bool, output_style?: str, theme?: str). Validate giá trị (permission_mode phải trong ['default','plan','full_auto'], effort trong ['low','medium','high'], passes 1-5). Áp dụng vào AppState hiện tại. Persist vào ~/.openharness/settings.json qua save_settings(). Broadcast state_snapshot qua WebSocket."

oh autopilot add idea "[P2.3] Frontend: Settings/Modes page" --body "Tạo page /settings/modes. Fetch GET /api/modes on mount. Hiển thị: (1) Permission Mode — 3 radio buttons: Default, Plan, Full Auto với mô tả ngắn; (2) Effort — 3-button toggle low/medium/high; (3) Passes — number input 1-5; (4) Fast Mode — toggle switch; (5) Output Style — dropdown; (6) Theme — dropdown. Khi thay đổi → PATCH /api/modes ngay (debounce 300ms cho numeric)."

oh autopilot add idea "[P2.4] Frontend: Header quick-switch permission mode" --body "Thêm clickable chip trong Header hiển thị permission_mode hiện tại (DEFAULT=xám, PLAN=xanh, AUTO=đỏ/cam). Click mở popover/dropdown với 3 option. Chọn → PATCH /api/modes {permission_mode: ...}. Cập nhật UI ngay optimistic."

oh autopilot add idea "[P2.5] Frontend: Visual indicator cho full_auto mode" --body "Khi permission_mode=full_auto: Header hiện animated badge 'AUTO' màu cam nhấp nháy nhẹ. Sidebar status row permission hiện đỏ. Toast warning 1 lần khi chuyển sang full_auto: 'All tool calls will be auto-approved'. Khi chuyển về default → toast confirm."

oh autopilot add idea "[P2.6] Test: modes routes" --body "Tạo tests/webui/test_modes_routes.py. Test GET /api/modes trả đúng fields. Test PATCH với giá trị hợp lệ → 200 + giá trị thay đổi. Test PATCH với effort=invalid → 422. Test PATCH permission_mode=full_auto → persist đúng."
```

---

## P3 — F3a: Provider Settings

```bash
oh autopilot add idea "[P3.1] Backend: GET /api/providers — list provider profiles" --body "Tạo src/openharness/webui/server/routes/providers.py. GET /api/providers trả về danh sách provider profiles từ default_provider_profiles() merge với custom profiles trong settings. Mỗi item: {id, label, provider, api_format, default_model, base_url, has_credentials: bool, is_active: bool}. Active profile = profile đang dùng trong current session."

oh autopilot add idea "[P3.2] Backend: POST /api/providers/{name}/activate" --body "Endpoint POST /api/providers/{name}/activate: switch active provider profile. Cập nhật settings.json active_profile field. Reload BackendHostConfig cho sessions mới (sessions hiện tại giữ nguyên cho tới khi reconnect). Return {ok: true, model: new_default_model}."

oh autopilot add idea "[P3.3] Backend: POST /api/providers/{name}/credentials" --body "Endpoint POST /api/providers/{name}/credentials nhận {api_key?: string, base_url?: string}. Lưu api_key qua auth/storage.py hoặc auth/manager.py credential store đã có (tìm hiểu cách hiện tại lưu key). Lưu base_url override vào provider profile settings. Mask api_key trong response (chỉ trả 4 ký tự cuối)."

oh autopilot add idea "[P3.4] Backend: POST /api/providers/{name}/verify" --body "Endpoint POST /api/providers/{name}/verify: thử kết nối tới provider. Ưu tiên gọi GET /v1/models (miễn phí). Nếu provider không hỗ trợ /v1/models thì gọi 1 completion request nhỏ (~10 token). Trả {ok: bool, error?: string, models?: string[]} trong đó models là danh sách model IDs lấy được. Timeout 10s."

oh autopilot add idea "[P3.5] Frontend: Settings/Provider page" --body "Tạo page /settings/provider. Fetch GET /api/providers. Hiển thị grid card cho mỗi provider: icon/emoji theo type, label, status badge (Active/Configured/Not configured), default model. Card active có viền highlight. Click card mở modal: form api_key (password input), base_url, nút Verify, nút Activate. Sau verify thành công hiện danh sách models có thể import."

oh autopilot add idea "[P3.6] Test: provider routes" --body "Tạo tests/webui/test_provider_routes.py. Test list providers trả về ≥9 items. Test activate unknown → 404. Test credentials save + mask. Test verify với mock httpx response."
```

---

## P4 — F3b/c: Models & Agents

```bash
oh autopilot add idea "[P4.1] Backend: GET /api/models — list models by provider" --body "Tạo src/openharness/webui/server/routes/models.py. GET /api/models trả về {provider_id: [{id, label, context_window, is_default, is_custom}, ...]}. Merge built-in models từ ProviderProfile + CLAUDE_MODEL_ALIAS_OPTIONS + custom models từ settings.allowed_models. Group theo provider."

oh autopilot add idea "[P4.2] Backend: POST/DELETE /api/models — add/remove custom model" --body "POST /api/models nhận {provider: string, model_id: string, label?: string, context_window?: int}. Thêm vào ProviderProfile.allowed_models cho provider đó. Persist settings. DELETE /api/models/{provider}/{model_id}: chỉ cho phép xoá custom models (is_custom=true). Return 400 nếu cố xoá built-in."

oh autopilot add idea "[P4.3] Frontend: Settings/Models page" --body "Tạo page /settings/models. Hiển thị accordion theo provider. Mỗi provider: table model (id, label, context window, default toggle, custom badge). Nút 'Add custom model' mở form modal: chọn provider dropdown, nhập model_id, label optional, context_window optional. Nút delete cho custom models (confirm dialog)."

oh autopilot add idea "[P4.4] Backend: GET /api/agents — list agent definitions" --body "Tạo src/openharness/webui/server/routes/agents.py. GET /api/agents gọi coordinator/agent_definitions.py load functions. Trả về list {name, description, model, effort, permission_mode, tools_count, has_system_prompt, source_file}."

oh autopilot add idea "[P4.5] Backend: PATCH /api/agents/{name} — edit agent config" --body "Endpoint PATCH /api/agents/{name} nhận {model?: string, effort?: string, permission_mode?: string}. Load agent definition file (.agents/{name}.md hoặc ~/.claude/agents/{name}.md). Parse YAML frontmatter. Update chỉ các field được gửi. Write back file giữ nguyên body markdown. Validate model phải tồn tại trong /api/models. Return updated agent."

oh autopilot add idea "[P4.6] Frontend: Settings/Agents page" --body "Tạo page /settings/agents. Fetch GET /api/agents. List card cho mỗi agent: name, description (truncate), current model/effort/permission badges. Click card mở inline editor: model dropdown (fetch /api/models flat list), effort select, permission_mode select. Save → PATCH /api/agents/{name}. Toast success/error."

oh autopilot add idea "[P4.7] Test: models + agents routes" --body "Tạo tests/webui/test_models_routes.py: list, add custom, delete custom, delete built-in → 400. Tạo tests/webui/test_agents_routes.py: list agents, patch agent model, patch unknown agent → 404."
```

---

## P5 — F4: Pipeline & Tasks

```bash
oh autopilot add idea "[P5.1] Backend: GET /api/pipeline/cards — autopilot registry" --body "Tạo src/openharness/webui/server/routes/pipeline.py. GET /api/pipeline/cards đọc RepoAutopilotRegistry từ .openharness/autopilot/registry.json. Trả {cards: [{id, title, status, source_kind, score, labels, created_at, updated_at}], updated_at}. Nếu file không tồn tại trả {cards: []}."

oh autopilot add idea "[P5.2] Backend: POST /api/pipeline/cards — enqueue manual idea" --body "POST /api/pipeline/cards nhận {title: string, body?: string, labels?: string[]}. Gọi RepoAutopilotStore(cwd).enqueue_card(source_kind='manual_idea', title=title, body=body). Trả card đã tạo. Return 409 nếu duplicate (fingerprint trùng)."

oh autopilot add idea "[P5.3] Backend: POST /api/pipeline/cards/{id}/action" --body "POST /api/pipeline/cards/{id}/action nhận {action: 'accept'|'reject'|'retry'}. Load registry, tìm card by id. accept → status='accepted'; reject → status='rejected'; retry → reset status='queued'. Persist registry. Return updated card. 404 nếu không tìm thấy."

oh autopilot add idea "[P5.4] Backend: GET /api/pipeline/journal — repo journal" --body "GET /api/pipeline/journal?limit=50 đọc repo journal (JSONL file) từ get_project_repo_journal_path(cwd). Parse từng line JSON → list RepoJournalEntry. Trả 50 entries gần nhất, newest first."

oh autopilot add idea "[P5.5] Backend: GET+PATCH /api/pipeline/policy — autopilot policy CRUD" --body "GET /api/pipeline/policy đọc .openharness/autopilot/autopilot_policy.yaml trả về YAML string + parsed JSON. PATCH /api/pipeline/policy nhận {yaml_content: string}: validate YAML syntax, validate required keys (intake, decision, execution, github, repair), ghi file. Return parsed JSON."

oh autopilot add idea "[P5.6] Backend: Task detail + output endpoints" --body "Thêm trong routes/tasks.py: GET /api/tasks/{id} → task detail (reuse task manager). GET /api/tasks/{id}/output?tail=200 → đọc task output log (tail N lines). POST /api/tasks/{id}/stop → stop task. Wire qua tasks/manager.py."

oh autopilot add idea "[P5.7] Frontend: Pipeline kanban page" --body "Tạo page /pipeline. Layout 4 columns kanban: Queue (queued+accepted), In Progress (preparing+running+verifying+repairing), Review (pr_open+waiting_ci), Done (completed+merged+failed+rejected). Fetch GET /api/pipeline/cards. Mỗi card hiển thị: title, source badge, score, age relative. Click card mở drawer với detail + journal entries + action buttons (Accept/Reject/Retry)."

oh autopilot add idea "[P5.8] Frontend: Pipeline — New idea form + policy editor" --body "Trong /pipeline page: nút '+ New idea' mở modal form (title required, body textarea, labels comma-separated). Submit → POST /api/pipeline/cards → refresh list. Tab 'Policy' trong pipeline page: textarea hiển thị YAML content từ GET /api/pipeline/policy. Nút Save → PATCH. Hiển thị validation error nếu YAML invalid."

oh autopilot add idea "[P5.9] Frontend: Tasks page mở rộng" --body "Tạo page /tasks. Bảng list tất cả tasks: id (truncate 8), type, status (color badge), description, created time. Filter dropdown theo status. Click row mở drawer: full detail + log viewer (fetch /api/tasks/{id}/output, auto-scroll). Nút Stop cho running tasks."

oh autopilot add idea "[P5.10] Test: pipeline + task detail routes" --body "Tạo tests/webui/test_pipeline_routes.py: list empty cards, enqueue card, enqueue duplicate → 409, action accept, action on unknown → 404, journal empty. Tạo tests/webui/test_task_detail_routes.py: get task, get unknown → 404, stop task."
```

---

## P6 — F5: Auto Code-Review

```bash
oh autopilot add idea "[P6.1] Tạo agent definition code-reviewer" --body "Tạo .agents/code-reviewer.md nếu chưa có. YAML frontmatter: name=code-reviewer, description='Review code changes for bugs, security issues, and style', model=null (inherit default), effort=medium, permission_mode=plan, tools=['read_file','grep','glob','bash','lsp']. Body markdown: system prompt hướng dẫn review git diff, check OWASP top 10, check logic bugs, output structured Markdown report với sections: Summary, Issues Found (severity/description/file:line), Suggestions, Overall Score (1-10)."

oh autopilot add idea "[P6.2] Backend: services/auto_review.py — hook task lifecycle" --body "Tạo src/openharness/services/auto_review.py. Function maybe_spawn_review(task_id, cwd, base_branch='main'): (1) check settings auto_review.enabled, (2) chạy git diff --stat base_branch..HEAD trong cwd, (3) nếu có changes: spawn agent code-reviewer với prompt chứa diff summary + file list, (4) lưu review output vào .openharness/autopilot/runs/{task_id}/review.md, (5) update task metadata review_status + review_summary. Hook vào tasks/manager.py khi task status chuyển sang completed."

oh autopilot add idea "[P6.3] Backend: Settings auto_review trong config/settings.py" --body "Thêm class AutoReviewSettings(BaseModel) trong config/settings.py: enabled: bool = False, scope: Literal['all','autopilot_only','manual_only'] = 'autopilot_only', model: str | None = None (override model cho reviewer). Thêm field auto_review: AutoReviewSettings vào Settings class. Wire vào save/load settings."

oh autopilot add idea "[P6.4] Backend: GET /api/review/{task_id} + POST rerun" --body "Tạo routes/review.py. GET /api/review/{task_id}: đọc file .openharness/autopilot/runs/{task_id}/review.md, trả {task_id, status, markdown, created_at}. 404 nếu chưa có review. POST /api/review/{task_id}/rerun: re-spawn code-reviewer agent cho task đó (force). Return {ok: true, message: 'Review started'}."

oh autopilot add idea "[P6.5] Frontend: Review tab trong Pipeline card detail" --body "Trong pipeline card drawer (P5.7): thêm tab 'Review'. Fetch GET /api/review/{task_id}. Nếu có → render markdown (react-markdown). Nếu chưa có → nút 'Run Review'. Nếu đang chạy → spinner 'Reviewing...'. Nút 'Re-run Review' cho reviews đã hoàn tất."

oh autopilot add idea "[P6.6] Frontend: Review badge trong Tasks list" --body "Trong /tasks page (P5.9): thêm cột Review status. Badge: '✅ Reviewed' (xanh), '⏳ Reviewing' (vàng), '—' (xám). Click badge navigate tới review detail."

# [SKIPPED] P6.7 — redundant with autopilot remote_code_review policy (autopilot_policy.yaml). Toggle lives in YAML, not UI.
# oh autopilot add idea "[P6.7] Frontend: Toggle auto-review trong Settings/Modes" ...

# [NARROWED] P6.8 — only test review routes (P6.4 shipped). Auto-spawn tests dropped (no auto_review service needed).
oh autopilot add idea "[P6.8] Test: review routes" --body "Tạo tests/webui/test_review_routes.py: GET review không tồn tại → 404, mock review file → GET trả markdown, POST rerun → 200."
```

---

## P7 — Gap Fixes: WebUI Integration

```bash
oh autopilot add idea "[P7.1] Frontend: History detail — xem transcript session cũ" --body "Trong /history page (HistoryPage.tsx): click vào history item mở drawer/modal. Gọi GET /api/history/{id} để lấy full snapshot. Hiển thị danh sách messages phân biệt role user/assistant bằng màu nền. Hỗ trợ scroll dài. Nút 'Resume session' trong drawer gọi POST /api/sessions {resume_id} rồi navigate /chat. Spawn agents: planner để thiết kế drawer layout → tdd-guide để viết tests trước → code-reviewer sau khi implement."

oh autopilot add idea "[P7.2] Frontend: vim_enabled toggle trong Settings/Modes" --body "Trong ModesSettingsPage.tsx (P2.3): thêm toggle switch cho vim_enabled bên dưới Fast Mode. Label: 'Vim keybindings' với mô tả ngắn 'Enable vim key navigation in the chat input'. Đọc giá trị từ GET /api/modes, lưu qua PATCH /api/modes {vim_enabled: bool}. Debounce 0ms (toggle switch apply ngay). Cập nhật test modes routes để cover vim_enabled. Spawn agents: tdd-guide → viết test PATCH vim_enabled trước → implement toggle → code-reviewer."

oh autopilot add idea "[P7.3] Frontend: Tasks drawer gọi GET /api/tasks/{id}" --body "Trong TasksPage.tsx (P5.9): khi user click mở drawer của một task, gọi GET /api/tasks/{id} để lấy full detail thay vì chỉ dùng data từ list payload. Spinner trong drawer khi đang fetch. Polling mỗi 3s khi task đang running để refresh output. Nút Retry cho tasks ở trạng thái failed. Spawn agents: tdd-guide → test drawer fetch detail API → implement → code-reviewer."

oh autopilot add idea "[P7.4] Frontend: No-WebSocket live pipeline updates" --body "PipelinePage.tsx hiện chỉ fetch một lần. Thêm auto-refresh: interval polling mỗi 5s khi có card ở trạng thái active (running/preparing/verifying/repairing/pr_open/waiting_ci). Dừng polling khi tất cả cards ở trạng thái terminal. Hiển thị 'Last updated Xs ago' indicator. Không thêm thư viện mới. Spawn agents: planner → tdd-guide → code-reviewer."

oh autopilot add idea "[P7.5] Frontend: edit/update custom model UI" --body "Trong ModelsSettingsPage.tsx (P4.3): các custom model (is_custom=true) hiện chỉ có nút delete. Thêm nút Edit mở form modal cho phép sửa label và context_window (model_id readonly). Submit → gọi DELETE rồi POST /api/models với data mới (vì không có PATCH endpoint). Toast success/error. Spawn agents: tdd-guide → test edit flow → implement → code-reviewer."

oh autopilot add idea "[P7.6] Frontend: Agent detail page/modal" --body "Trong AgentsSettingsPage.tsx (P4.6): thêm nút 'View details' trên mỗi agent card. Click mở modal hiển thị: name, description đầy đủ, system prompt preview (truncate 500 chars với 'Show more'), source_file path, danh sách tools, model/effort/permission hiện tại với inline editor. Spawn agents: planner → tdd-guide → code-reviewer."

oh autopilot add idea "[P7.7] Frontend: Pipeline card journal inline" --body "Trong pipeline card drawer (P5.7): hiện chỉ có action buttons. Thêm tab 'Activity' fetch GET /api/pipeline/journal?card_id={id}&limit=20. Hiển thị timeline: icon theo kind (merge_warning, code_review, ci_check...), summary text, relative timestamp. Auto-refresh 10s khi card active. Spawn agents: planner → tdd-guide → code-reviewer."

oh autopilot add idea "[P7.8] Test: gap coverage P7.1–P7.7" --body "Tạo tests/webui/test_history_detail.py: GET /api/history/{id} trả messages list, truncation logic, 404. Cập nhật tests/webui/test_modes_routes.py: thêm test PATCH vim_enabled true/false. Cập nhật tests/webui/test_task_detail_routes.py: GET /api/tasks/{id} trả đúng fields. Spawn agents: tdd-guide (viết tests) → code-reviewer (review test quality)."

```

---

## P8 — Autopilot UI Polish

```bash
oh autopilot add idea "[P8.1] Rebuild Autopilot Kanban board theo lifecycle thật" --body "Thiết kế lại board Autopilot để phản ánh đúng lifecycle thay vì gộp nhiều trạng thái vào In Progress. Cột đề xuất: Queue, Running, Repairing, Waiting CI, Review, Merged, Failed/Rejected. Mapping rõ từng status: queued/accepted→Queue, preparing/running/verifying→Running, repairing→Repairing, waiting_ci/pr_open→Waiting CI, code_review→Review, merged/completed→Merged, failed/rejected/killed→Failed. Card hiển thị status badge màu riêng, spinner khi active, attempt_count, PR link, branch, last_note ngắn. Board auto-refresh 3s khi có active card, 15s khi idle. Spawn agents: planner → a11y-architect → code-reviewer."

oh autopilot add idea "[P8.2] Đổi tên menu Pipeline → Autopilot" --body "Đổi tên nav item 'Pipeline' thành 'Autopilot' trong sidebar (App.tsx). Cập nhật route path /pipeline → /autopilot (giữ redirect từ /pipeline). Đổi tiêu đề trang, document.title, và breadcrumb. Cập nhật tất cả internal link. Spawn agents: code-reviewer."

oh autopilot add idea "[P8.3] Làm rõ Tasks tab — đổi tên thành Jobs và thêm subtitle" --body "Tasks tab hiện tại là background shell processes (autopilot run-next, hooks), không phải autopilot cards — dễ gây nhầm lẫn. Đổi tên nav item thành 'Jobs'. Đổi tiêu đề trang thành 'Background Jobs'. Thêm subtitle nhỏ bên dưới heading: 'Background CLI processes spawned by the system. Autopilot cards are managed in the Autopilot board.' Dùng icon khác biệt (⚙ Jobs, 🤖 Autopilot). Spawn agents: code-reviewer."

oh autopilot add idea "[P8.4] Activity drawer có thể scroll + chiều cao đúng viewport" --body "Trong Autopilot card drawer (P7.7 Activity tab): activity list hiện không scroll được vì container thiếu overflow-y: auto và height bị unconstrained. Fix: wrapper phải có overflow-y: auto, height: 100% hoặc max-height: calc(100vh - <header-height>). Đảm bảo drawer panel tổng thể không overflow ra ngoài viewport trên cả desktop và mobile 375px. Spawn agents: code-reviewer."

oh autopilot add idea "[P8.5] Activity item — truncate message + expand on click" --body "Mỗi activity item trong card drawer hiện hiển thị toàn bộ message text dài, gây khó đọc. Truncate sau 120 chars với '...' và nút 'Show more' expand inline (không mở modal). Status icon cố định bên trái theo kind: repairing=🔴, verifying=🔵, merged=✅, failed=⚠, preparing=🟡. Timestamp relative cố định bên phải. Spawn agents: code-reviewer."

oh autopilot add idea "[P8.6] Activity filter theo loại event" --body "Thêm filter pills bên trên activity list trong card drawer: All | Failures | CI | Agent | Git. Filter theo journal entry kind field. Default: All. Active filter highlight. Giữ filter state trong component (không cần persist). Spawn agents: tdd-guide → code-reviewer."

oh autopilot add idea "[P8.7] Current blocker alert ở đầu card detail" --body "Khi card ở trạng thái failed/repairing/waiting_ci: hiển thị alert banner nổi bật ở đầu drawer (trước activity list) với icon ⚠/⏳, text từ metadata.last_note, và nút action: 'View PR' (link linked_pr_url), 'Retry' (gọi action reset), 'Merge manually'. Ẩn khi card ở trạng thái terminal (merged/rejected/completed). Spawn agents: planner → code-reviewer."
```

---

## P9 — Parallel Autopilot Execution

> **Phân tích rủi ro & giải pháp**: Hiện tại autopilot chạy single-task (boolean gate `already_running`).
> Chuyển sang parallel yêu cầu giải quyết: (1) race condition khi claim card, (2) registry/journal
> file contention, (3) shared main checkout conflicts, (4) worktree cleanup on failure,
> (5) capacity management. Thứ tự task được sắp xếp theo dependency: lock trước → claim → capacity → model → UI.

```bash
oh autopilot add idea "[P9.1] Interprocess lock cho registry + journal" --body "
## Mục tiêu
Thêm file-based interprocess locking cho registry.json và journal.jsonl để tránh lost-update khi nhiều autopilot process chạy song song.

## Phân tích rủi ro hiện tại
- _load_registry() đọc → modify → _save_registry() ghi KHÔNG atomic → 2 process đọc cùng lúc, process B ghi đè thay đổi của A
- append_journal() mở file append nhưng JSONL append trên NFS/SMB có thể interleave
- Hiện tại chưa có locking cơ chế nào

## Giải pháp đề xuất
1. Tạo class RepoFileLock trong src/openharness/autopilot/locking.py
   - Dùng fcntl.flock (Unix) hoặc msvcrt.locking (Windows) — cross-platform
   - Lock file: .openharness/autopilot/registry.lock, journal.lock
   - Context manager: with RepoFileLock(path, timeout=10): ...
   - Timeout + retry (default 10s, backoff 0.1s)
   - Stale lock detection (PID check nếu lock >60s)
2. Wrap _load_registry() + _save_registry() trong RepoFileLock('registry.lock')
3. Wrap append_journal() trong RepoFileLock('journal.lock')
4. Đảm bảo lock file được tạo trong .openharness/autopilot/ (đã có mkdir)

## Files cần sửa
- NEW: src/openharness/autopilot/locking.py
- MODIFY: src/openharness/autopilot/service.py — _load_registry, _save_registry, append_journal
- NEW: tests/test_autopilot/test_locking.py

## Tests yêu cầu
- test_lock_acquire_release: lock → unlock → lock lại OK
- test_lock_blocks_concurrent: 2 threads, thread 2 blocks cho tới khi thread 1 release
- test_lock_timeout: lock held quá timeout → LockTimeoutError
- test_lock_stale_detection: lock file tồn tại nhưng PID chết → acquire OK
- test_registry_save_under_lock: 2 concurrent saves không lost-update

Spawn agents: planner (thiết kế lock protocol) → tdd-guide (viết tests trước) → code-reviewer.
" --labels "parallel,backend,critical-path"

oh autopilot add idea "[P9.2] Atomic card claim — pick_and_claim_card()" --body "
## Mục tiêu
Thay thế pick_next_card() + update_status() riêng lẻ bằng atomic pick_and_claim_card() để tránh 2 process cùng claim 1 card.

## Phân tích rủi ro hiện tại
- pick_next_card() (line 401) chỉ đọc registry, trả card đầu tiên queued
- update_status() (line 407) ghi riêng biệt — window giữa pick và claim cho phép race
- Kết quả: 2 process pick cùng card → cả 2 bắt đầu run → conflict worktree, duplicate PR

## Giải pháp đề xuất
1. Thêm method pick_and_claim_card(worker_id: str) trong RepoAutopilotStore:
   - Acquire RepoFileLock('registry.lock') [từ P9.1]
   - Load registry
   - Filter cards: status in (queued, accepted), sort by score desc, created_at asc
   - Set card.status = 'preparing', card.metadata['worker_id'] = worker_id
   - Save registry
   - Release lock
   - Return card or None
2. worker_id = unique ID per process (uuid4 hoặc PID-timestamp)
3. run_card() sử dụng pick_and_claim_card() thay vì pick + update riêng
4. Nếu card đã bị claim (status != queued/accepted) → return None

## Files cần sửa
- MODIFY: src/openharness/autopilot/service.py — thêm pick_and_claim_card(), sửa run_next()
- MODIFY: tests/test_services/test_autopilot.py

## Tests yêu cầu
- test_pick_and_claim_returns_highest_score: 3 cards queued, claim trả card score cao nhất
- test_pick_and_claim_skips_already_claimed: card đã preparing → skip
- test_pick_and_claim_sets_worker_id: card.metadata['worker_id'] đúng
- test_concurrent_claim_no_duplicate: 2 threads claim song song → mỗi thread nhận card khác nhau
- test_pick_and_claim_none_when_empty: không có queued card → return None

Spawn agents: tdd-guide (viết tests trước) → code-reviewer.
Depends on: P9.1 (cần RepoFileLock).
" --labels "parallel,backend,critical-path"

oh autopilot add idea "[P9.3] Main checkout lock cho _pull_base_branch + _install_editable" --body "
## Mục tiêu
Bảo vệ shared main checkout (self._cwd) khi nhiều autopilot process cùng gọi _pull_base_branch() hoặc _install_editable() sau merge.

## Phân tích rủi ro hiện tại
- _pull_base_branch() (line 1436) chạy git fetch + git pull --ff-only trên self._cwd
- _install_editable() chạy pip install -e . trên self._cwd
- 2 process merge xong cùng lúc → concurrent git pull → corrupt index
- 2 process cùng install_editable → dependency conflict

## Giải pháp đề xuất
1. Thêm RepoFileLock('main-checkout.lock') [reuse P9.1]
2. Wrap _pull_base_branch() call site trong lock
3. Wrap _install_editable() call site trong lock
4. Timeout 60s (pull + install có thể chậm)
5. Lock scope chỉ ở call site, không lock toàn bộ method

## Files cần sửa
- MODIFY: src/openharness/autopilot/service.py — wrap _pull_base_branch, _install_editable calls
- MODIFY: tests/test_services/test_autopilot.py

## Tests yêu cầu
- test_pull_base_branch_acquires_lock: mock lock, verify acquire called
- test_pull_base_branch_releases_lock_on_error: pull fails → lock released
- test_concurrent_pull_serialized: 2 threads pull → serialized execution

Spawn agents: tdd-guide → code-reviewer.
Depends on: P9.1.
" --labels "parallel,backend"

oh autopilot add idea "[P9.4] Per-card model field trong RepoTaskCard" --body "
## Mục tiêu
Cho phép chỉ định model cho từng autopilot card thay vì dùng chung model mặc định từ policy.

## Phân tích hiện tại
- RepoTaskCard (types.py line 47) có metadata: dict[str, Any] nhưng KHÔNG có model field
- run_card() (service.py line 711) xác định effective_model = explicit param hoặc policy default
- Không có cách nào user chọn model cho 1 card cụ thể

## Giải pháp đề xuất
1. Thêm field model: str | None = None vào RepoTaskCard (types.py)
2. Trong run_card(): effective_model = card.model or policy_default
3. enqueue_card() chấp nhận optional model param
4. update_card_model(card_id, model) method mới trong RepoAutopilotStore
5. Migration: registry.json cũ không có model field → Pydantic default None xử lý tự động

## Files cần sửa
- MODIFY: src/openharness/autopilot/types.py — thêm model field
- MODIFY: src/openharness/autopilot/service.py — effective_model logic, update_card_model()
- MODIFY: tests/test_services/test_autopilot.py

## Tests yêu cầu
- test_card_model_default_none: card mới model=None
- test_card_model_overrides_policy: card.model='claude-haiku-4-5' → effective dùng haiku
- test_card_model_none_falls_back_to_policy: card.model=None → dùng policy default
- test_update_card_model: gọi update → model đổi đúng
- test_registry_backward_compat: load registry cũ không có model field → OK

Spawn agents: tdd-guide (viết tests trước) → code-reviewer.
" --labels "parallel,backend"

oh autopilot add idea "[P9.5] Backend API: PATCH /api/pipeline/cards/{id}/model" --body "
## Mục tiêu
API endpoint cho phép WebUI gửi model override cho 1 autopilot card.

## Giải pháp đề xuất
1. Thêm endpoint PATCH /api/pipeline/cards/{id}/model trong routes/pipeline.py
   - Body: {model: string | null} — null để reset về default
   - Validate model tồn tại trong allowed models (optional, warn only)
   - Gọi store.update_card_model(card_id, model)
   - Return updated card
   - 404 nếu card không tồn tại
2. Thêm GET /api/pipeline/cards/{id} endpoint trả full card detail
   - Include model field, metadata, body, linked_pr_url, attempt_count
   - Include available_models list (từ provider profiles)
3. Cập nhật _serialize_card() thêm model field

## Files cần sửa
- MODIFY: src/openharness/webui/server/routes/pipeline.py
- MODIFY: tests/test_webui/test_server.py hoặc test_pipeline_routes.py

## Tests yêu cầu
- test_patch_card_model: set model → 200, card.model updated
- test_patch_card_model_null_resets: set null → model=None
- test_patch_card_model_404: unknown card → 404
- test_get_card_detail: trả full card bao gồm model
- test_serialize_card_includes_model: model field có trong response

Spawn agents: tdd-guide → code-reviewer.
Depends on: P9.4 (cần model field trên RepoTaskCard).
" --labels "parallel,backend,api"

oh autopilot add idea "[P9.6] Frontend: Card detail + model dropdown" --body "
## Mục tiêu
Trong Autopilot board, click card mở detail drawer hiển thị model mặc định, user có thể chọn model khác qua dropdown.

## Giải pháp đề xuất
1. Card detail drawer (mở khi click card trên Kanban board):
   - Header: card title, status badge, source_kind badge
   - Section 'Model': hiển thị current model (policy default nếu null)
     - Dropdown lấy danh sách từ GET /api/models (flatten)
     - Default option: 'Policy default ({policy_model})' 
     - Khi chọn → PATCH /api/pipeline/cards/{id}/model
     - Optimistic update + toast success/error
   - Section 'Details': body, labels, attempt_count, linked_pr_url
   - Section 'Activity': journal entries (reuse P7.7)
   - Section 'Actions': Accept/Reject/Retry/Reset buttons
2. Model dropdown disabled khi card đang active (running/repairing/etc)
3. Responsive: drawer full-width trên mobile

## Files cần sửa
- MODIFY hoặc NEW: frontend/webui/src/components/CardDetailDrawer.tsx
- MODIFY: frontend/webui/src/pages/AutopilotPage.tsx (hoặc PipelinePage.tsx tùy P8.2)

## Tests yêu cầu
- Visual: drawer mở đúng, model dropdown hiển thị
- test_model_dropdown_calls_patch: chọn model → API called
- test_model_dropdown_disabled_when_active: card running → dropdown disabled

Spawn agents: planner (thiết kế drawer layout) → tdd-guide → code-reviewer → a11y-architect.
Depends on: P9.5, P8.1 (Kanban board).
" --labels "parallel,frontend,ui"

oh autopilot add idea "[P9.7] Configurable max_parallel_runs policy" --body "
## Mục tiêu
Thêm cấu hình số lượng task tối đa autopilot có thể chạy song song. Default 2 cho giai đoạn phát triển.

## Giải pháp đề xuất
1. Thêm vào _DEFAULT_AUTOPILOT_POLICY['execution']:
   max_parallel_runs: 2
2. Thêm validation: 1 ≤ max_parallel_runs ≤ 10
3. Web UI: thêm number input trong Policy editor (P5.8) hoặc Settings
4. CLI: oh autopilot config set max_parallel_runs 3

## Files cần sửa
- MODIFY: src/openharness/autopilot/service.py — _DEFAULT_AUTOPILOT_POLICY
- MODIFY: routes/pipeline.py — policy validation
- MODIFY: tests/test_services/test_autopilot.py

## Tests yêu cầu
- test_default_max_parallel_runs_is_2: policy default = 2
- test_max_parallel_runs_validation: <1 hoặc >10 → error
- test_policy_round_trip: save max_parallel_runs=3 → load = 3

Spawn agents: tdd-guide → code-reviewer.
" --labels "parallel,backend,config"

oh autopilot add idea "[P9.8] Capacity-based concurrency gate thay already_running" --body "
## Mục tiêu
Thay thế boolean check 'already_running' bằng capacity check đếm số task đang active so với max_parallel_runs.

## Phân tích hiện tại
- routes/pipeline.py run_next_card(): check any(c.status in active_statuses) → 409
- tick() trong scheduler cũng check tương tự
- Boolean gate chỉ cho 1 task → cần đổi thành count-based

## Giải pháp đề xuất
1. Thêm method count_active_cards() trong RepoAutopilotStore:
   - Count cards với status in {preparing, running, verifying, repairing, waiting_ci, pr_open}
   - Return int
2. Thêm method has_capacity(policies) → bool:
   - return count_active_cards() < policies['execution']['max_parallel_runs']
3. Sửa routes/pipeline.py run_next_card():
   - Thay any(c.status in active_statuses) bằng not store.has_capacity(policies)
   - Error message: 'Maximum parallel runs ({max}) reached. {active} tasks currently active.'
4. Sửa tick() / scheduler tương tự
5. run_next() method trong service: gọi has_capacity() trước pick_and_claim_card()

## Files cần sửa
- MODIFY: src/openharness/autopilot/service.py — count_active_cards, has_capacity, run_next
- MODIFY: src/openharness/webui/server/routes/pipeline.py — run_next_card capacity check
- MODIFY: tests/test_services/test_autopilot.py
- MODIFY: tests/test_webui/test_server.py

## Tests yêu cầu
- test_count_active_cards: 2 running + 1 queued → count = 2
- test_has_capacity_true: 1 active, max=2 → True
- test_has_capacity_false: 2 active, max=2 → False
- test_run_next_rejects_at_capacity: 2 active → 409 với message đúng
- test_run_next_allows_when_under_capacity: 1 active, max=2 → 202

Spawn agents: tdd-guide → code-reviewer.
Depends on: P9.2, P9.7.
" --labels "parallel,backend,critical-path"

oh autopilot add idea "[P9.9] Worktree cleanup finally block" --body "
## Mục tiêu
Đảm bảo worktree luôn được cleanup khi autopilot card fail/crash, tránh leaked worktrees.

## Phân tích hiện tại
- run_card() tạo worktree qua worktree_manager.create_worktree()
- Cleanup chỉ xảy ra trên happy path hoặc một số error path cụ thể
- Nếu exception bất ngờ (OOM, timeout, SIGKILL) → worktree leak
- Leaked worktrees chiếm disk + block branch name

## Giải pháp đề xuất
1. Wrap toàn bộ run_card() worktree section trong try/finally:
   try:
       worktree = await manager.create_worktree(slug)
       ... # all card work
   finally:
       if worktree and use_worktree:
           try:
               await manager.remove_worktree(slug)
           except Exception as cleanup_exc:
               self.append_journal(kind='cleanup_warning', ...)
2. Thêm startup cleanup: khi service init, scan .openharness/worktrees/ cho stale worktrees
   - Worktree mà card status đã terminal → auto remove
   - Log cleanup action
3. Card status update to failed/killed TRƯỚC cleanup (persist trước)

## Files cần sửa
- MODIFY: src/openharness/autopilot/service.py — run_card() try/finally, startup cleanup
- MODIFY: tests/test_services/test_autopilot.py

## Tests yêu cầu
- test_worktree_cleanup_on_exception: mock run raises → worktree removed
- test_worktree_cleanup_failure_non_fatal: cleanup raises → card still failed, journal entry
- test_startup_cleans_stale_worktrees: stale worktree + terminal card → removed
- test_startup_keeps_active_worktrees: active card worktree → NOT removed

Spawn agents: tdd-guide → code-reviewer.
" --labels "parallel,backend,reliability"

oh autopilot add idea "[P9.10] Rebase strategy cho in-flight worktrees" --body "
## Mục tiêu
Khi card A merge vào main, card B đang chạy trên worktree cũ base → cần rebase để tránh merge conflict.

## Phân tích hiện tại
- Mỗi worktree branch từ main tại thời điểm create
- Khi card A merge → main advance → card B worktree stale
- Card B push branch → PR có conflict với new main
- Hiện tại không có auto-rebase mechanism

## Giải pháp đề xuất
1. Sau mỗi _pull_base_branch() (khi card merge xong):
   - List active worktrees qua count_active_cards()
   - Cho mỗi active worktree: schedule git fetch origin main + git rebase origin/main
   - Nếu rebase conflict → abort rebase, journal warning, để card tự handle khi verify
2. Rebase KHÔNG bắt buộc thành công — nếu fail thì card verify step sẽ phát hiện conflict
3. Async: rebase chạy background, không block main flow
4. Lock: cần RepoFileLock per-worktree ('card-{id}.lock') khi rebase

## Alternative đơn giản hơn (recommended cho v1):
- KHÔNG auto-rebase
- Khi card push branch → nếu PR có conflict → repair step detect và rebase
- Đã có repair loop → tận dụng existing mechanism
- Chỉ cần journal entry 'base_advanced' để track

## Files cần sửa
- MODIFY: src/openharness/autopilot/service.py — post-merge notification, optional rebase
- MODIFY: tests/test_services/test_autopilot.py

## Tests yêu cầu  
- test_base_advance_journals_notification: card A merge → journal 'base_advanced' cho active cards
- test_rebase_conflict_non_fatal: rebase fails → journal warning, card continues

Spawn agents: planner (chọn strategy v1 vs full) → tdd-guide → code-reviewer.
Depends on: P9.3, P9.8.
" --labels "parallel,backend,advanced"

oh autopilot add idea "[P9.11] Integration test: 2 cards chạy song song end-to-end" --body "
## Mục tiêu
Test tích hợp đảm bảo 2 autopilot cards có thể chạy song song không conflict.

## Test scenarios
1. test_two_cards_claim_different_cards:
   - Enqueue 3 cards
   - 2 workers gọi pick_and_claim_card() đồng thời
   - Mỗi worker nhận card khác nhau
   - Không card nào bị claim 2 lần

2. test_two_cards_run_in_parallel_worktrees:
   - 2 cards claimed
   - Mỗi card tạo worktree riêng (slug khác nhau)
   - Cả 2 chạy đồng thời không conflict
   - Registry reflect cả 2 đang running

3. test_capacity_gate_blocks_third_card:
   - max_parallel_runs=2
   - 2 cards đang running
   - run_next() cho card thứ 3 → blocked (409)
   - Card 1 finish → run_next() cho card 3 → OK

4. test_merge_one_does_not_corrupt_other:
   - Card A merge → _pull_base_branch()
   - Card B vẫn running → không bị ảnh hưởng
   - Registry vẫn correct

5. test_crash_cleanup_does_not_affect_sibling:
   - Card A crash → worktree cleanup
   - Card B vẫn running bình thường

## Files cần sửa
- NEW: tests/test_autopilot/test_parallel_execution.py

## Mock strategy
- Mock _run_agent_prompt, _run_gh, git commands
- Dùng real file system (tmp_path) cho registry + journal + worktree dirs
- Dùng threading cho concurrent execution

Spawn agents: tdd-guide (viết toàn bộ test scenarios) → code-reviewer.
Depends on: P9.1, P9.2, P9.3, P9.7, P9.8, P9.9.
" --labels "parallel,testing"
```

---

## P10 — WebUI UX/UI Polish & Bug Fixes

> Sắp xếp theo nhóm: Sidebar → Autopilot Board → History → Jobs → Settings → Misc

### P10.A — Sidebar & Navigation

```bash
oh autopilot add idea "[P10.1] UI: Tối ưu layout phần Status trong Sidebar" --body "Cải thiện visual hierarchy cho phần Status trong sidebar: dùng pill/badge thay vì text thuần cho model/provider/permission/effort, thêm màu semantic (xanh=ok, đỏ=error), nhóm các field liên quan, tách JOBS và CRON JOBS thành sub-section riêng với border-top. Tránh hiển thị dày đặc văn bản như hiện tại. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.2] UX: Collapsible SETTINGS section trong Sidebar" --body "Settings section trong sidebar có 4 items (Modes, Provider, Models, Agents) chiếm nhiều space. Thêm toggle collapse/expand cho section SETTINGS. Lưu trạng thái vào localStorage. Khi collapsed: hiện icon gear nhỏ thay vì list. Default: expanded. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.3] UX: Thêm liên kết Docs/Help vào Sidebar" --body "Thêm liên kết 'Docs' hoặc 'Help' ở cuối sidebar (dưới CRON JOBS) dẫn đến tài liệu hướng dẫn sử dụng. Dùng icon ? hoặc book. Mở link trong tab mới. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.4] UI: Header breadcrumb responsive truncation" --body "Header hiện tại hiển thị '* DEFAULT↓ · claude-review · /Users/hodtien/harness/my-harness' — khó đọc trên màn nhỏ. Ưu tiên hiển thị: model badge trước, path truncate từ trái (hiện ...my-harness thay vì full path), tooltip hover để xem đầy đủ. Trên mobile <768px: ẩn path, chỉ giữ model + provider. Spawn agents: code-reviewer."
```

### P10.B — Autopilot Board

```bash
oh autopilot add idea "[P10.5] UI: Column count badge màu theo trạng thái" --body "Header mỗi cột Kanban (QUEUE, IN PROGRESS, REVIEW, COMPLETED, FAILED, REJECTED) chỉ hiển thị số trắng. Thêm màu semantic: QUEUE=xanh-lam, IN PROGRESS=cam (nhấp nháy nhẹ khi count>0), REVIEW=tím, COMPLETED=xanh-lá, FAILED=đỏ, REJECTED=xám mờ. Badge pulse animation khi có card active. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.6] UX: Empty state có hành động cho cột QUEUE" --body "Cột QUEUE đang hiện 'No cards' nhưng không gợi ý gì. Thêm empty state: icon + text 'No tasks queued' + nút '+ Add idea' trực tiếp trong cột (gọi cùng modal với nút '+ New idea' trên header). Tương tự cho cột IN PROGRESS: 'No active tasks. Click Run Next to start.' Spawn agents: code-reviewer."

oh autopilot add idea "[P10.7] UX: Autopilot log viewer — chronological + grouped blocks" --body "Trong card detail drawer (Activity tab): hiện tại log entries không rõ thứ tự. Sắp xếp tất cả entries theo timestamp tăng dần. Gom các entries liên tiếp cùng kind thành collapsible block với header [timestamp] kind (N entries). Expanded by default nếu block ≤3 entries, collapsed nếu >3. Format: ▼ [10:32] implement (3) / ▶ [10:35] tool_use bash (12, collapsed). Spawn agents: planner → code-reviewer." --labels "ux,autopilot"
```

### P10.C — History Page

```bash
oh autopilot add idea "[P10.8] UX: Thêm Skeleton loader cho trang History" --body "Thay thế văn bản 'Loading history...' bằng component Skeleton loader (pulse animation) phản ánh đúng layout card: thumbnail placeholder, text line placeholder, badge placeholder. Reuse LoadingSkeleton.tsx nếu đã có từ X2. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.9] UX: History grouping theo ngày" --body "History list hiện tại là flat list không có separator. Group các sessions theo ngày với sticky header: 'Today', 'Yesterday', '3 days ago', 'Last week', date cụ thể cho cũ hơn. Dùng date-fns formatRelative hoặc Intl.RelativeTimeFormat (không thêm lib nếu chưa có). Spawn agents: code-reviewer."

oh autopilot add idea "[P10.10] UX: History search + filter theo model" --body "Thêm search bar trên History page: filter by summary text (debounce 300ms, client-side trên data đã fetch). Thêm filter dropdown theo model (lấy unique models từ history list). Kết quả filter realtime, không cần fetch lại. Empty state khi không có kết quả: 'No sessions match your search'. Spawn agents: tdd-guide → code-reviewer."

oh autopilot add idea "[P10.11] UX: Nút Copy mở rộng trong History" --body "Thêm nút Copy cho mỗi history item. Copy toàn bộ: summary + model + message_count + created_at dưới dạng plain text. Feedback: icon đổi thành checkmark 1.5s sau khi copy thành công. Thay thế đề xuất P10.7 cũ (chỉ copy description). Spawn agents: code-reviewer."
```

### P10.D — Jobs Page

```bash
oh autopilot add idea "[P10.12] UI: Status styling cho Background Jobs" --body "Bảng Background Jobs: thêm màu và icon theo trạng thái cho từng dòng — xanh lá + ✓ cho completed, đỏ + ✗ cho failed/error, vàng + spinner cho running. Status badge thay vì text thuần. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.13] UX: Inline log viewer cho Jobs" --body "Khi click vào một job trong TasksPage, drawer hiện chỉ có basic info. Thêm inline log viewer: terminal-style monospace font, dark background, scroll, auto-follow tail khi job đang running (polling mỗi 2s). Nút 'Scroll to bottom' floating khi user scroll lên. Nút copy log. Spawn agents: tdd-guide → code-reviewer."
```

### P10.E — Settings Pages

```bash
oh autopilot add idea "[P10.14] UI: Cải thiện input 'Passes' trong Modes Settings" --body "Chuyển đổi ô nhập 'Passes' trong ModesSettingsPage từ text input sang number input (type=number, min=1, max=5) với stepper buttons. Hiển thị visual indicator (ví dụ 5 dots, active dots = passes value) bên cạnh để trực quan hơn. Spawn agents: code-reviewer."

oh autopilot add idea "[P10.15] UI: Syntax highlighting cho Autopilot Policy editor" --body "Trong PipelinePage tab Policy: thay textarea thuần bằng editor có syntax highlighting YAML. Dùng CodeMirror 6 (@codemirror/lang-yaml) hoặc monaco-editor nếu đã có dependency. Nếu chưa có thư viện nào: dùng highlight.js chỉ cho read-only preview + textarea cho edit. Validate YAML realtime, hiển thị error inline dưới editor. Spawn agents: code-reviewer."
```

### P10.F — Chat & Misc

```bash
oh autopilot add idea "[P10.16] UX: Cập nhật thông báo trang Chat" --body "Cập nhật ChatPage: khi đã kết nối WebSocket thành công, thay 'Waiting for backend...' bằng welcome message hiển thị: session ID (truncate), model đang dùng, trạng thái kết nối với icon xanh. Khi mất kết nối: hiển thị banner đỏ 'Disconnected — attempting to reconnect...' với spinner. Spawn agents: code-reviewer."
```

---

## Cross-cutting

```bash
oh autopilot add idea "[X1] Docs: cập nhật WEBUI.md + tạo WEBUI-SETTINGS.md" --body "Cập nhật docs/WEBUI.md thêm section mô tả các tính năng mới: History/Resume, Mode toggles, Settings, Pipeline dashboard, Auto review. Tạo docs/WEBUI-SETTINGS.md hướng dẫn chi tiết cách cấu hình provider, models, agents qua Web UI. Tạo docs/WEBUI-PIPELINE.md hướng dẫn sử dụng Pipeline kanban + auto review. Spawn agents: doc-updater."

oh autopilot add idea "[X2] Frontend: Error handling + loading states nhất quán" --body "Tạo shared components: LoadingSkeleton.tsx (pulse animation), ErrorBanner.tsx (retry button), EmptyState.tsx (icon + message). Áp dụng pattern: mỗi page fetch data → show skeleton → show content hoặc error. Toast notifications cho PATCH success/fail (tạo simple toast system dùng zustand, không thêm lib). Áp dụng cho tất cả pages P1-P7. Spawn agents: planner → tdd-guide → code-reviewer → a11y-architect."
```

---

## P11 — Multi-Project Support

> **Mục tiêu**: Cho phép OpenHarness quản lý nhiều project (folder), mỗi project có lịch sử chat, autopilot tasks, sessions riêng biệt. Chuyển đổi project qua Web UI và CLI.
> **Registry**: `~/.openharness/projects.json` lưu danh sách project với name/path/description.
> **Backward compat**: Khi registry rỗng, tự tạo default project từ cwd hiện tại.

### P11.A — Backend

```bash
oh autopilot add idea "[P11.1] Backend: Project model và registry" --body "Tạo src/openharness/config/projects.py:
1. Project(BaseModel): id (slug từ name), name, path (abs), description, created_at, updated_at, is_active
2. ProjectRegistry class:
   - REGISTRY_PATH = ~/.openharness/projects.json
   - load() -> {projects: list[Project], active_project_id: str}
   - save(registry) với atomic_write_text + file lock (theo pattern _cron_lock_path trong services/cron.py)
   - add_project(name, path, description) -> Project. Slugify name cho id, validate path là directory
   - remove_project(id) -> bool. Không xoá folder thật
   - update_project(id, name?, description?) -> Project
   - activate_project(id) -> Project. Set is_active, clear others
   - get_active_project() -> Project | None
   - ensure_default(cwd: Path) -> tạo default project từ cwd nếu registry rỗng
3. Validate: không duplicate paths, không duplicate names, path phải là directory tồn tại

Tests: test_project_crud, test_activate, test_ensure_default, test_duplicate_prevention.
Spawn agents: code-reviewer." --labels "backend,multi-project"

oh autopilot add idea "[P11.2] Backend: Project CRUD API endpoints" --body "Tạo src/openharness/webui/server/routes/projects.py:
1. GET /api/projects -> {projects: [...], active_project_id: str}
2. POST /api/projects -> Body: {name, path, description?} -> Project (201). 400 nếu path không phải dir, 409 nếu duplicate.
3. PATCH /api/projects/{id} -> {name?, description?} -> updated Project. 404 nếu không tìm thấy.
4. DELETE /api/projects/{id} -> {ok: true}. 404 nếu không tồn tại, 400 nếu đang active.
5. POST /api/projects/{id}/activate -> {ok: true, project: Project}. Trigger project switch (xem P11.3).

Register trong app.py: app.include_router(projects_routes.router). Tất cả endpoints yêu cầu require_token.

Tests: test_projects_api_crud, test_activate_endpoint, test_validation_errors.
Spawn agents: code-reviewer.
Depends on: P11.1." --labels "backend,multi-project,api"

oh autopilot add idea "[P11.3] Backend: Logic chuyển đổi project trong WebUIState" --body "Sửa state.py và app.py:
1. Thêm vào WebUIState: active_project_id: str | None = None
2. Thêm method switch_project(self, project: Project): cập nhật self.cwd và self.active_project_id
3. Trong create_app(): gọi ProjectRegistry.ensure_default(resolved_cwd), load active project, set state.active_project_id. Nếu active project tồn tại, dùng path của nó làm cwd.
4. Trong routes/projects.py activate endpoint: gọi state.switch_project(project), recreate SessionManager với WebUIConfig(cwd=project.path, ...), cập nhật app.state.webui_session_manager
5. Broadcast event 'project_switched' qua WebSocket tới tất cả connected clients

Tests: test_switch_project_updates_cwd, test_session_manager_recreated.
Spawn agents: planner → code-reviewer.
Depends on: P11.1, P11.2." --labels "backend,multi-project"

oh autopilot add idea "[P11.4] Backend: Audit session/chat isolation theo project" --body "Audit và verify per-project isolation cho session/chat layer:
1. Xác nhận get_project_session_dir(cwd) dùng cwd hash cho directory naming — đã OK
2. Verify tất cả session operations trong sessions.py, history routes, snapshot loading dùng state.cwd (dynamic)
3. Verify routes/ws.py WebSocket streams và reconnect path không leak state của project cũ sau khi switch
4. Verify latest session pointer, history list, resume flow đều scoped theo active project
5. Thêm integration test: hai projects, sessions/history không cross-contaminate

Không cover autopilot/cron ở task này — phần đó tách riêng ở P11.5.

Spawn agents: code-reviewer.
Depends on: P11.3." --labels "backend,multi-project"
```

### P11.B — Frontend

```bash
oh autopilot add idea "[P11.5] Frontend: ProjectSelector dropdown + active project state" --body "Thêm UI chọn project ở header/sidebar:
1. Tạo ProjectSelector.tsx: dropdown hiển thị active project name + path tooltip
2. Fetch GET /api/projects khi mount -> list projects + active_project_id
3. Khi user chọn project khác: POST /api/projects/{id}/activate
4. Update global store (zustand) activeProject và project list
5. Sau activate thành công: reset current session/transcript state, reconnect WebSocket với project mới, refresh History/Autopilot/Jobs data
6. Hiển thị toast 'Switched to <project>'

Không reload full page; giữ SPA state và trigger data refetch.

Tests: component state transitions, API call sequence.
Spawn agents: planner → code-reviewer.
Depends on: P11.2, P11.3." --labels "frontend,multi-project"

oh autopilot add idea "[P11.6] Frontend: Project API client + shared types" --body "Tạo/extend frontend/webui/src/api/client.ts và types.ts:
1. type Project, ProjectListResponse
2. api.listProjects(), api.createProject(), api.updateProject(), api.deleteProject(), api.activateProject()
3. Handle error mapping 400/404/409 với message rõ ràng cho UI
4. Export hooks/helper để pages khác reuse

Refactor ProjectSelector và future Projects page dùng chung API layer này.

Spawn agents: code-reviewer.
Depends on: P11.2." --labels "frontend,multi-project"

oh autopilot add idea "[P11.7] Frontend: Projects management page" --body "Tạo page /projects:
1. List tất cả projects với name, path, description, active badge
2. Form thêm project mới: name, path, description
3. Inline edit name/description
4. Delete project (confirm modal), disable delete nếu active
5. Button 'Activate' cho project không active
6. Validation UI: path required, duplicate warning, backend error display

UI nên đơn giản nhưng rõ ràng; không cần drag/drop.

Tests: create/edit/delete/activate flows.
Spawn agents: planner → code-reviewer.
Depends on: P11.2, P11.6." --labels "frontend,multi-project,ui"

oh autopilot add idea "[P11.8] Frontend: Chuyển project không reload + reconnect đúng cách" --body "Fix regression-prone flow khi switch project:
1. WebSocket/session reconnect phải dùng cwd/project mới
2. Hủy subscriptions/polling của project cũ
3. Reset pipeline/history/jobs caches về loading state trước khi refetch
4. Nếu session hiện tại đang mở transcript, clear transcript để tránh hiển thị message project cũ
5. Tránh full-page reload; chỉ soft reconnect + data reload

Đây là task UX correctness quan trọng cho multi-project.

Tests: switch project while connected, ensure transcript/history/pipeline đều đổi theo project mới.
Spawn agents: tdd-guide → code-reviewer.
Depends on: P11.5, P11.6." --labels "frontend,multi-project,critical"
```

### P11.C — CLI, Tests, Docs

```bash
oh autopilot add idea "[P11.9] CLI: project commands cơ bản" --body "Mở rộng CLI với namespace project:
1. `oh project list`
2. `oh project add <path> [--name ...] [--description ...]`
3. `oh project activate <id-or-name>`
4. `oh project remove <id-or-name>`
5. `oh project current`

CLI dùng chung ProjectRegistry từ P11.1. Output human-readable + JSON mode nếu framework CLI hiện có hỗ trợ.

Tests: command happy path + error cases.
Spawn agents: code-reviewer.
Depends on: P11.1." --labels "cli,multi-project"

oh autopilot add idea "[P11.10] Tests: Multi-project integration coverage" --body "Thêm integration tests end-to-end cho multi-project:
1. create 2 temp project dirs
2. ensure history/session isolation
3. switch active project qua API -> state.cwd đổi
4. pipeline/journal endpoints đọc dữ liệu theo project active
5. websocket reconnect sau switch project không leak messages cũ

Ưu tiên test backend + light frontend integration; không cần full browser e2e ở task này.

Spawn agents: tdd-guide → code-reviewer.
Depends on: P11.3, P11.5, P11.8." --labels "testing,multi-project"

oh autopilot add idea "[P11.11] Docs: Multi-project user guide" --body "Cập nhật docs cho multi-project:
1. GUIDE.md: section Projects / quản lý nhiều repo
2. AUTOPILOT.md: giải thích registry theo project và switching
3. Nếu có docs WebUI riêng: thêm screenshots hoặc flow mô tả ProjectSelector + Projects page
4. Nêu rõ backward compatibility: project mặc định được tạo từ cwd hiện tại

Spawn agents: doc-updater.
Depends on: P11.1, P11.5." --labels "docs,multi-project"

oh autopilot add idea "[P11.12] Docs/Test snapshot: refresh docs snapshot sau multi-project" --body "Sau khi P11 hoàn tất:
1. rebuild frontend docs snapshot nếu project có generated static docs
2. cập nhật docs/autopilot/snapshot.json hoặc artifact tương tự nếu cần
3. verify docs references /projects routes đúng

Task này dành cho final polish + consistency.
Spawn agents: doc-updater.
Depends on: P11.11." --labels "docs,multi-project,polish"
```

---

## P12 — Autopilot Cron Scheduling Configuration

### P12.A — Backend

```bash
oh autopilot add idea "[P12.1] Backend: Cron schedule config model + persistence" --body "Thêm cấu hình lịch chạy autopilot vào settings/policy:
1. CronScheduleConfig model: enabled, scan_cron, tick_cron, timezone?, install_mode
2. Persist trong file policy hoặc settings phù hợp với cấu trúc hiện tại
3. Default: scan mỗi 15 phút, tick mỗi giờ (giữ behavior cũ)
4. Validate cron expression bằng helper/library sẵn có; nếu chưa có, validate format 5 trường cơ bản

Không cài cron ở task này; chỉ model + persistence.

Tests: load/save/validation/defaults.
Spawn agents: code-reviewer." --labels "backend,cron"

oh autopilot add idea "[P12.2] Backend: GET/PATCH cron scheduling API" --body "Tạo/extend API cho cron scheduling config:
1. GET /api/cron/config -> current config
2. PATCH /api/cron/config -> update enabled/scan_cron/tick_cron
3. Response gồm preview human-readable ('Every 15 minutes', ...)
4. Return validation errors rõ ràng nếu cron invalid

Reuse config model từ P12.1.

Tests: GET, PATCH valid, PATCH invalid.
Spawn agents: code-reviewer.
Depends on: P12.1." --labels "backend,cron,api"

oh autopilot add idea "[P12.3] Backend: Cron preview + next-run computation" --body "Thêm helper tính toán next run times cho scan/tick schedule:
1. Hàm preview cron -> next 3 run timestamps
2. API response include next_scan_runs, next_tick_runs
3. Nếu disabled -> arrays rỗng
4. Timezone handling rõ ràng; nếu app chưa support timezone custom thì dùng local timezone hiện tại và expose label

Tests: deterministic preview với frozen time.
Spawn agents: code-reviewer.
Depends on: P12.1, P12.2." --labels "backend,cron"

oh autopilot add idea "[P12.4] Backend: install-cron endpoint/command integration" --body "Bridge config với luồng install cron hiện có:
1. expose action để apply config hiện tại vào crontab/install routine
2. nếu project có endpoint/CLI install-cron hiện hữu, refactor để đọc từ config thay vì hardcode scan 15m/tick 1h
3. response trả installed commands và cron lines để user audit
4. không silent overwrite; log rõ thay đổi

Tests: install payload/command generation.
Spawn agents: planner → code-reviewer.
Depends on: P12.1." --labels "backend,cron"
```

### P12.B — Frontend

```bash
oh autopilot add idea "[P12.5] Frontend: Cron scheduling settings UI" --body "Thêm UI cấu hình cron schedule trong Settings hoặc Autopilot Policy page:
1. Toggle enabled
2. Input scan_cron và tick_cron
3. Helper text ví dụ cron patterns
4. Preview next 3 runs từ API
5. Nút Save / Apply

UX ưu tiên an toàn: hiển thị warning nếu schedule quá dày.

Tests: form state + validation rendering.
Spawn agents: planner → code-reviewer.
Depends on: P12.2, P12.3." --labels "frontend,cron,ui"

oh autopilot add idea "[P12.6] Frontend: Preset schedule shortcuts" --body "Trong cron scheduling UI thêm preset buttons:
- Conservative: scan 30m / tick 2h
- Default: scan 15m / tick 1h
- Aggressive: scan 5m / tick 15m
- Disabled

Click preset sẽ fill form nhưng vẫn cho user chỉnh tay sau đó. Hiển thị note về tradeoff resource usage.

Spawn agents: code-reviewer.
Depends on: P12.5." --labels "frontend,cron,ux"

oh autopilot add idea "[P12.7] Frontend: Install/apply cron action feedback" --body "Sau khi user apply cron config:
1. Hiển thị result panel/toast với cron lines đã cài
2. Hiển thị lỗi rõ ràng nếu install thất bại
3. Có nút copy cron config / command
4. Nếu app không thể cài tự động trong current env, hiển thị manual instructions fallback

Spawn agents: code-reviewer.
Depends on: P12.4, P12.5." --labels "frontend,cron,ux"
```

### P12.C — CLI & Tests

```bash
oh autopilot add idea "[P12.8] Tests: cron scheduling integration" --body "Thêm coverage cho scheduling config end-to-end:
1. config round-trip API
2. preview next runs deterministic
3. install routine consumes configured cron values thay vì hardcode
4. frontend form submits đúng payload

Spawn agents: tdd-guide → code-reviewer.
Depends on: P12.2, P12.4, P12.5." --labels "testing,cron"
```

---

## P13 — Autopilot Task Resilience (Pre-flight + Pending/Resume)

### P13.A — Status & Pre-flight

```bash
oh autopilot add idea "[P13.1] Backend: Pre-flight check trước khi run card" --body "Thêm pre-flight step trước khi autopilot thực sự chạy agent:
1. Kiểm tra provider/model available
2. Kiểm tra auth/token/API key nếu cần
3. Kiểm tra network / GitHub availability cho flow cần PR
4. Kiểm tra repo state tối thiểu (cwd tồn tại, git repo nếu policy yêu cầu)
5. Nếu fail do transient reason -> không mark failed ngay, chuyển sang pending

Record structured reason trong metadata để UI/CLI hiển thị.

Tests: preflight success, auth failure, network failure.
Spawn agents: planner → code-reviewer." --labels "backend,resilience"

oh autopilot add idea "[P13.2] Backend: Thêm trạng thái pending + retry metadata" --body "Mở rộng lifecycle autopilot với trạng thái `pending` cho lỗi tạm thời:
1. cho phép status pending trong card model/registry
2. metadata: pending_reason, next_retry_at, retry_count
3. scheduler/tick bỏ qua pending card cho tới next_retry_at
4. policy retry/backoff cơ bản: exponential hoặc fixed schedule đơn giản
5. pending không tính là failed terminal

Cần cập nhật serialize, filters, counts, journal.

Tests: status transition pending, retry timing, pending not counted as active capacity.
Spawn agents: code-reviewer.
Depends on: P13.1." --labels "backend,resilience"

oh autopilot add idea "[P13.3] Backend: Pre-flight API endpoint" --body "Expose pre-flight diagnostics qua API:
1. GET /api/pipeline/preflight hoặc POST on-demand
2. trả checks list: provider_ok, auth_ok, github_ok, repo_ok, messages
3. frontend dùng endpoint này để hiển thị health trước khi user bấm run-next
4. cache ngắn nếu cần để tránh spam external checks

Tests: endpoint payload + failure mapping.
Spawn agents: code-reviewer.
Depends on: P13.1." --labels "backend,resilience,api"
```

### P13.B — Core Logic

```bash
oh autopilot add idea "[P13.4] Backend: Pending retry scheduler + resume logic" --body "Implement core logic cho pending cards:
1. tick() hoặc scheduler chọn lại card pending khi đến next_retry_at
2. reset status pending -> accepted/preparing trước khi retry
3. retry_count vượt ngưỡng thì chuyển failed với summary rõ ràng
4. journal ghi transition pending/resumed/retry_exhausted
5. manual retry action có thể clear pending ngay

Tests: scheduler retries pending card, retry exhausted -> failed, manual retry resets pending.
Spawn agents: planner → code-reviewer.
Depends on: P13.2." --labels "backend,resilience"

oh autopilot add idea "[P13.9] Backend: Auto-merge autopilot_managed PR khi CI pass" --body "Gap hiện tại: run_card() chỉ gọi _process_existing_pr_card() (check CI + merge) cho source_kind='github_pr' external hoặc last_failure_stage='repair_exhausted'. Card autopilot_managed=True với PR open + CI pass không có path merge tự động — bị kẹt ở waiting_ci hoặc rerun repair vô tận.

Fix:
1. Trong run_card(), sau khi tạo worktree và trước khi chạy agent: check nếu card có linked_pr_number + metadata.autopilot_managed=True + last_ci_conclusion='success' -> gọi trực tiếp _try_merge_pr() thay vì chạy repair loop.
2. Hoặc tạo _check_and_merge_if_ci_passed(card) helper: query GitHub PR status, nếu CI pass -> merge -> update status='merged'.
3. Gọi helper này trong tick() sau _recover_stuck_cards() cho các card ở waiting_ci + autopilot_managed=True.

Tests:
- test_autopilot_managed_card_merged_when_ci_pass: card autopilot_managed=True + waiting_ci + CI pass -> tick() -> status=merged
- test_autopilot_managed_card_stays_waiting_when_ci_pending: CI pending -> không merge
- test_autopilot_managed_card_repairs_when_ci_fail: CI fail -> vào repair flow

Spawn agents: code-reviewer.
Depends on: P11.5." --labels "backend,autopilot,reliability"
```

### P13.C — API, Frontend & Tests

```bash
oh autopilot add idea "[P13.5] Backend: Pipeline API hỗ trợ pending status" --body "Cập nhật routes/pipeline.py serialization + counts:
1. pending xuất hiện trong cards list/detail
2. include pending_reason, next_retry_at, retry_count trong payload
3. run-next/capacity logic bỏ qua pending card trừ khi due
4. action endpoint thêm 'retry-now' cho pending card

Spawn agents: code-reviewer.
Depends on: P13.2." --labels "backend,resilience,api"

oh autopilot add idea "[P13.6] Frontend: Pending status trong autopilot board" --body "Cập nhật board UI để hiển thị pending rõ ràng:
1. thêm column hoặc group cho Pending
2. card hiển thị pending_reason + next retry relative time
3. button 'Retry now' trong card detail
4. không gộp pending vào failed để tránh gây hiểu nhầm

Tests: render pending card + retry-now action.
Spawn agents: code-reviewer.
Depends on: P13.5." --labels "frontend,resilience,ui"

oh autopilot add idea "[P13.7] Tests: Task resilience integration tests" --body "Thêm integration coverage cho pending/resume flow:
1. preflight network failure -> pending
2. transient runtime error -> pending
3. scheduler retries when due
4. exhausted retries -> failed
5. manual retry-now recovers pending card

Spawn agents: tdd-guide → code-reviewer.
Depends on: P13.4, P13.5, P13.6." --labels "testing,resilience"

oh autopilot add idea "[P13.8] Backend: Pre-flight check API endpoint cho WebUI/CLI" --body "Nếu P13.3 mới cover nội bộ, task này hoàn thiện contract public:
1. endpoint callable từ WebUI và CLI
2. standardized payload cho human-readable + machine-readable diagnostics
3. CLI command `oh autopilot preflight`
4. docs/help text ngắn cho từng failure type

Spawn agents: code-reviewer.
Depends on: P13.3." --labels "backend,resilience,api"
```

---

## P14 — Settings Review & Polish

```bash
oh autopilot add idea "[P14.1] UI: Modes page — thêm notifications và auto-compact settings" --body "Enhance ModesSettingsPage.tsx:
1. Add toggle for notification preferences relevant to WebUI/autopilot events
2. Add auto-compact / transcript compaction related setting nếu app đã support ở backend/settings
3. Group related controls rõ ràng hơn, tách runtime controls vs UX preferences
4. Show helper text ngắn cho mỗi advanced option

Tests: settings form render + submit payload.
Spawn agents: code-reviewer." --labels "frontend,settings,ux"

oh autopilot add idea "[P14.2] UI: Provider page — connection status và batch verify" --body "Enhance ProviderSettingsPage.tsx:
1. Hiển thị connection status badge realtime-ish cho từng provider
2. Add 'Verify all configured providers' action
3. Improve result presentation: latency, model count, last verified time
4. Disable noisy actions khi verify đang chạy

Spawn agents: planner → code-reviewer.
Depends on: P3.4." --labels "frontend,settings,ux"

oh autopilot add idea "[P14.3] UI: Models page — capabilities info và search" --body "Enhance ModelsSettingsPage.tsx:
1. Search/filter models by id/label
2. Show capability badges nếu available (vision, tools, long-context, fast, etc.)
3. Better grouping/sorting of custom vs built-in models
4. Improve empty state when provider has no models

Spawn agents: code-reviewer." --labels "frontend,settings,ux"

oh autopilot add idea "[P14.4] UI: Agents page — system prompt preview, clone, test" --body "Enhance AgentsSettingsPage.tsx:
1. Preview full system prompt/body with expand modal
2. Add clone/copy agent config flow để tạo agent mới từ template
3. Add lightweight test action or validation for edited config
4. Surface source file path + changed status clearly

Spawn agents: planner → code-reviewer." --labels "frontend,settings,ux"

oh autopilot add idea "[P14.5] UI: Cross-cutting settings form validation và UX" --body "Improvements cho tất cả settings pages:
1. consistent dirty state indicator
2. unsaved changes warning khi rời page
3. inline validation messages nhất quán
4. save/apply success state rõ ràng
5. keyboard/focus UX polish

Depends on: P14.1, P14.2, P14.3, P14.4." --labels "frontend,settings,ux"

oh autopilot add idea "[P14.6] Tests: Settings pages integration tests" --body "Tạo tests/test_settings_improvements.py:
1. modes settings advanced fields
2. provider batch verify UI flow
3. model search/filter
4. agent prompt preview/clone flow
5. dirty-state + unsaved warning behavior

Depends on: P14.1, P14.2, P14.3, P14.4, P14.5.
" --labels "testing,settings"
```

---

**Tổng cộng**: 126 tasks (P0=3, P1=8, P2=6, P3=6, P4=7, P5=10, P6=8, P7=8, P8=7, P9=11, P10=16, P11=12, P12=8, P13=8, P14=6, Cross=2)

> P10 được tổ chức lại thành 6 nhóm: A=Sidebar/Nav (4), B=Autopilot Board (3), C=History (4), D=Jobs (2), E=Settings (2), F=Misc (1)
> P11-P14 bổ sung ngày 2026-05-06: Multi-Project (12), Cron Scheduling (8), Task Resilience (8), Settings Polish (6)
