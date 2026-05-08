# Autopilot — Chạy tự động từ đầu đến cuối

my-harness có 2 chế độ autopilot:

- **A. `full_auto` mode** — 1 session, 1 prompt, agent tự làm hết
- **B. `oh autopilot`** — repo-wide queue, scan → run → PR → CI → merge liên tục

---

## A. `full_auto` mode — autopilot trong 1 session

Permission mode bypass mọi prompt confirmation. Agent tự edit/run/spawn
từ đầu đến cuối, không hỏi xác nhận.

### Cách bật

```bash
# Cách 1: flag --permission-mode
oh -p "Implement user-profile API endpoint with tests" \
   --permission-mode full_auto \
   --max-turns 50

# Cách 2: --dangerously-skip-permissions (alias → full_auto)
oh -p "..." --dangerously-skip-permissions

# Cách 3: trong interactive session, đổi mode runtime
oh
> /permissions full_auto
```

### Flow end-to-end (1 prompt → done)

```
1. Bridge load ~/.claude/settings.json → resolve model + auth
2. Agent đọc prompt, vào loop:
   ├─ Plan → spawn sub-agents (planner/tdd-guide/worker) qua AgentTool
   ├─ Mỗi sub-agent dùng model theo agent_models[name] chain
   └─ Tools (FileEditTool/BashTool/GrepTool) chạy không hỏi xác nhận
3. Loop kết thúc khi:
   ├─ Agent declare done
   ├─ Hết --max-turns
   └─ Lỗi fatal
4. Output: text / json / stream-json (tùy --output-format)
```

### Ví dụ pipeline

```bash
# Full feature: đọc spec → code → test → fix
oh -p "Read GUIDE.md, implement feature X, write tests, run pytest, fix failures" \
   --permission-mode full_auto \
   --max-turns 100 \
   --output-format json > result.json

# Bug fix nhanh
oh -p "Fix the null pointer in src/auth.py line 42, run tests to verify" \
   --permission-mode full_auto

# Refactor + commit
oh -p "Refactor payment module to use repository pattern, commit with message" \
   --permission-mode full_auto \
   --max-turns 80
```

### Kết hợp CI script

```bash
#!/usr/bin/env bash
# auto-review.sh — chạy review tự động
set -euo pipefail

PR_DIFF=$(git diff origin/main...HEAD)

oh -p "Review this PR diff for security and quality issues:
$PR_DIFF" \
  --permission-mode full_auto \
  --max-turns 20 \
  --output-format json > review.json

# Alert nếu có CRITICAL
jq -e '.issues[] | select(.severity == "CRITICAL")' review.json && \
  echo "CRITICAL issues found!" && exit 1
```

### Cảnh báo

- `full_auto` sẽ tự `rm`, `git push`, gọi API — **không hỏi**
- Chỉ dùng trong sandboxed env: Docker, worktree, VM, hoặc throwaway branch
- Luôn set `--max-turns` để tránh loop vô hạn
- Nên `--dry-run` trước để verify config:
  ```bash
  oh -p "..." --permission-mode full_auto --dry-run
  ```

---

## B. `oh autopilot` — repo-wide queue (kanban end-to-end)

Multi-task continuous autopilot: scan sources → enqueue cards → chạy
highest-priority → PR → CI → merge. Chạy 24/7 qua cron.

### Lifecycle

```
queued → accepted → preparing → running → verifying
       → waiting_ci → code_review → completed → merged
                                  → failed → repairing (auto retry)
                                  → rejected
                                  → killed
                                  → superseded
```

**Tất cả trạng thái hợp lệ:**

| Status        | Ý nghĩa                                              |
|---------------|------------------------------------------------------|
| `queued`      | Vừa enqueue, chưa được nhận                         |
| `accepted`    | Đã accept, chờ worker                               |
| `preparing`   | Đang checkout worktree, setup môi trường            |
| `running`     | Agent đang implement (code + test)                  |
| `verifying`   | Chạy local verification (pytest, ruff, tsc…)        |
| `waiting_ci`  | PR đã push, đang chờ CI checks trên GitHub          |
| `code_review` | Code-reviewer agent đang đánh giá PR diff           |
| `repairing`   | Đang tự sửa lỗi (retry tự động)                    |
| `completed`   | Xong nhưng không merge (policy không cho hoặc skip) |
| `merged`      | PR đã merge vào base branch                         |
| `failed`      | Hết attempts, cần can thiệp thủ công               |
| `rejected`    | Bị từ chối (policy, human review, hoặc thủ công)   |
| `killed`      | Bị dừng thủ công                                   |
| `superseded`  | Bị thay thế bởi card mới hơn                       |

### Source kinds

| Source kind              | Từ đâu                  | CLI add                              |
|--------------------------|-------------------------|--------------------------------------|
| `manual_idea`            | Manual / brainstorm     | `oh autopilot add idea "..."`        |
| `ohmo_request`           | ohmo CLI request        | `oh autopilot add ohmo "..."`        |
| `github_issue`           | GitHub issue            | `oh autopilot add issue "Fix #123"`  |
| `github_pr`              | GitHub PR cần review    | `oh autopilot add pr "Review #456"`  |
| `claude_code_candidate`  | Claude Code candidates  | `oh autopilot add claude "..."`      |

### Commands

```bash
oh autopilot status                        # tổng counts theo status + next card
oh autopilot list [<status>] [--limit N]  # liệt kê cards, filter theo status
oh autopilot add <source> <title> [--body "..."]
oh autopilot context                       # active repo context (synthesized)
oh autopilot journal                       # log recent activity
oh autopilot scan [issues|prs|claude-code|all] [--limit N]
oh autopilot run-next                      # chạy card top priority end-to-end
oh autopilot tick                          # scan + run-next (1 lệnh cho cron)
oh autopilot install-cron                  # cài cron jobs (scan 15min, tick 1h)
oh autopilot export-dashboard              # static kanban → GitHub Pages
```

### Slash commands `/autopilot`

Dùng trong interactive session hoặc script `oh -p`:

```
/autopilot status
/autopilot list [queued|running|…]
/autopilot show <id>
/autopilot next
/autopilot context
/autopilot journal [N]
/autopilot add [idea|ohmo|issue|pr|claude] <title> :: <details>
/autopilot accept <id>
/autopilot start <id>
/autopilot complete <id> [note]
/autopilot fail <id> [note]
/autopilot reject <id> [note]
/autopilot run-next
/autopilot tick
/autopilot install-cron
/autopilot export-dashboard [output-path]
/autopilot scan [issues|prs|claude-code|all] [limit]
```

### Flow autopilot loop (mỗi tick)

```
1. scan — đọc idea/, GitHub issues, PRs, Claude candidates
   └─ enqueue cards với score (priority)
2. pick_next_card — chọn card cao điểm nhất có capacity
3. run-next — chạy với context của card:
   ├─ preparing: checkout worktree mới (isolated git branch)
   ├─ running: agent code + test (permission full_auto)
   ├─ verifying: CI checks local (pytest, ruff, tsc…)
   ├─ push + upsert PR: git push + gh pr create/update
   │   └─ branch sync: rebase onto origin/<base> trước khi push
   ├─ waiting_ci: poll CI status trên GitHub
   ├─ code_review: code-reviewer agent so sánh PR diff vs origin/main
   │   (block_on: ["critical"] — nếu CRITICAL → human gate)
   ├─ automerge: gh pr merge --squash nếu CI pass + review OK
   └─ post-merge sync: pull origin main + rebase in-flight worktrees
4. completed/merged hoặc failed (auto retry → repairing)
5. journal — log mọi state transition
```

### Capacity gate

`max_parallel_runs` trong `autopilot_policy.yaml` giới hạn số card chạy
đồng thời. `run_next` raise `ValueError("Maximum parallel runs reached")`
khi đầy capacity. Cron/tick tự handle: chỉ chạy khi có slot trống.

### Auto-merge policy

Autopilot tự merge khi tất cả điều kiện sau đúng:

1. CI checks pass trên GitHub
2. Remote code review không có `CRITICAL` issue
3. `auto_merge.mode` cho phép

Cấu hình trong `.openharness/autopilot/autopilot_policy.yaml`:

```yaml
execution:
  max_parallel_runs: 2
  max_attempts: 5
  base_branch: main
  use_worktree: true
  pr_branch_sync_strategy: rebase    # rebase | none
  max_branch_sync_attempts: 2
  allow_force_push_pr_branch: false  # true → dùng --force-with-lease

github:
  auto_merge:
    mode: always          # always | label_gated | disabled
    required_label: "autopilot:merge"  # chỉ dùng khi mode: label_gated
  remote_code_review:
    enabled: true
    block_on:
      - critical
    max_turns: 6
    max_diff_chars: 80000
```

Sau khi merge, autopilot tự động:

1. Pull `origin/main` vào local branch
2. Rebase tất cả in-flight worktrees (cards đang `running`/`verifying`) lên
   `origin/main` mới — tránh diverge với commit vừa merge

Nếu pull thất bại (e.g. fast-forward conflict), card vẫn giữ trạng thái
`merged` và journal ghi `kind: merge_warning`.

### Branch sync trước khi push

Trước mỗi lần push PR branch, autopilot:

1. Fetch `origin/<base_branch>` và remote head branch
2. Rebase local head lên `origin/<base_branch>` (strategy: `rebase`)
3. Nếu conflict → card chuyển sang `repairing` với
   `human_gate_pending: true`, journal ghi chi tiết
4. Nếu push bị từ chối (non-fast-forward) → retry sync 1 lần
5. `allow_force_push_pr_branch: true` → dùng `--force-with-lease` (không
   bao giờ plain `--force`)

### Setup cho dự án

```bash
cd ~/projects/my-app

# 1. Set agent models cost-aware
oh model agent set planner       "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set worker        "claude-haiku-4-5,claude-architect"
oh model agent set code-reviewer "claude-sonnet-4-6"

# 2. Install cron
oh autopilot install-cron
# → scan mỗi 15 phút, tick mỗi giờ

# 3. Add backlog
oh autopilot add idea "Add dark mode toggle"
oh autopilot add idea "Refactor payment service"
oh autopilot add issue "Bug: login timeout on Safari"

# 4. Monitor
oh autopilot status
# queued: 3, running: 0, waiting_ci: 0, completed: 0

# 5. Chạy thử 1 card (không đợi cron)
oh autopilot run-next

# 6. Xem journal
oh autopilot journal
```

### Persistence

| File / Dir                                          | Nội dung                            |
|-----------------------------------------------------|-------------------------------------|
| `.openharness/autopilot/registry.json`              | Tất cả cards + state + metadata     |
| `.openharness/autopilot/journal.jsonl`              | Event log (1 JSON/line)             |
| `.openharness/autopilot/context.md`                 | Synthesized repo context            |
| `.openharness/autopilot/autopilot_policy.yaml`      | Execution + GitHub + merge policy   |
| `.openharness/autopilot/verification_policy.yaml`   | Local verification commands         |
| `.openharness/autopilot/runs/`                      | Per-card run + verification reports |

Card schema (ví dụ):

```json
{
  "id": "ap-abc123",
  "status": "queued",
  "score": 85,
  "title": "Add dark mode toggle",
  "body": "Description...",
  "source_kind": "manual_idea",
  "source_ref": null,
  "metadata": {
    "linked_pr_number": null,
    "autopilot_managed": false,
    "attempt_count": 0
  }
}
```

### Pipeline REST API (Web UI)

Web UI expose đầy đủ pipeline qua `/api/pipeline/*`:

| Method  | Path                                        | Mô tả                                    |
|---------|---------------------------------------------|------------------------------------------|
| `GET`   | `/api/pipeline/cards`                       | Tất cả cards                             |
| `POST`  | `/api/pipeline/cards`                       | Enqueue card mới (201)                   |
| `GET`   | `/api/pipeline/cards/{id}`                  | Chi tiết card                            |
| `POST`  | `/api/pipeline/cards/{id}/action`           | `accept` / `reject` / `retry` / `reset` |
| `PATCH` | `/api/pipeline/cards/{id}/model`            | Set/clear execution model                |
| `GET`   | `/api/pipeline/cards/{id}/stream`           | SSE event stream (stream token auth)     |
| `GET`   | `/api/pipeline/cards/{id}/checkpoint`       | Checkpoint info                          |
| `POST`  | `/api/pipeline/cards/{id}/resume`           | Resume từ checkpoint (202)               |
| `DELETE`| `/api/pipeline/cards/{id}/checkpoint`       | Xóa checkpoints                          |
| `GET`   | `/api/pipeline/journal`                     | Journal entries (`?card_id=…`)           |
| `GET`   | `/api/pipeline/policy`                      | Policy YAML + parsed JSON                |
| `PATCH` | `/api/pipeline/policy`                      | Validate & persist policy YAML           |
| `POST`  | `/api/pipeline/run-next`                    | Spawn run-next background task (202)     |

---

## WebUI upgrade status

Các phase P0–P11 đã xong trong codebase hiện tại:

- **P0–P3**: WebUI foundation, history/resume, modes toggle, provider settings, backend REST routes
- **P4–P8**: Pipeline WebUI, agent config, models API, review routes, cron routes, tasks routes
- **P9.10**: Rebase strategy cho in-flight worktrees sau merge
- **P9.11**: Safe PR branch sync trước khi push (rebase + conflict gate)
- **P11.1**: Direct card control từ board (`run`, `pause`, `resume`, `retry-now`)
- **P11.6**: Project API types và client methods cho WebUI
- **P11.9**: Switch project không reload; Web UI reconnect session/WebSocket đúng cách
- **P11.10**: Card có linked PR đã merge được short-circuit sang `merged`, không rơi vào `failed/no_changes`
- **P11.11**: Integration tests cho multi-project flow
- **P11.12**: Multi-project documentation và snapshot docs cập nhật

Backlog tiếp theo là UI polish, QA, dashboard export, và packaging.

Xem `GUIDE.md` section 12b để biết danh sách REST API/WebSocket routes đầy đủ.

---

## So sánh nhanh

| Tiêu chí           | `full_auto` mode       | `oh autopilot`            |
| ------------------- | ----------------------- | ------------------------- |
| Phạm vi            | 1 prompt, 1 session     | Nhiều tasks, liên tục    |
| Cần prompt         | Có (user viết)         | Không (auto từ sources)  |
| State persist       | Không                   | Có (registry, journal)   |
| Cron tích hợp     | Không                   | Có (`install-cron`)      |
| PR/CI flow          | Phải prompt thủ công   | Built-in lifecycle        |
| Worktree isolation  | Phải tự enter           | Tự checkout mỗi card     |
| Parallel cards      | Không                   | Có (`max_parallel_runs`) |
| Use case            | One-shot task           | Backlog burn-down 24/7    |

---

## Gợi ý kết hợp cả 2

```bash
# Autopilot queue xử lý backlog hàng ngày
oh autopilot install-cron

# Khi cần task khẩn cấp, bypass queue:
oh -p "URGENT: fix production crash in auth.py" \
   --permission-mode full_auto \
   --max-turns 30

# Sau đó add vào autopilot để track:
oh autopilot add idea "Post-mortem: auth crash root cause analysis"
```

---

## Permission modes tham khảo

| Mode                                 | Hành vi                           |
| ------------------------------------ | ---------------------------------- |
| `default`                          | Hỏi user trước write/bash/spawn  |
| `plan`                             | Block mọi write ops (read-only)   |
| `full_auto`                        | Allow all tools automatically      |
| `--dangerously-skip-permissions`   | = `full_auto` (alias)             |
| `--allowed-tools "bash,file_edit"` | Chỉ auto-approve tools liệt kê   |
| `--disallowed-tools "web_fetch"`   | Block tools cụ thể               |

---

## Agent model mapping cho autopilot

Autopilot chạy nhiều turn → cost matters. Gợi ý:

```bash
# Heavy thinkers: planning phase
oh model agent set planner          "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set architect        "claude-opus-4-7,claude-sonnet-4-6"

# Balanced: review + testing
oh model agent set code-reviewer    "claude-sonnet-4-6"
oh model agent set tdd-guide        "claude-sonnet-4-6"
oh model agent set security-reviewer "claude-opus-4-7,claude-sonnet-4-6"

# Cost-efficient: high-frequency workers
oh model agent set worker           "claude-haiku-4-5,claude-architect"
oh model agent set Explore          "claude-haiku-4-5"

# Fallback chain đảm bảo: nếu Opus rate-limited → tự rớt về Sonnet
```

---

**Liên quan:** Xem `GUIDE.md` cho install, bridge config, per-agent model mapping, và REST API chi tiết.
