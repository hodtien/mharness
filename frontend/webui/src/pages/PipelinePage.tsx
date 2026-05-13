import React, { useEffect, useState, useCallback, useMemo, useRef, type ChangeEvent, type FormEvent } from "react";
import { api, apiFetch, apiRequest, getToken, refreshAuthSession } from "../api/client";
import { useSession } from "../store/session";
import {
  LOG_FILTERS,
  type LogFilter,
  type LogStep,
  type StreamEvent,
  eventsToLogSteps,
  filterLogSteps,
  getSelectedLogStep,
} from "./PipelineLogModel";
import PageHeader from "../components/PageHeader";

// ─── Types ────────────────────────────────────────────────────────────────────

export type RepoTaskStatus =
  | "queued"
  | "accepted"
  | "preparing"
  | "running"
  | "verifying"
  | "repairing"
  | "pending"
  | "pr_open"
  | "waiting_ci"
  | "completed"
  | "merged"
  | "failed"
  | "rejected"
  | "killed"
  | "superseded"
  | "paused";

export type RepoTaskSource =
  | "github_issue"
  | "github_pr"
  | "manual_idea"
  | "ohmo_request"
  | "claude_code_candidate";

export interface PipelineCardMetadata {
  last_note?: string | null;
  linked_pr_url?: string | null;
  resume_available?: boolean;
  resume_phase?: string | null;
  pending_reason?: string | null;
  next_retry_at?: number | null;
}

export interface PipelineCard {
  id: string;
  title: string;
  body?: string;
  status: RepoTaskStatus;
  source_kind: RepoTaskSource;
  score: number;
  labels: string[];
  created_at: number;
  updated_at: number;
  model?: string | null;
  attempt_count?: number;
  metadata?: PipelineCardMetadata;
}

export interface JournalEntry {
  timestamp: number;
  kind: string;
  summary: string;
  task_id: string | null;
  metadata: Record<string, unknown>;
}

// ─── New Idea Modal ────────────────────────────────────────────────────────────

interface NewIdeaModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

function NewIdeaModal({ onClose, onSuccess }: NewIdeaModalProps) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [labelsRaw, setLabelsRaw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setError(null);
    setSubmitting(true);
    try {
      const labels = labelsRaw
        ? labelsRaw.split(",").map((l) => l.trim()).filter(Boolean)
        : undefined;
      await apiFetch<PipelineCard>("/api/pipeline/cards", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), body: body.trim() || undefined, labels }),
        headers: { "Content-Type": "application/json" },
      });
      onSuccess();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label="New idea"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-[var(--text)]">New idea</h2>
          <button
            onClick={onClose}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-1.5 text-sm text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="idea-title" className="mb-1 block text-xs font-medium text-[var(--text-dim)]">
              Title <span className="text-red-400">*</span>
            </label>
            <input
              id="idea-title"
              ref={titleRef}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What needs to be done?"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] placeholder-[var(--text-dim)]/50 focus:border-[var(--accent)]/60 focus:outline-none"
              required
            />
          </div>
          <div>
            <label htmlFor="idea-body" className="mb-1 block text-xs font-medium text-[var(--text-dim)]">
              Body
            </label>
            <textarea
              id="idea-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Optional details…"
              rows={4}
              className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] placeholder-[var(--text-dim)]/50 focus:border-[var(--accent)]/60 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="idea-labels" className="mb-1 block text-xs font-medium text-[var(--text-dim)]">
              Labels <span className="text-[var(--text-dim)]/60">(comma-separated)</span>
            </label>
            <input
              id="idea-labels"
              type="text"
              value={labelsRaw}
              onChange={(e) => setLabelsRaw(e.target.value)}
              placeholder="frontend, bug, enhancement"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] placeholder-[var(--text-dim)]/50 focus:border-[var(--accent)]/60 focus:outline-none"
            />
          </div>
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
              {error}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] transition hover:border-[var(--accent)]/40"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || submitting}
              className="rounded-lg border border-emerald-500/40 bg-emerald-500/20 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/30 disabled:opacity-40"
            >
              {submitting ? "Submitting…" : "Submit"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

// ─── Policy Tab ────────────────────────────────────────────────────────────────

interface PolicyTabProps {
  onSaved: () => void;
}

function PolicyTab({ onSaved }: PolicyTabProps) {
  const [yamlContent, setYamlContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const yamlError = useMemo(() => {
    const lines = yamlContent.split("\n");
    let currentIndent = 0;
    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      if (!line.trim() || line.trimStart().startsWith("#")) continue;
      const indent = line.match(/^\s*/)?.[0].length ?? 0;
      if (indent % 2 !== 0) return `YAML error on line ${i + 1}: indentation must use 2-space increments.`;
      if (indent > currentIndent + 2) return `YAML error on line ${i + 1}: unexpected indentation.`;
      currentIndent = indent;
      if (!line.includes(":")) return `YAML error on line ${i + 1}: expected key-value pair.`;
    }
    return null;
  }, [yamlContent]);

  useEffect(() => {
    apiFetch<{ yaml_content: string; parsed: unknown }>("/api/pipeline/policy")
      .then((data) => {
        setYamlContent(data.yaml_content);
      })
      .catch((err) => setLoadError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  const highlightedPreview = useMemo(() => {
    return yamlContent.split("\n").map((line, idx) => {
      const commentIdx = line.indexOf("#");
      const comment = commentIdx >= 0 ? line.slice(commentIdx) : "";
      const code = commentIdx >= 0 ? line.slice(0, commentIdx) : line;
      const colonIdx = code.indexOf(":");
      const key = colonIdx >= 0 ? code.slice(0, colonIdx + 1) : code;
      const value = colonIdx >= 0 ? code.slice(colonIdx + 1) : "";
      return (
        <div key={idx} className="whitespace-pre-wrap break-words">
          <span className="text-[var(--text)]">{key}</span>
          <span className="text-amber-300">{value}</span>
          {comment && <span className="text-emerald-400">{comment}</span>}
        </div>
      );
    });
  }, [yamlContent]);

  const handleSave = async () => {
    setSaveError(null);
    setSaving(true);
    setSaved(false);
    try {
      const res = await apiRequest("/api/pipeline/policy", {
        method: "PATCH",
        body: JSON.stringify({ yaml_content: yamlContent }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        let msg = `${res.status} ${res.statusText}`;
        if (body.message) msg = body.message;
        if (body.missing) msg = `Missing required keys: ${body.missing.join(", ")}`;
        throw new Error(msg);
      }
      setSaved(true);
      onSaved();
    } catch (err) {
      setSaveError(String(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="text-sm text-[var(--text-dim)]">Loading policy…</span>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {loadError}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-[var(--text-dim)]">
          Edit <code className="rounded bg-[var(--panel-2)] px-1 py-0.5">.openharness/autopilot/autopilot_policy.yaml</code>
        </p>
        <div className="flex items-center gap-3">
          {saved && <span className="text-xs text-emerald-400">Saved ✓</span>}
          <button
            onClick={handleSave}
            disabled={saving || Boolean(yamlError)}
            className="rounded-lg border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-4 py-1.5 text-sm font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/30 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      <div className="grid flex-1 gap-3 lg:grid-cols-2">
        <textarea
          value={yamlContent}
          onChange={(e) => {
            setYamlContent(e.target.value);
            setSaved(false);
          }}
          className="min-h-80 resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-4 font-mono text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          spellCheck={false}
          aria-label="Autopilot policy YAML editor"
        />
        <div className="min-h-80 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-4 font-mono text-sm leading-6 text-[var(--text)]">
          <div className="mb-2 text-xs uppercase tracking-wide text-[var(--text-dim)]">Preview</div>
          {highlightedPreview}
        </div>
      </div>
      {yamlError && (
        <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {yamlError}
        </div>
      )}
      {saveError && (
        <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {saveError}
        </div>
      )}
    </div>
  );
}

// ─── Status constants ──────────────────────────────────────────────────────────

const ACTIVE_STATUSES: RepoTaskStatus[] = [
  "running",
  "preparing",
  "verifying",
  "repairing",
  "pr_open",
  "waiting_ci",
];

/** Statuses that represent a terminal outcome. */
export const TERMINAL_STATUSES: RepoTaskStatus[] = [
  "completed",
  "merged",
  "failed",
  "rejected",
  "killed",
  "superseded",
  "paused",
];

/** Statuses that operators need to act on immediately. */
export const ATTENTION_STATUSES: RepoTaskStatus[] = ["failed", "paused"];

/** Statuses representing waiting for external signal. */
export const WAITING_STATUSES: RepoTaskStatus[] = ["waiting_ci", "pr_open"];

export type BoardFilter = "all" | "active" | "attention" | "waiting" | "terminal";

export const BOARD_FILTERS: { id: BoardFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "active", label: "Active" },
  { id: "attention", label: "Needs attention" },
  { id: "waiting", label: "Waiting" },
  { id: "terminal", label: "Terminal" },
];

export function matchesBoardFilter(status: RepoTaskStatus, filter: BoardFilter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return ACTIVE_STATUSES.includes(status) || status === "queued" || status === "accepted" || status === "pending";
  if (filter === "attention") return ATTENTION_STATUSES.includes(status);
  if (filter === "waiting") return WAITING_STATUSES.includes(status);
  if (filter === "terminal") return TERMINAL_STATUSES.includes(status);
  return false;
}

function hasActiveCard(cards: PipelineCard[]): boolean {
  return cards.some((c) => ACTIVE_STATUSES.includes(c.status));
}

function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function formatRelativeTime(timestamp: number | null | undefined): string {
  if (!timestamp) return "—";
  const seconds = Math.max(0, Math.floor(timestamp - Date.now() / 1000));
  if (seconds < 60) return `in ${seconds}s`;
  if (seconds < 3600) return `in ${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `in ${Math.floor(seconds / 3600)}h`;
  return `in ${Math.floor(seconds / 86400)}d`;
}

// ─── Kanban columns ────────────────────────────────────────────────────────────

interface ColumnDef {
  id: string;
  label: string;
  statuses: RepoTaskStatus[];
  badgeColor: string;
  pulseWhenActive?: boolean;
}

const COLUMNS: ColumnDef[] = [
  {
    id: "queue",
    label: "Queue",
    statuses: ["queued", "accepted"],
    badgeColor: "bg-[var(--status-queue-bg)] text-[var(--status-queue-text)] border-[var(--status-queue-border)]",
  },
  {
    id: "pending",
    label: "Pending",
    statuses: ["pending"],
    badgeColor: "bg-[var(--status-pending-bg)] text-[var(--status-pending-text)] border-[var(--status-pending-border)]",
  },
  {
    id: "in_progress",
    label: "In Progress",
    statuses: ["preparing", "running", "verifying", "repairing"],
    badgeColor: "bg-[var(--status-running-bg)] text-[var(--status-running-text)] border-[var(--status-running-border)]",
    pulseWhenActive: true,
  },
  {
    id: "review",
    label: "Review",
    statuses: ["pr_open", "waiting_ci"],
    badgeColor: "bg-[var(--status-review-bg)] text-[var(--status-review-text)] border-[var(--status-review-border)]",
  },
  {
    id: "completed",
    label: "Completed",
    statuses: ["completed", "merged"],
    badgeColor: "bg-[var(--status-done-bg)] text-[var(--status-done-text)] border-[var(--status-done-border)]",
  },
  {
    id: "failed",
    label: "Failed",
    statuses: ["failed"],
    badgeColor: "bg-[var(--status-failed-bg)] text-[var(--status-failed-text)] border-[var(--status-failed-border)]",
  },
  {
    id: "rejected",
    label: "Rejected",
    statuses: ["rejected", "killed", "paused", "superseded"],
    badgeColor: "bg-[var(--status-rejected-bg)] text-[var(--status-rejected-text)] border-[var(--status-rejected-border)]",
  },
];

const SOURCE_LABELS: Record<RepoTaskSource, string> = {
  github_issue: "Issue",
  github_pr: "PR",
  manual_idea: "Idea",
  ohmo_request: "OHMO",
  claude_code_candidate: "Candidate",
};

const SOURCE_COLOR: Record<RepoTaskSource, string> = {
  github_issue: "bg-[var(--status-review-bg)] text-[var(--status-review-text)] border-[var(--status-review-border)]",
  github_pr: "bg-[var(--status-queue-bg)] text-[var(--status-queue-text)] border-[var(--status-queue-border)]",
  manual_idea: "bg-[var(--status-done-bg)] text-[var(--status-done-text)] border-[var(--status-done-border)]",
  ohmo_request: "bg-[var(--status-pending-bg)] text-[var(--status-pending-text)] border-[var(--status-pending-border)]",
  claude_code_candidate: "bg-[var(--status-running-bg)] text-[var(--status-running-text)] border-[var(--status-running-border)]",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function relativeAge(timestamp: number): string {
  const diff = Date.now() / 1000 - timestamp;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return `${Math.floor(diff / 604800)}w ago`;
}

function formatTimestamp(timestamp: number): string {
  const d = new Date(timestamp * 1000);
  const h = d.getHours().toString().padStart(2, "0");
  const m = d.getMinutes().toString().padStart(2, "0");
  return `${h}:${m}`;
}

function buildActivityGroups(entries: JournalEntry[]): JournalEntry[][] {
  const sorted = [...entries].sort((a, b) => b.timestamp - a.timestamp);
  const groups: JournalEntry[][] = [];
  for (const entry of sorted) {
    const last = groups[groups.length - 1];
    if (last && last[last.length - 1].kind === entry.kind) {
      last.push(entry);
    } else {
      groups.push([entry]);
    }
  }
  return groups;
}

// ─── Card ─────────────────────────────────────────────────────────────────────

function Card({ card, onClick }: { card: PipelineCard; onClick: () => void }) {
  const sourceLabel = SOURCE_LABELS[card.source_kind] ?? card.source_kind;
  const sourceColor = SOURCE_COLOR[card.source_kind] ?? "bg-gray-500/20 text-gray-300 border-gray-500/40";
  const pendingReason = card.status === "pending" ? card.metadata?.pending_reason : null;
  const nextRetryAt = card.status === "pending" ? card.metadata?.next_retry_at : null;
  const isActive = ACTIVE_STATUSES.includes(card.status);
  const isCompleted = card.status === "completed" || card.status === "merged";

  // Status badge colors
  const statusBadgeMap: Record<string, string> = {
    queued: "bg-[var(--status-queue-bg)] text-[var(--status-queue-text)]",
    accepted: "bg-[var(--status-queue-bg)] text-[var(--status-queue-text)]",
    pending: "bg-[var(--status-pending-bg)] text-[var(--status-pending-text)]",
    preparing: "bg-[var(--status-running-bg)] text-[var(--status-running-text)]",
    running: "bg-[var(--status-running-bg)] text-[var(--status-running-text)]",
    verifying: "bg-[var(--status-review-bg)] text-[var(--status-review-text)]",
    repairing: "bg-red-500/20 text-red-300",
    pr_open: "bg-[var(--status-review-bg)] text-[var(--status-review-text)]",
    waiting_ci: "bg-[var(--status-review-bg)] text-[var(--status-review-text)]",
    completed: "bg-[var(--status-done-bg)] text-[var(--status-done-text)]",
    merged: "bg-[var(--status-done-bg)] text-[var(--status-done-text)]",
    failed: "bg-[var(--status-failed-bg)] text-[var(--status-failed-text)]",
    rejected: "bg-[var(--status-rejected-bg)] text-[var(--status-rejected-text)]",
    killed: "bg-[var(--status-rejected-bg)] text-[var(--status-rejected-text)]",
    superseded: "bg-[var(--status-rejected-bg)] text-[var(--status-rejected-text)]",
    paused: "bg-[var(--status-rejected-bg)] text-[var(--status-rejected-text)]",
  };
  const statusBadge = statusBadgeMap[card.status] ?? "bg-gray-500/20 text-gray-300";

  return (
    <button
      onClick={onClick}
      className={`w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-4 text-left text-sm shadow-sm transition hover:border-[var(--accent)]/40 hover:bg-[var(--panel)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
        isCompleted ? "opacity-70 hover:opacity-100" : ""
      }${isActive ? "border-l-2 border-l-[var(--status-running-border)]" : ""}`}
    >
      {/* Title with hierarchy */}
      <div className="mb-3 text-sm font-medium leading-relaxed text-[var(--text)] line-clamp-2">{card.title}</div>

      {/* Pending info */}
      {card.status === "pending" && (
        <div className="mb-3 rounded-md border border-[var(--status-pending-border)] bg-[var(--status-pending-bg)] px-2.5 py-1.5 text-[11px] text-[var(--status-pending-text)]">
          <div className="font-medium">Pending</div>
          {pendingReason && <div className="mt-0.5 break-words opacity-90">{pendingReason}</div>}
          {nextRetryAt && <div className="mt-0.5 opacity-80">Next retry {formatRelativeTime(nextRetryAt)}</div>}
        </div>
      )}

      {/* Metadata row: badges + age/score */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Status badge */}
          <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${statusBadge}`}>
            {card.status}
          </span>
          {/* Source badge */}
          <span
            className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${sourceColor}`}
          >
            {sourceLabel}
          </span>
          {/* Model badge if available */}
          {card.model && (
            <span className="shrink-0 rounded border border-[var(--border)] bg-[var(--panel)] px-1.5 py-0.5 text-[9px] text-[var(--text-dim)]">
              {card.model.split("/").pop()?.slice(0, 12)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isActive && (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-label="Active" />
          )}
          <span className="text-[11px] font-mono text-[var(--text-dim)]">{card.score}</span>
          <span className="text-[11px] text-[var(--text-dim)]">{relativeAge(card.created_at)}</span>
        </div>
      </div>
    </button>
  );
}

// ─── Kind → icon map ───────────────────────────────────────────────────────────

const KIND_ICONS: Record<string, string> = {
  // Status-based icons per task spec
  repairing: "🔴",
  verifying: "🔵",
  merged: "✅",
  failed: "⚠️",
  preparing: "🟡",
  // Event-based icons
  merge_warning: "⚠️",
  code_review: "🔍",
  ci_check: "✅",
  ci_failure: "❌",
  intake_added: "📥",
  intake_refresh: "🔄",
  status_change: "🔄",
  pr_opened: "🔀",
  pr_merged: "🔀",
  pr_closed: "🔚",
  agent_started: "🤖",
  agent_finished: "🤖",
  error: "❗",
  info: "ℹ️",
};

function kindIcon(kind: string): string {
  return KIND_ICONS[kind] ?? "📌";
}

// ─── TruncatedText ─────────────────────────────────────────────────────────────

const TRUNCATE_LIMIT = 120;

function TruncatedText({ text }: { text: string }) {
  const [expanded, setExpanded] = React.useState(false);
  if (text.length <= TRUNCATE_LIMIT) {
    return <span>{text}</span>;
  }
  if (expanded) {
    return (
      <span>
        {text}{" "}
        <button
          onClick={() => setExpanded(false)}
          className="ml-1 text-[var(--accent)] underline-offset-2 hover:underline"
        >
          Show less
        </button>
      </span>
    );
  }
  return (
    <span>
      {text.slice(0, TRUNCATE_LIMIT)}…{" "}
      <button
        onClick={() => setExpanded(true)}
        className="ml-1 text-[var(--accent)] underline-offset-2 hover:underline"
      >
        Show more
      </button>
    </span>
  );
}

// ─── Activity Tab ──────────────────────────────────────────────────────────────

interface ActivityEntryGroupProps {
  entries: JournalEntry[];
}

function ActivityEntryGroup({ entries }: ActivityEntryGroupProps) {
  const collapsed = entries.length > 3;
  const [expanded, setExpanded] = useState(!collapsed);
  const timestamp = formatTimestamp(entries[0].timestamp);
  const kind = entries[0].kind;
  const count = entries.length;

  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--panel-2)]" data-testid="activity-entry-group">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-[var(--panel)]"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="shrink-0 font-mono text-[var(--text-dim)]">
          {expanded ? "▼" : "▶"}
        </span>
        <span className="font-mono text-[var(--text-dim)]">
          [{timestamp}] {kind} ({count})
        </span>
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-[var(--border)] p-3">
          {entries.map((entry, entryIdx) => (
            <div key={entryIdx} className="flex gap-3 text-sm" data-testid="activity-item">
              <span className="shrink-0 mt-0.5 text-base" data-testid="activity-item-icon">
                {kindIcon(entry.kind)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <TruncatedText text={entry.summary} />
                  <span className="shrink-0 text-[10px] text-[var(--text-dim)]">
                    {relativeAge(entry.timestamp)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export type ActivityFilter = "all" | "failures" | "ci" | "agent" | "git";

export const ACTIVITY_FILTERS: { id: ActivityFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "failures", label: "Failures" },
  { id: "ci", label: "CI" },
  { id: "agent", label: "Agent" },
  { id: "git", label: "Git" },
];

export function matchesActivityFilter(kind: string, filter: ActivityFilter): boolean {
  if (filter === "all") return true;
  if (filter === "failures") return /fail|error|repairing/.test(kind);
  if (filter === "ci") return kind.startsWith("ci_");
  if (filter === "agent") return kind.startsWith("agent_");
  if (filter === "git") return /^(pr_|merge_)/.test(kind);
  return false;
}

interface ActivityTabProps {
  cardId: string;
  isActive: boolean;
}

function ActivityTab({ cardId, isActive }: ActivityTabProps) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<ActivityFilter>("all");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchEntries = useCallback(async () => {
    try {
      const data = await apiFetch<{ entries: JournalEntry[] }>(
        `/api/pipeline/journal?card_id=${encodeURIComponent(cardId)}&limit=20`,
      );
      setEntries(data.entries);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [cardId]);

  useEffect(() => {
    setLoading(true);
    setEntries([]);
    fetchEntries();
  }, [fetchEntries]);

  // Auto-refresh every 10 s while this tab is visible
  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (isActive) {
      timerRef.current = setInterval(fetchEntries, 10_000);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isActive, fetchEntries]);

  const filteredEntries = entries.filter((e) => matchesActivityFilter(e.kind, activeFilter));
  const groupedEntries = useMemo(() => buildActivityGroups(filteredEntries), [filteredEntries]);

  if (loading) {
    return (
      <div className="p-4 text-sm text-[var(--text-dim)]">Loading activity…</div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-sm text-red-300">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col min-h-0">
      {/* Filter pills */}
      <div className="flex gap-1.5 flex-wrap border-b border-[var(--border)] px-4 py-2" data-testid="activity-filter-pills">
        {ACTIVITY_FILTERS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setActiveFilter(id)}
            aria-pressed={activeFilter === id}
            className={`rounded-full border px-3 py-0.5 text-xs font-medium transition ${
              activeFilter === id
                ? "border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]"
                : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:text-[var(--text)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Entry list */}
      {filteredEntries.length === 0 ? (
        <div className="shrink-0 p-4 text-sm text-[var(--text-dim)]">
          {entries.length === 0 ? "No activity yet." : "No entries match this filter."}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 min-h-0">
          <div className="space-y-2">
            {groupedEntries.map((group, idx) => (
              <ActivityEntryGroup key={idx} entries={group} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Logs Tab ─────────────────────────────────────────────────────────────────

interface LogsTabProps {
  cardId: string;
  isActive: boolean;
}

const _SSE_BACKOFF_INITIAL_MS = 1_000;
const _SSE_BACKOFF_MAX_MS = 30_000;
const _SSE_MAX_RETRIES = 6;

function LogsTab({ cardId, isActive }: LogsTabProps) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [streamState, setStreamState] = useState<"connecting" | "open" | "closed">("connecting");
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<LogFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef<boolean>(true);
  // Track how many events we've successfully received for the `after=` resume param.
  const seenCountRef = useRef<number>(0);

  useEffect(() => {
    if (!isActive) return;
    setEvents([]);
    setError(null);
    setStreamState("connecting");
    seenCountRef.current = 0;

    let attempt = 0;
    let refreshedAuth = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      getToken();
      const after = seenCountRef.current;
      const url = `/api/pipeline/cards/${encodeURIComponent(cardId)}/stream?after=${after}`;
      const es = new EventSource(url);
      sourceRef.current = es;

      es.onopen = () => {
        attempt = 0;
        setStreamState("open");
      };

      es.onerror = () => {
        es.close();
        sourceRef.current = null;
        if (cancelled) return;
        if (!refreshedAuth) {
          refreshedAuth = true;
          void refreshAuthSession().then((refreshed) => {
            if (!refreshed || cancelled) return;
            setStreamState("connecting");
            connect();
          });
          return;
        }
        attempt += 1;
        if (attempt > _SSE_MAX_RETRIES) {
          setStreamState("closed");
          setError("Stream disconnected after multiple retries.");
          return;
        }
        const delay = Math.min(_SSE_BACKOFF_INITIAL_MS * 2 ** (attempt - 1), _SSE_BACKOFF_MAX_MS);
        setStreamState("connecting");
        retryTimer = setTimeout(connect, delay);
      };

      es.onmessage = (ev) => {
        if (paused) return;
        const index = seenCountRef.current;
        seenCountRef.current += 1;
        try {
          const data = JSON.parse(ev.data) as StreamEvent;
          setEvents((prev) => [...prev, { ...data, index }]);
        } catch {
          setError("Received malformed stream event.");
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      sourceRef.current?.close();
      sourceRef.current = null;
      setStreamState("closed");
    };
  }, [cardId, isActive]);

  useEffect(() => {
    const node = scrollerRef.current;
    if (!node) return;
    // Newest-first: keep user at top when near top
    if (stickRef.current) {
      node.scrollTop = 0;
    }
  }, [events]);

  const onScroll = useCallback(() => {
    const node = scrollerRef.current;
    if (!node) return;
    stickRef.current = node.scrollTop < 40;
  }, []);

  const steps = useMemo(() => eventsToLogSteps(events), [events]);
  const normalizedQuery = query.trim().toLowerCase();
  const visibleSteps = useMemo(
    () => filterLogSteps(steps, activeFilter, normalizedQuery),
    [steps, activeFilter, normalizedQuery],
  );
  const selectedStep = getSelectedLogStep(visibleSteps, selectedStepId);

  useEffect(() => {
    if (!selectedStep && visibleSteps.length > 0) {
      setSelectedStepId(visibleSteps[0]?.id ?? null);
    }
  }, [selectedStep, visibleSteps]);

  const pauseButton = (
    <button
      type="button"
      onClick={() => setPaused((v) => !v)}
      className="rounded border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 text-[10px] text-[var(--text-dim)] hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
      title={paused ? "Resume stream" : "Pause stream"}
    >
      {paused ? "▶ Resume" : "⏸ Pause"}
    </button>
  );

  const badge = streamState === "open" ? (
    <span className="text-emerald-300">● live</span>
  ) : streamState === "connecting" ? (
    <span className="text-amber-300">● connecting…</span>
  ) : (
    <span className="text-[var(--text-dim)]">○ ended</span>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b border-[var(--border)] px-4 py-3 text-[11px]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="font-mono uppercase tracking-wider text-[var(--text-dim)]">Stream</div>
            <div className="font-mono">{badge}</div>
          </div>
          {pauseButton}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="sr-only" htmlFor="task-log-search">Search logs</label>
          <input
            id="task-log-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search logs"
            className="min-h-9 flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          />
          <div className="flex flex-wrap gap-1.5" aria-label="Filter log segments">
            {LOG_FILTERS.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => setActiveFilter(id)}
                aria-pressed={activeFilter === id}
                className={`min-h-9 rounded-full border px-3 py-1 text-xs font-medium transition ${
                  activeFilter === id
                    ? "border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]"
                    : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:text-[var(--text)]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="sr-only" aria-live="polite">{visibleSteps.length} log steps shown</div>
      </div>
      {error && (
        <div className="px-4 py-2 text-xs text-red-300">{error}</div>
      )}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <div
          ref={scrollerRef}
          onScroll={onScroll}
          className="min-h-0 overflow-y-auto overscroll-contain border-b border-[var(--border)] px-4 pb-24 pt-3 font-mono text-[11px] leading-snug lg:border-b-0 lg:border-r"
        >
          {events.length === 0 ? (
            <div className="text-[var(--text-dim)]">
              {streamState === "open" ? "Waiting for activity…" : "No events yet."}
            </div>
          ) : visibleSteps.length === 0 ? (
            <div className="text-[var(--text-dim)]">No log steps match this filter.</div>
          ) : (
            <LogStreamFeed
              steps={visibleSteps}
              selectedStepId={selectedStep?.id ?? null}
              onSelectStep={setSelectedStepId}
            />
          )}
        </div>
        <LogDetailInspector step={selectedStep} />
      </div>
    </div>
  );
}

// ─── Semantic log stream feed (newest-first, operator-first) ─────────────────

interface LogStreamFeedProps {
  steps: LogStep[];
  selectedStepId: string | null;
  onSelectStep: (stepId: string) => void;
}

function LogStreamFeed({ steps, selectedStepId, onSelectStep }: LogStreamFeedProps) {
  return (
    <div className="space-y-1" aria-label="Activity log">
      {steps.map((step) => (
        <LogEventCard
          key={step.id}
          step={step}
          isSelected={step.id === selectedStepId}
          onSelect={() => onSelectStep(step.id)}
        />
      ))}
    </div>
  );
}

interface LogEventCardProps {
  step: LogStep;
  isSelected: boolean;
  onSelect: () => void;
}

const STEP_TYPE_ICONS: Record<string, string> = {
  agent: "🤖",
  tool: "🔧",
  phase: "🏁",
  error: "❗",
  checkpoint: "💾",
  event: "📌",
};

function LogEventCard({ step, isSelected, onSelect }: LogEventCardProps) {
  const icon = STEP_TYPE_ICONS[step.type] ?? "📌";
  const tone = step.isError
    ? "border-red-500/40 bg-red-500/10 text-red-100"
    : isSelected
      ? "border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--text)]"
      : "border-transparent text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-black/10 hover:text-[var(--text)]";

  return (
    <button
      type="button"
      aria-pressed={isSelected}
      onClick={onSelect}
      className={`flex w-full items-start gap-2 rounded-lg border px-2 py-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${tone}`}
    >
      <span className="mt-0.5 shrink-0 text-base leading-none" aria-hidden="true">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 flex-wrap">
          <span className="truncate text-[11px] font-semibold">{step.title}</span>
          {step.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-current/20 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide opacity-70"
            >
              {tag}
            </span>
          ))}
        </span>
        <span className="block truncate text-[10px] text-[var(--text-dim)] mt-0.5">{step.summary}</span>
      </span>
      <span className="shrink-0 text-[10px] text-[var(--text-dim)] mt-0.5 whitespace-nowrap">
        {new Date(step.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </span>
    </button>
  );
}

// ─── Inspector panel ──────────────────────────────────────────────────────────

function LogDetailInspector({ step }: { step: LogStep | null }) {
  const [rawExpanded, setRawExpanded] = useState(false);

  useEffect(() => {
    setRawExpanded(false);
  }, [step?.id]);

  return (
    <aside
      className="min-h-0 overflow-y-auto bg-[var(--panel)] px-4 pb-24 pt-3 font-mono text-[11px] leading-snug"
      aria-labelledby="log-detail-heading"
    >
      <div className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--panel)] pb-3">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--accent)]">Inspector</div>
        <h3 id="log-detail-heading" className="mt-1 text-sm font-semibold text-[var(--text)]">
          {step ? step.title : "Select an event"}
        </h3>
        {step && (
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-[var(--text-dim)]">{step.phase} · {new Date(step.timestamp * 1000).toLocaleString()}</span>
            {step.tags.map((tag) => (
              <span key={tag} className="rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5 text-[9px] text-[var(--text-dim)]">
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
      {!step ? (
        <div className="pt-4 text-[var(--text-dim)]">Select an event to inspect its input, output, and details.</div>
      ) : (
        <div className="space-y-4 pt-4">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3">
            <div className="mb-1 text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Summary</div>
            <div className="whitespace-pre-wrap text-[var(--text)]">{step.summary}</div>
          </div>
          {step.details.map((detail) => (
            <div key={detail.label} className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)]">
              <div className="border-b border-[var(--border)] px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-dim)]">{detail.label}</div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap p-3 text-[var(--text)]">{detail.value}</pre>
            </div>
          ))}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)]">
            <button
              type="button"
              onClick={() => setRawExpanded((v) => !v)}
              className="flex w-full items-center justify-between border-b border-[var(--border)] px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-dim)] hover:text-[var(--text)]"
            >
              <span>View raw event</span>
              <span aria-hidden="true">{rawExpanded ? "▲" : "▼"}</span>
            </button>
            {rawExpanded && (
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap p-3 text-[var(--text-dim)]">
                {JSON.stringify(step.rawEvents, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

// ─── Blocker Banner ───────────────────────────────────────────────────────────

const BLOCKER_STATUSES: RepoTaskStatus[] = ["failed", "repairing", "waiting_ci"];

interface BlockerBannerProps {
  card: PipelineCard;
  onAction: (cardId: string, action: "accept" | "reject" | "retry" | "reset") => void;
  loadingAction: boolean;
}

export function BlockerBanner({ card, onAction, loadingAction }: BlockerBannerProps) {
  if (!BLOCKER_STATUSES.includes(card.status)) return null;

  const isFailed = card.status === "failed";
  const icon = isFailed ? "⚠" : "⏳";
  const tone = isFailed
    ? "border-red-500/40 bg-red-500/10 text-red-200"
    : "border-amber-500/40 bg-amber-500/10 text-amber-200";
  const labelMap: Record<string, string> = {
    failed: "Run failed",
    repairing: "Repairing",
    waiting_ci: "Waiting on CI",
  };
  const note = card.metadata?.last_note ?? null;
  const prUrl = card.metadata?.linked_pr_url ?? null;

  return (
    <div
      role="alert"
      aria-label="Card blocker"
      data-testid="blocker-banner"
      className={`mx-4 mt-3 rounded-lg border p-3 text-sm ${tone}`}
    >
      <div className="flex items-start gap-2">
        <span className="text-lg leading-none" aria-hidden="true">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{labelMap[card.status]}</div>
          {note && (
            <div className="mt-0.5 text-[12px] leading-snug opacity-90 break-words">{note}</div>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {prUrl && (
          <a
            href={prUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-md border border-current/40 bg-black/10 px-2.5 py-1 text-xs font-medium hover:bg-black/20"
          >
            View PR
          </a>
        )}
        <button
          type="button"
          onClick={() => onAction(card.id, "reset")}
          disabled={loadingAction}
          className="rounded-md border border-current/40 bg-black/10 px-2.5 py-1 text-xs font-medium hover:bg-black/20 disabled:opacity-40"
        >
          Retry
        </button>
        {prUrl ? (
          <a
            href={prUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-md border border-current/40 bg-black/10 px-2.5 py-1 text-xs font-medium hover:bg-black/20"
          >
            Merge manually
          </a>
        ) : (
          <button
            type="button"
            disabled
            title="No linked PR"
            className="rounded-md border border-current/40 bg-black/10 px-2.5 py-1 text-xs font-medium opacity-40"
          >
            Merge manually
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Model Section ────────────────────────────────────────────────────────────

const MODEL_LOCKED_STATUSES: RepoTaskStatus[] = [
  "preparing", "running", "verifying", "waiting_ci", "repairing",
];

interface ModelSectionProps {
  card: PipelineCard;
  policyDefaultModel: string | null;
  onModelChange: (model: string | null) => void;
}

function ModelSection({ card, policyDefaultModel, onModelChange }: ModelSectionProps) {
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; msg: string } | null>(null);
  const [modelList, setModelList] = useState<Array<{ id: string; label: string }>>([]);

  const isActive = MODEL_LOCKED_STATUSES.includes(card.status);
  const currentModel = card.model ?? null;

  useEffect(() => {
    api.listModels().then((raw) => {
      const flat: Array<{ id: string; label: string }> = [];
      for (const [, profiles] of Object.entries(raw)) {
        for (const p of profiles) {
          flat.push({ id: p.id, label: p.label });
        }
      }
      setModelList(flat);
    }).catch(() => setModelList([]));
  }, []);

  const handleChange = async (e: ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    const next = value === "__policy__" ? null : value;
    const previous = currentModel;
    setLoading(true);
    setToast(null);
    onModelChange(next);
    try {
      await api.patchPipelineCardModel(card.id, next);
      setToast({ kind: "ok", msg: "Model updated" });
    } catch {
      onModelChange(previous);
      setToast({ kind: "error", msg: "Failed to update model" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Model</div>
      <div className="flex items-center gap-2">
        <select
          value={currentModel ?? "__policy__"}
          disabled={isActive || loading}
          onChange={handleChange}
          className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none disabled:opacity-40"
          aria-label="Select execution model"
        >
          <option value="__policy__">Policy default{policyDefaultModel ? ` (${policyDefaultModel})` : ""}</option>
          {modelList.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
        {isActive && (
          <span className="text-[10px] text-[var(--text-dim)] whitespace-nowrap">running…</span>
        )}
      </div>
      {toast && (
        <div
          className={`rounded border px-2 py-1 text-xs ${
            toast.kind === "ok"
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-red-500/40 bg-red-500/10 text-red-300"
          }`}
          role="status"
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

// ─── Drawer ───────────────────────────────────────────────────────────────────

const RESETTABLE_STATUSES: RepoTaskStatus[] = ["failed", "rejected", "killed", "paused", "pending"];

interface DrawerProps {
  card: PipelineCard | null;
  onClose: () => void;
  onAction: (cardId: string, action: "accept" | "reject" | "retry" | "reset") => void;
  onRun: (cardId: string) => void;
  onPause: (cardId: string) => void;
  onResume: (cardId: string) => void;
  onRetryNow: (cardId: string) => void;
  loadingAction: boolean;
  policyDefaultModel: string | null;
  onCardModelChange: (cardId: string, model: string | null) => void;
}

function Drawer({ card, onClose, onAction, onRun, onPause, onResume, onRetryNow, loadingAction, policyDefaultModel, onCardModelChange }: DrawerProps) {
  const [drawerTab, setDrawerTab] = useState<"info" | "activity" | "logs">("info");
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!card) return;

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusableSelector = [
      "button:not([disabled])",
      "a[href]",
      "select:not([disabled])",
      "input:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    const focusFirst = () => {
      const focusable = dialogRef.current?.querySelector<HTMLElement>(focusableSelector);
      focusable?.focus();
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKey);
    const raf = window.requestAnimationFrame(focusFirst);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener("keydown", onKey);
      previouslyFocused?.focus();
    };
  }, [card, onClose]);

  if (!card) return null;

  const sourceLabel = SOURCE_LABELS[card.source_kind] ?? card.source_kind;
  const sourceColor = SOURCE_COLOR[card.source_kind] ?? "bg-gray-500/20 text-gray-300 border-gray-500/40";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
        <div
          ref={dialogRef}
          className="flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="task-detail-title"
          aria-describedby="task-detail-summary"
        >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-[var(--border)] bg-[var(--panel)] p-4">
          <div className="flex-1 min-w-0">
            <p id="task-detail-summary" className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--accent)]">Autopilot task</p>
            <h2 id="task-detail-title" className="text-base font-semibold leading-snug text-[var(--text)]">{card.title}</h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${sourceColor}`}>
                {sourceLabel}
              </span>
              <span className="text-[11px] font-mono text-[var(--text-dim)]">#{card.id.slice(0, 8)}</span>
              <span className="rounded border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--text-dim)]">
                {card.status}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="min-h-11 min-w-11 shrink-0 rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-2 text-sm text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            aria-label="Close task details"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* Blocker alert – shown for failed/repairing/waiting_ci */}
          <BlockerBanner card={card} onAction={onAction} loadingAction={loadingAction} />

          {/* Tab bar */}
          <div className="flex shrink-0 border-b border-[var(--border)]" role="tablist" aria-label="Task detail sections">
            {(["info", "activity", "logs"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                role="tab"
                id={`task-tab-${tab}`}
                aria-selected={drawerTab === tab}
                aria-controls={`task-panel-${tab}`}
                tabIndex={drawerTab === tab ? 0 : -1}
                onClick={() => setDrawerTab(tab)}
                className={`min-h-11 flex-1 px-4 py-2 text-sm font-medium capitalize transition ${
                  drawerTab === tab
                    ? "border-b-2 border-[var(--accent)] text-[var(--accent)]"
                    : "text-[var(--text-dim)] hover:text-[var(--text)]"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {drawerTab === "info" ? (
            <div id="task-panel-info" role="tabpanel" aria-labelledby="task-tab-info" className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 pb-24">
              {/* Model */}
              <ModelSection
                card={card}
                policyDefaultModel={policyDefaultModel}
                onModelChange={(model) => onCardModelChange(card.id, model)}
              />

              {/* Score */}
              <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3">
                <div className="text-[10px] uppercase tracking-wider text-[var(--text-dim)] mb-1">Score</div>
                <div className="text-2xl font-bold font-mono text-[var(--accent)]">{card.score}</div>
              </div>

              {/* Labels */}
              {card.labels.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Labels</div>
                  <div className="flex flex-wrap gap-1.5">
                    {card.labels.map((label) => (
                      <span
                        key={label}
                        className="rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 text-[11px] text-[var(--text)]"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Details */}
              <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 text-sm">
                <div className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Details</div>
                {card.body && (
                  <div className="whitespace-pre-wrap text-[var(--text)]">{card.body}</div>
                )}
                <dl className="grid grid-cols-2 gap-3">
                  <div>
                    <dt className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Created</dt>
                    <dd className="text-[var(--text)]">{relativeAge(card.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">Attempts</dt>
                    <dd className="font-mono text-[var(--text)]">{card.attempt_count ?? 0}</dd>
                  </div>
                </dl>
                {card.status === "pending" && (
                  <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3 text-sm text-yellow-100">
                    <div className="text-[10px] uppercase tracking-wider text-yellow-200/80">Pending</div>
                    {card.metadata?.pending_reason && <div className="mt-1 break-words">{card.metadata.pending_reason}</div>}
                    {card.metadata?.next_retry_at && (
                      <div className="mt-1 text-yellow-100/80">Next retry {formatRelativeTime(card.metadata.next_retry_at)}</div>
                    )}
                    <button
                      onClick={() => onRetryNow(card.id)}
                      disabled={loadingAction}
                      className="mt-3 rounded-lg border border-yellow-500/40 bg-yellow-500/15 px-3 py-1.5 text-xs font-medium text-yellow-200 transition hover:bg-yellow-500/25 disabled:opacity-40"
                    >
                      {loadingAction ? "Retrying…" : "Retry now"}
                    </button>
                  </div>
                )}
                {card.metadata?.linked_pr_url && (
                  <a
                    href={card.metadata.linked_pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex text-xs text-[var(--accent)] hover:underline"
                  >
                    Linked PR
                  </a>
                )}
              </div>
            </div>
          ) : drawerTab === "activity" ? (
            <div id="task-panel-activity" role="tabpanel" aria-labelledby="task-tab-activity" className="min-h-0 flex-1 flex flex-col overflow-hidden">
              <ActivityTab cardId={card.id} isActive={drawerTab === "activity"} />
            </div>
          ) : (
            <div id="task-panel-logs" role="tabpanel" aria-labelledby="task-tab-logs" className="min-h-0 flex-1 flex flex-col overflow-hidden">
              <LogsTab cardId={card.id} isActive={drawerTab === "logs"} />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="sticky bottom-0 z-10 flex gap-2 border-t border-[var(--border)] bg-[var(--panel)] p-4">
          {/* Run button: for queued/accepted cards */}
          {(card.status === "queued" || card.status === "accepted") && (
            <button
              onClick={() => onRun(card.id)}
              disabled={loadingAction}
              className="flex-1 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-sm font-medium text-blue-300 transition hover:bg-blue-500/20 disabled:opacity-40"
              title="Start this card immediately"
            >
              ▶ Run
            </button>
          )}
          {/* Pause button: for active cards */}
          {ACTIVE_STATUSES.includes(card.status) && (
            <button
              onClick={() => onPause(card.id)}
              disabled={loadingAction}
              className="flex-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-40"
              title="Pause this card"
            >
              ⏸ Pause
            </button>
          )}
          {/* Resume button: for paused cards */}
          {card.status === "paused" && (
            <button
              onClick={() => onResume(card.id)}
              disabled={loadingAction}
              className="flex-1 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm font-medium text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-40"
              title="Resume this card"
            >
              ▶ Resume
            </button>
          )}
          {/* Retry Now button: for failed/killed/rejected */}
          {RESETTABLE_STATUSES.includes(card.status) && (
            <button
              onClick={() => onRetryNow(card.id)}
              disabled={loadingAction}
              className="flex-1 rounded-lg border border-orange-500/40 bg-orange-500/10 px-3 py-2 text-sm font-medium text-orange-300 transition hover:bg-orange-500/20 disabled:opacity-40"
              title="Retry this card immediately"
            >
              ↻ Retry Now
            </button>
          )}
          {/* Common: accept / reject for queued/accepted/paused */}
          {(card.status === "queued" || card.status === "accepted" || card.status === "paused") && (
            <>
              <button
                onClick={() => onAction(card.id, "accept")}
                disabled={loadingAction}
                className="flex-1 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-40"
              >
                Accept
              </button>
              <button
                onClick={() => onAction(card.id, "reject")}
                disabled={loadingAction}
                className="flex-1 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-300 transition hover:bg-red-500/20 disabled:opacity-40"
              >
                Reject
              </button>
              {(card.status === "queued" || card.status === "accepted") && (
                <button
                  onClick={() => onAction(card.id, "retry")}
                  disabled={loadingAction}
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm font-medium text-[var(--text)] transition hover:border-[var(--accent)]/40 disabled:opacity-40"
                >
                  Retry
                </button>
              )}
            </>
          )}
          {/* Reset for non-active cards that aren't already in terminal */}
          {card.status !== "preparing" && card.status !== "running" && !ACTIVE_STATUSES.includes(card.status) && (
            <button
              onClick={() => onAction(card.id, "reset")}
              disabled={loadingAction}
              className="flex-1 rounded-lg border border-gray-500/40 bg-gray-500/10 px-3 py-2 text-sm font-medium text-gray-300 transition hover:bg-gray-500/20 disabled:opacity-40"
            >
              Reset
            </button>
          )}
        </div>
        </div>
      </div>
    </>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

type ActiveTab = "board" | "policy";

export default function PipelinePage() {
  const [cards, setCards] = useState<PipelineCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCard, setSelectedCard] = useState<PipelineCard | null>(null);
  const [loadingAction, setLoadingAction] = useState(false);
  const [showNewIdea, setShowNewIdea] = useState(false);
  const [runningNext, setRunningNext] = useState(false);
  const [runNextError, setRunNextError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>("board");
  const [boardFilter, setBoardFilter] = useState<BoardFilter>("all");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const [policyDefaultModel, setPolicyDefaultModel] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const projectSwitchedAt = useSession((s) => s.projectSwitchedAt);

  // Attention strip counts
  const failedCount = cards.filter((c) => c.status === "failed" || c.status === "paused").length;
  const waitingCICount = cards.filter((c) => c.status === "waiting_ci").length;
  const reviewCount = cards.filter((c) => c.status === "pr_open").length;
  const runningCount = cards.filter((c) => ACTIVE_STATUSES.includes(c.status)).length;
  const queueCount = cards.filter((c) => c.status === "queued" || c.status === "accepted").length;

  useEffect(() => {
    const previous = document.title;
    document.title = "Autopilot · OpenHarness";
    return () => {
      document.title = previous;
    };
  }, []);

  // Load policy defaults for the model dropdown
  useEffect(() => {
    apiFetch<{ defaults?: { default_model?: string | null } }>("/api/pipeline/policy")
      .then((data) => {
        setPolicyDefaultModel(data.defaults?.default_model ?? null);
      })
      .catch(() => setPolicyDefaultModel(null));
  }, []);

  const refreshCards = useCallback(() => {
    apiFetch<{ cards: PipelineCard[]; updated_at: number }>("/api/pipeline/cards")
      .then((data) => {
        setCards(data.cards);
        setLastUpdated(Date.now() / 1000);
        setSecondsAgo(0);
      })
      .catch((err) => console.error("refresh cards failed:", err));
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ cards: PipelineCard[]; updated_at: number }>("/api/pipeline/cards")
      .then((cardsData) => {
        if (cancelled) return;
        setCards(cardsData.cards);
        setLastUpdated(Date.now() / 1000);
        setSecondsAgo(0);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-fetch cards when the active project changes.
  useEffect(() => {
    if (projectSwitchedAt === null) return;
    refreshCards();
  }, [projectSwitchedAt, refreshCards]);

  // Auto-refresh: start/stop polling based on active card presence
  useEffect(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    if (cards.length > 0 && hasActiveCard(cards)) {
      pollingRef.current = setInterval(refreshCards, 5000);
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [cards, refreshCards]);

  // Tick: increment secondsAgo every second while lastUpdated is set
  useEffect(() => {
    if (lastUpdated === null) return;
    const id = setInterval(() => {
      setSecondsAgo(Math.floor(Date.now() / 1000 - lastUpdated));
    }, 1000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  const handleRunNext = useCallback(async () => {
    setRunningNext(true);
    setRunNextError(null);
    try {
      await apiFetch("/api/pipeline/run-next", { method: "POST" });
      setTimeout(refreshCards, 1500);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRunNextError(msg.includes("no_queued_cards") ? "No queued cards." : msg.includes("already_running") ? "Already running." : msg);
    } finally {
      setRunningNext(false);
    }
  }, [refreshCards]);

  const handleCardModelChange = useCallback((cardId: string, model: string | null) => {
    setCards((prev) =>
      prev.map((c) => (c.id === cardId ? { ...c, model } : c)),
    );
    setSelectedCard((prev) =>
      prev && prev.id === cardId ? { ...prev, model } : prev,
    );
  }, []);

  const handleAction = useCallback(
    async (cardId: string, action: "accept" | "reject" | "retry" | "reset") => {
      setLoadingAction(true);
      try {
        await apiFetch(`/api/pipeline/cards/${encodeURIComponent(cardId)}/action`, {
          method: "POST",
          body: JSON.stringify({ action }),
          headers: { "Content-Type": "application/json" },
        });
        setSelectedCard(null);
        refreshCards();
      } catch (err) {
        console.error("action failed:", err);
      } finally {
        setLoadingAction(false);
      }
    },
    [refreshCards],
  );

  const handleRun = useCallback(
    async (cardId: string) => {
      setLoadingAction(true);
      try {
        await apiFetch(`/api/pipeline/cards/${encodeURIComponent(cardId)}/run`, {
          method: "POST",
        });
        setSelectedCard(null);
        refreshCards();
      } catch (err) {
        console.error("run failed:", err);
      } finally {
        setLoadingAction(false);
      }
    },
    [refreshCards],
  );

  const handlePause = useCallback(
    async (cardId: string) => {
      setLoadingAction(true);
      try {
        await apiFetch(`/api/pipeline/cards/${encodeURIComponent(cardId)}/pause`, {
          method: "POST",
        });
        refreshCards();
      } catch (err) {
        console.error("pause failed:", err);
      } finally {
        setLoadingAction(false);
      }
    },
    [refreshCards],
  );

  const handleRetryNow = useCallback(
    async (cardId: string) => {
      setLoadingAction(true);
      try {
        await apiFetch(`/api/pipeline/cards/${encodeURIComponent(cardId)}/retry-now`, {
          method: "POST",
        });
        setSelectedCard(null);
        refreshCards();
      } catch (err) {
        console.error("retry-now failed:", err);
      } finally {
        setLoadingAction(false);
      }
    },
    [refreshCards],
  );

  const handleResume = useCallback(
    async (cardId: string) => {
      setLoadingAction(true);
      try {
        await apiFetch(`/api/pipeline/cards/${encodeURIComponent(cardId)}/resume`, {
          method: "POST",
        });
        setSelectedCard(null);
        refreshCards();
      } catch (err) {
        console.error("resume failed:", err);
      } finally {
        setLoadingAction(false);
      }
    },
    [refreshCards],
  );


  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="text-sm text-[var(--text-dim)]">Loading autopilot…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      </div>
    );
  }

  const activeCount = cards.filter((c) => ACTIVE_STATUSES.includes(c.status)).length;

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      {/* Page header */}
      <PageHeader
        title="Autopilot"
        description="Automated pipeline that picks up, runs, and reviews tasks from the queue."
        primaryAction={
          activeTab === "board" ? (
            <div className="flex items-center gap-2">
              <button
                onClick={handleRunNext}
                disabled={runningNext}
                className="rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-medium text-blue-300 transition hover:bg-blue-500/20 disabled:opacity-40"
                title="Run the highest-priority queued card"
              >
                {runningNext ? "Starting…" : "▶ Run Next"}
              </button>
              <button
                onClick={() => setShowNewIdea(true)}
                className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/20"
              >
                + New idea
              </button>
            </div>
          ) : undefined
        }
        secondaryAction={
          runNextError ? (
            <span className="text-[11px] text-red-400">{runNextError}</span>
          ) : undefined
        }
        metadata={[
          { label: "Total", value: String(cards.length) },
          { label: "Active", value: String(activeCount), accent: activeCount > 0 ? "cyan" : "none" },
          ...(lastUpdated !== null ? [{ label: "Last sync", value: formatSeconds(secondsAgo) }] : []),
        ]}
      />

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-[var(--border)] px-4 pt-2">
          <button
            onClick={() => setActiveTab("board")}
            className={`rounded-t-lg border px-4 py-2 text-sm font-medium transition ${
              activeTab === "board"
                ? "border-b-0 border-[var(--border)] bg-[var(--panel)] text-[var(--text)]"
                : "border-b border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:text-[var(--text)]"
            }`}
          >
            Board
          </button>
          <button
            onClick={() => setActiveTab("policy")}
            className={`rounded-t-lg border px-4 py-2 text-sm font-medium transition ${
              activeTab === "policy"
                ? "border-b-0 border-[var(--border)] bg-[var(--panel)] text-[var(--text)]"
                : "border-b border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:text-[var(--text)]"
            }`}
          >
            Policy
          </button>
      </div>

      {/* Content */}
      {activeTab === "policy" ? (
        <PolicyTab onSaved={() => {}} />
      ) : (
        <>
          <div className="border-b border-[var(--border)] px-4 py-3">
            <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-5">
              {[
                { label: "Failed/Paused", count: failedCount },
                { label: "Waiting CI", count: waitingCICount },
                { label: "Review", count: reviewCount },
                { label: "Running", count: runningCount },
                { label: "Queue", count: queueCount },
              ].map((item) => (
                <div key={item.label} className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs">
                  <div className="text-[var(--text-dim)]">{item.label}</div>
                  <div className="mt-1 text-lg font-semibold text-[var(--text)]">{item.count}</div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {BOARD_FILTERS.map((filter) => (
                <button key={filter.id} onClick={() => setBoardFilter(filter.id)} className={`rounded-md border px-2.5 py-1 text-xs ${boardFilter === filter.id ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)] text-[var(--text-dim)]"}`}>
                  {filter.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-1 overflow-x-auto overflow-y-hidden p-4 gap-4">
            {COLUMNS.map((col) => {
              const colCards = cards.filter((c) => col.statuses.includes(c.status) && matchesBoardFilter(c.status, boardFilter));
              return (
                <div key={col.id} className="flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--panel)]">
                  <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2.5">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-dim)]">{col.label}</span>
                    <span className={`flex h-5 min-w-5 items-center justify-center rounded-full border px-1.5 text-[10px] font-medium ${col.badgeColor}${col.pulseWhenActive && colCards.length > 0 ? " animate-pulse-subtle" : ""}`}>{colCards.length}</span>
                  </div>
                  <div className="flex-1 overflow-y-auto p-2 space-y-2">
                    {colCards.length === 0 ? <div className="rounded-lg border border-dashed border-[var(--border)] p-4 text-center text-xs text-[var(--text-dim)]">No cards for this filter.</div> : colCards.map((card) => <Card key={card.id} card={card} onClick={() => setSelectedCard(card)} />)}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {showNewIdea && (
        <NewIdeaModal
          onClose={() => setShowNewIdea(false)}
          onSuccess={() => {
            setShowNewIdea(false);
            refreshCards();
          }}
        />
      )}

      <Drawer
        card={selectedCard}
        onClose={() => setSelectedCard(null)}
        onAction={handleAction}
        onRun={handleRun}
        onPause={handlePause}
        onResume={handleResume}
        onRetryNow={handleRetryNow}
        loadingAction={loadingAction}
        policyDefaultModel={policyDefaultModel}
        onCardModelChange={handleCardModelChange}
      />
    </div>
  );
}
