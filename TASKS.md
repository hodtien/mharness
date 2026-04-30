# WebUI Upgrade — Autopilot Task List

> Generated: 2026-04-29
> Cách dùng: copy từng block lệnh `oh autopilot add` chạy trong terminal tại thư mục project root (`/Users/hodtien/harness/my-harness`).

## Mục lục
- [P0 — Foundation: Router + Backend restructure](#p0--foundation)
- [P1 — F1: Quản lý lịch sử chat (resume)](#p1--f1-history--resume)
- [P2 — F2: Bật/tắt các modes](#p2--f2-modes-toggle)
- [P3 — F3a: Provider settings](#p3--f3a-provider-settings)
- [P4 — F3b/c: Models + Agents](#p4--f3bc-models--agents)
- [P5 — F4: Pipeline & Task dashboard](#p5--f4-pipeline--tasks)
- [P6 — F5: Auto code-review sau task done](#p6--f5-auto-code-review)
- [Cross-cutting](#cross-cutting)

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

oh autopilot add idea "[P6.7] Frontend: Toggle auto-review trong Settings/Modes" --body "Trong /settings/modes page (P2.3): thêm section 'Auto Code Review'. Toggle enabled/disabled. Dropdown scope (All tasks / Autopilot only / Manual only). Model override input (optional, placeholder 'Use default'). Save → PATCH tới endpoint mới PATCH /api/settings/auto-review."

oh autopilot add idea "[P6.8] Test: auto_review service + review routes" --body "Tạo tests/webui/test_review_routes.py: GET review không tồn tại → 404, mock review file → GET trả markdown. Tạo tests/services/test_auto_review.py: test maybe_spawn_review với mock git diff empty → skip, mock git diff có changes → spawn được gọi, test settings disabled → skip."
```

---

## Cross-cutting

```bash
oh autopilot add idea "[X1] Docs: cập nhật WEBUI.md + tạo WEBUI-SETTINGS.md" --body "Cập nhật docs/WEBUI.md thêm section mô tả các tính năng mới: History/Resume, Mode toggles, Settings, Pipeline dashboard, Auto review. Tạo docs/WEBUI-SETTINGS.md hướng dẫn chi tiết cách cấu hình provider, models, agents qua Web UI. Tạo docs/WEBUI-PIPELINE.md hướng dẫn sử dụng Pipeline kanban + auto review."

oh autopilot add idea "[X2] Frontend: Error handling + loading states nhất quán" --body "Tạo shared components: LoadingSkeleton.tsx (pulse animation), ErrorBanner.tsx (retry button), EmptyState.tsx (icon + message). Áp dụng pattern: mỗi page fetch data → show skeleton → show content hoặc error. Toast notifications cho PATCH success/fail (tạo simple toast system dùng zustand, không thêm lib). Áp dụng cho tất cả pages P1-P6."
```

---

**Tổng cộng**: 38 tasks (P0=3, P1=8, P2=6, P3=6, P4=7, P5=10, P6=8, Cross=2)
