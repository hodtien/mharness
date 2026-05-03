export interface TaskCard {
  id: string;
  title: string;
  body?: string;
  status: string;
  score: number;
  score_reasons?: string[];
  source_kind?: string;
  source_ref?: string;
  labels?: string[];
  updated_at?: number;
  metadata?: {
    last_note?: string;
    last_ci_summary?: string;
    last_failure_summary?: string;
    human_gate_pending?: boolean;
    verification_steps?: { status: string; command: string }[];
    attempt_count?: number;
    max_attempts?: number;
    linked_pr_number?: number | null;
    linked_pr_url?: string;
    head_branch?: string;
  };
}

export interface JournalEntry {
  timestamp: number;
  kind: string;
  task_id?: string;
  summary: string;
}

export interface Snapshot {
  generated_at: number;
  repo_name: string;
  focus?: TaskCard;
  counts: Record<string, number>;
  status_order: string[];
  columns: Record<string, TaskCard[]>;
  cards: TaskCard[];
  journal: JournalEntry[];
}

export const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  accepted: "Accepted",
  preparing: "Preparing",
  running: "Running",
  verifying: "Verifying",
  pr_open: "PR Open",
  waiting_ci: "Waiting CI",
  code_review: "Code Review",
  repairing: "Repairing",
  completed: "Completed",
  merged: "Merged",
  failed: "Failed",
  rejected: "Rejected",
  killed: "Killed",
  superseded: "Superseded",
};

export const STATUS_COLORS: Record<string, string> = {
  queued: "#64748b",
  accepted: "#8b5cf6",
  preparing: "#0f766e",
  running: "#00d4aa",
  verifying: "#3b82f6",
  pr_open: "#3b82f6",
  waiting_ci: "#3b82f6",
  code_review: "#a855f7",
  repairing: "#ff6b35",
  completed: "#00d4aa",
  merged: "#00d4aa",
  failed: "#ff4444",
  rejected: "#ff4444",
  killed: "#ff4444",
  superseded: "#ffaa00",
};

/**
 * Active statuses — board auto-refreshes faster when any card sits here.
 * Maps directly to the "is the autopilot doing work right now?" question.
 */
export const ACTIVE_STATUSES: ReadonlySet<string> = new Set([
  "preparing",
  "running",
  "verifying",
  "repairing",
  "waiting_ci",
  "pr_open",
  "code_review",
]);

/** Lifecycle kanban columns — one column per real autopilot phase. */
export interface KanbanGroup {
  key: string;
  label: string;
  color: string;
  statuses: string[];
}

export const KANBAN_GROUPS: KanbanGroup[] = [
  {
    key: "queue",
    label: "Queue",
    color: "#64748b",
    statuses: ["queued", "accepted"],
  },
  {
    key: "running",
    label: "Running",
    color: "#00d4aa",
    statuses: ["preparing", "running", "verifying"],
  },
  {
    key: "repairing",
    label: "Repairing",
    color: "#ff6b35",
    statuses: ["repairing"],
  },
  {
    key: "waiting_ci",
    label: "Waiting CI",
    color: "#3b82f6",
    statuses: ["waiting_ci", "pr_open"],
  },
  {
    key: "review",
    label: "Review",
    color: "#a855f7",
    statuses: ["code_review"],
  },
  {
    key: "merged",
    label: "Merged",
    color: "#00d4aa",
    statuses: ["merged", "completed"],
  },
  {
    key: "failed",
    label: "Failed / Rejected",
    color: "#ff4444",
    statuses: ["failed", "rejected", "killed", "superseded"],
  },
];
