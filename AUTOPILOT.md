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
> /permission full_auto
```

### Flow end-to-end (1 prompt → done)

```
1. Bridge load ~/.claude/settings.json → resolve model + auth
2. Agent đọc prompt, vào loop:
   ├─ Plan → spawn sub-agents (planner/tdd-guide/worker) qua agent_tool
   ├─ Mỗi sub-agent dùng model theo agent_models[name] chain
   └─ Tools (file_edit/bash/grep) chạy không hỏi xác nhận
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
oh -p "Fix the null pointer in src/auth.ts line 42, run tests to verify" \
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
    → pr_open → waiting_ci → completed → merged
                                       → failed → repairing (auto retry)
                                       → rejected / superseded
```

### Commands

```bash
oh autopilot status          # tổng counts theo status
oh autopilot list            # liệt kê tất cả cards
oh autopilot list queued     # filter theo status
oh autopilot add <source> <title> [--body "..."]
                             # source: idea, issue, pr, claude
oh autopilot context         # active repo context (synthesized)
oh autopilot journal         # log recent activity
oh autopilot scan            # scan intake sources → enqueue
oh autopilot run-next        # chạy card top priority end-to-end
oh autopilot tick            # scan + run-next (1 lệnh cho cron)
oh autopilot install-cron    # cài cron jobs (scan 15min, tick 1h)
oh autopilot export-dashboard  # static kanban → GitHub Pages
```

### Flow autopilot loop (mỗi tick)

```
1. scan — đọc idea/, GitHub issues, PRs, Claude candidates
   └─ enqueue cards với score (priority)
2. pick_next_card — chọn card cao điểm nhất
3. run-next — chạy oh -p với context của card:
   ├─ preparing: checkout worktree mới
   ├─ running: agent code + test (permission full_auto)
   ├─ verifying: CI checks local
   ├─ pr_open: gh pr create
   ├─ waiting_ci: poll CI status
   └─ completed/merged hoặc failed (auto retry → repairing)
4. journal — log mọi state transition
```

### Setup cho dự án

```bash
cd ~/projects/my-app

# 1. Set agent models cost-aware
oh model agent set planner       "claude-opus-4-7,claude-sonnet-4-6"
oh model agent set worker        "claude-haiku-4-5,claude-architect-backup"
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
# queued: 3, running: 0, pr_open: 0, completed: 0

# 5. Chạy thử 1 card (không đợi cron)
oh autopilot run-next

# 6. Xem journal
oh autopilot journal
```

### Source kinds

| Source     | Từ đâu              | Lệnh add                                |
| ---------- | ---------------------- | ---------------------------------------- |
| `idea`   | Manual / brainstorm    | `oh autopilot add idea "..."`          |
| `issue`  | GitHub issue           | `oh autopilot add issue "Fix #123"`    |
| `pr`     | GitHub PR cần review  | `oh autopilot add pr "Review PR #456"` |
| `claude` | Claude Code candidates | `oh autopilot add claude "..."`        |

### Persistence

- **Registry:** `<repo>/.oh/autopilot/registry.json` — tất cả cards + state
- **Journal:** `<repo>/.oh/autopilot/journal.jsonl` — event log (1 JSON/line)
- **Context:** `<repo>/.oh/autopilot/context.md` — synthesized repo context

Card schema (synthetic example):

```json
{
  "id": "card-001",
  "status": "queued",
  "score": 85,
  "title": "Add dark mode toggle",
  "body": "Description...",
  "source_kind": "manual_idea",
  "source_ref": null
}
```

---

## So sánh nhanh

| Tiêu chí         | `full_auto` mode      | `oh autopilot`          |
| ------------------ | ----------------------- | ------------------------- |
| Phạm vi           | 1 prompt, 1 session     | Nhiều tasks, liên tục  |
| Cần prompt        | Có (user viết)        | Không (auto từ sources) |
| State persist      | Không                  | Có (registry, journal)   |
| Cron tích hợp    | Không                  | Có (`install-cron`)    |
| PR/CI flow         | Phải prompt thủ công | Built-in lifecycle        |
| Worktree isolation | Phải tự enter         | Tự checkout mỗi card    |
| Use case           | One-shot task           | Backlog burn-down 24/7    |

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
| `default`                          | Hỏi user trước write/bash/spawn |
| `plan`                             | Block mọi write ops (read-only)   |
| `full_auto`                        | Allow all tools automatically      |
| `--dangerously-skip-permissions`   | =`full_auto` (alias)             |
| `--allowed-tools "bash,file_edit"` | Chỉ auto-approve tools liệt kê  |
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
oh model agent set worker           "claude-haiku-4-5,claude-architect-backup"
oh model agent set Explore          "claude-haiku-4-5"

# Fallback chain đảm bảo: nếu Opus rate-limited → tự rớt về Sonnet
```

---

**Liên quan:** Xem `GUIDE.md` cho install, bridge config, per-agent model mapping chi tiết.
