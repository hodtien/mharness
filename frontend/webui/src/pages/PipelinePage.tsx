import React, { useEffect, useState, useCallback, useRef, type ChangeEvent, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { api, apiFetch, getToken } from "../api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

export type RepoTaskStatus =
  | "queued"
  | "accepted"
  | "preparing"
  | "running"
  | "verifying"
  | "repairing"
  | "pr_open"
  | "waiting_ci"
  | "completed"
  | "merged"
  | "failed"
  | "rejected"
  | "killed";

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
  model_override?: string | null;
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

  useEffect(() => {
    apiFetch<{ yaml_content: string; parsed: unknown }>("/api/pipeline/policy")
      .then((data) => {
        setYamlContent(data.yaml_content);
      })
      .catch((err) => setLoadError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaveError(null);
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch("/api/pipeline/policy", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
        },
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
          {saved && (
            <span className="text-xs text-emerald-400">Saved ✓</span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-4 py-1.5 text-sm font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/30 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      <textarea
        value={yamlContent}
        onChange={(e) => { setYamlContent(e.target.value); setSaved(false); }}
        className="flex-1 resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-4 font-mono text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
        spellCheck={false}
      />
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

function hasActiveCard(cards: PipelineCard[]): boolean {
  return cards.some((c) => ACTIVE_STATUSES.includes(c.status));
}

function formatSeconds(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

// ─── Kanban columns ────────────────────────────────────────────────────────────

const COLUMNS: { id: string; label: string; statuses: RepoTaskStatus[] }[] = [
  { id: "queue", label: "Queue", statuses: ["queued", "accepted"] },
  { id: "in_progress", label: "In Progress", statuses: ["preparing", "running", "verifying", "repairing"] },
  { id: "review", label: "Review", statuses: ["pr_open", "waiting_ci"] },
  { id: "completed", label: "Completed", statuses: ["completed", "merged"] },
  { id: "failed", label: "Failed", statuses: ["failed"] },
  { id: "rejected", label: "Rejected", statuses: ["rejected", "killed"] },
];

const SOURCE_LABELS: Record<RepoTaskSource, string> = {
  github_issue: "Issue",
  github_pr: "PR",
  manual_idea: "Idea",
  ohmo_request: "OHMO",
  claude_code_candidate: "Candidate",
};

const SOURCE_COLOR: Record<RepoTaskSource, string> = {
  github_issue: "bg-violet-500/20 text-violet-300 border-violet-500/40",
  github_pr: "bg-blue-500/20 text-blue-300 border-blue-500/40",
  manual_idea: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  ohmo_request: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  claude_code_candidate: "bg-orange-500/20 text-orange-300 border-orange-500/40",
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

// ─── Card ─────────────────────────────────────────────────────────────────────

function Card({ card, onClick }: { card: PipelineCard; onClick: () => void }) {
  const sourceLabel = SOURCE_LABELS[card.source_kind] ?? card.source_kind;
  const sourceColor = SOURCE_COLOR[card.source_kind] ?? "bg-gray-500/20 text-gray-300 border-gray-500/40";

  return (
    <button
      onClick={onClick}
      className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 text-left text-sm shadow-sm transition hover:border-[var(--accent)]/40 hover:bg-[var(--panel)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
    >
      <div className="mb-1.5 font-medium leading-snug text-[var(--text)]">{card.title}</div>
      <div className="flex items-center justify-between gap-2">
        <span
          className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${sourceColor}`}
        >
          {sourceLabel}
        </span>
        <div className="flex items-center gap-2">
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

// ─── Markdown helper ──────────────────────────────────────────────────────────

function MarkdownText({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
      {content}
    </ReactMarkdown>
  );
}

// ─── Review Tab ────────────────────────────────────────────────────────────────

interface ReviewTabProps {
  cardId: string;
  isActive: boolean;
  cardStatus: string;
}

interface ReviewData {
  task_id: string;
  status: string;
  markdown: string;
  created_at: number;
}

function ReviewTab({ cardId, isActive, cardStatus }: ReviewTabProps) {
  const isMerged = cardStatus === "merged";
  const [reviewState, setReviewState] = useState<
    "loading" | "not_found" | "running" | "done"
  >("loading");
  const [review, setReview] = useState<ReviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchReview = useCallback(async () => {
    try {
      const data = await apiFetch<ReviewData>(`/api/review/${encodeURIComponent(cardId)}`);
      setReview(data);
      setReviewState("done");
    } catch (err) {
      // 404 means no review yet; treat any 4xx as not_found
      const msg = String(err);
      if (msg.includes("404")) {
        setReviewState("not_found");
      } else {
        setError(msg);
        setReviewState("not_found");
      }
    }
  }, [cardId]);

  const startRerun = useCallback(async () => {
    setRerunning(true);
    setReviewState("running");
    setError(null);
    try {
      await apiFetch<{ ok: boolean; message: string }>(
        `/api/review/${encodeURIComponent(cardId)}/rerun`,
        { method: "POST" },
      );
    } catch (err) {
      setError(String(err));
    } finally {
      setRerunning(false);
    }
  }, [cardId]);

  // Reset when tab becomes active
  useEffect(() => {
    if (isActive) {
      setReviewState("loading");
      setReview(null);
      setError(null);
      fetchReview();
    }
  }, [isActive, fetchReview]);

  // Poll every 3 s while in running state
  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (reviewState === "running") {
      timerRef.current = setInterval(fetchReview, 3000);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [reviewState, fetchReview]);

  if (reviewState === "loading") {
    return (
      <div className="flex items-center justify-center p-6">
        <span className="text-sm text-[var(--text-dim)]">Loading review…</span>
      </div>
    );
  }

  if (reviewState === "running") {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-6">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--accent)] border-t-transparent" />
        <span className="text-sm text-[var(--text-dim)]">Reviewing…</span>
      </div>
    );
  }

  if (reviewState === "not_found") {
    return (
      <div className="flex flex-col items-center gap-4 p-6 text-center">
        <p className="text-sm text-[var(--text-dim)]">
          {isMerged
            ? "No local review file. This card was merged after passing the autopilot remote review gate."
            : "No review yet for this task."}
        </p>
        {error && (
          <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">
            {error}
          </p>
        )}
        {!isMerged && (
          <button
            onClick={startRerun}
            disabled={rerunning}
            className="rounded-lg border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-5 py-2 text-sm font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/30 disabled:opacity-40"
          >
            {rerunning ? "Starting…" : "Run Review"}
          </button>
        )}
      </div>
    );
  }

  // done
  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <span className="text-[10px] uppercase tracking-wider text-[var(--text-dim)]">
          Review · {review ? relativeAge(review.created_at) : ""}
        </span>
        {!isMerged && (
          <button
            onClick={startRerun}
            disabled={rerunning}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1 text-xs text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)] disabled:opacity-40"
          >
            {rerunning ? "Starting…" : "Re-run Review"}
          </button>
        )}
      </div>
      <div className="overflow-y-auto p-4">
        <div className="prose prose-invert max-w-none text-sm text-[var(--text)]">
          <MarkdownText content={review?.markdown ?? ""} />
        </div>
      </div>
    </div>
  );
}

// ─── Activity Tab ──────────────────────────────────────────────────────────────

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

  const filteredEntries = entries.filter((e) => matchesActivityFilter(e.kind, activeFilter));

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
          {filteredEntries.map((entry, idx) => (
            <div key={idx} className="flex gap-3 text-sm" data-testid="activity-item">
              <span
                className="shrink-0 mt-0.5 text-base"
                data-testid="activity-item-icon"
              >
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

interface StreamEvent {
  ts: number;
  kind: string;
  payload: Record<string, unknown>;
}

const _SSE_BACKOFF_INITIAL_MS = 1_000;
const _SSE_BACKOFF_MAX_MS = 30_000;
const _SSE_MAX_RETRIES = 6;

function LogsTab({ cardId, isActive }: LogsTabProps) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [streamState, setStreamState] = useState<"connecting" | "open" | "closed">("connecting");
  const [error, setError] = useState<string | null>(null);
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
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const token = getToken();
      const after = seenCountRef.current;
      const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
      const url = `/api/pipeline/cards/${encodeURIComponent(cardId)}/stream?after=${after}${tokenParam}`;
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
        try {
          const data = JSON.parse(ev.data) as StreamEvent;
          setEvents((prev) => [...prev, data]);
          seenCountRef.current += 1;
        } catch {
          // ignore malformed lines
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
    if (stickRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [events]);

  const onScroll = useCallback(() => {
    const node = scrollerRef.current;
    if (!node) return;
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    stickRef.current = distanceFromBottom < 40;
  }, []);

  const badge = streamState === "open" ? (
    <span className="text-emerald-300">● live</span>
  ) : streamState === "connecting" ? (
    <span className="text-amber-300">● connecting…</span>
  ) : (
    <span className="text-[var(--text-dim)]">○ ended</span>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2 text-[11px]">
        <div className="font-mono uppercase tracking-wider text-[var(--text-dim)]">Stream</div>
        <div className="font-mono">{badge}</div>
      </div>
      {error && (
        <div className="px-4 py-2 text-xs text-red-300">{error}</div>
      )}
      <div
        ref={scrollerRef}
        onScroll={onScroll}
        className="flex-1 overflow-auto px-4 py-2 font-mono text-[11px] leading-snug"
      >
        {events.length === 0 ? (
          <div className="text-[var(--text-dim)]">
            {streamState === "open" ? "Waiting for activity…" : "No events yet."}
          </div>
        ) : (
          events.map((ev, idx) => <LogLine key={idx} event={ev} />)
        )}
      </div>
    </div>
  );
}

function LogLine({ event }: { event: StreamEvent }) {
  const { kind, payload } = event;
  const phase = typeof payload?.phase === "string" ? (payload.phase as string) : null;

  if (kind === "phase_start") {
    const attempt = typeof payload?.attempt === "number" ? ` · attempt ${payload.attempt}` : "";
    return (
      <div className="mt-2 border-t border-[var(--border)] pt-1 text-[var(--accent)]">
        ▶ {String(payload?.phase ?? "phase")}{attempt}
      </div>
    );
  }
  if (kind === "phase_end") {
    const ok = payload?.ok === false ? "✗" : "✓";
    return (
      <div className="text-[var(--text-dim)]">
        {ok} {String(payload?.phase ?? "phase")} ended
      </div>
    );
  }
  if (kind === "text_delta") {
    return (
      <span className="whitespace-pre-wrap text-[var(--text)]">
        {String(payload?.text ?? "")}
      </span>
    );
  }
  if (kind === "tool_call") {
    return (
      <div className="text-sky-300">
        ⚙ {String(payload?.name ?? "tool")}
        {payload?.input_summary ? (
          <span className="text-[var(--text-dim)]"> {String(payload.input_summary)}</span>
        ) : null}
      </div>
    );
  }
  if (kind === "tool_result") {
    const isError = payload?.is_error === true;
    return (
      <div className={isError ? "text-red-300" : "text-emerald-300"}>
        {isError ? "✗" : "→"} {String(payload?.name ?? "tool")}
        {payload?.summary ? (
          <span className="text-[var(--text-dim)]"> {String(payload.summary)}</span>
        ) : null}
      </div>
    );
  }
  if (kind === "error") {
    return (
      <div className="text-red-300">
        ✗ error: {String(payload?.message ?? "")}
      </div>
    );
  }
  if (kind === "checkpoint_saved") {
    return (
      <div className="text-violet-300">
        ⛯ checkpoint: {String(payload?.phase ?? "")}
      </div>
    );
  }
  return (
    <div className="text-[var(--text-dim)]">
      {kind}{phase ? ` (${phase})` : ""}
    </div>
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

const RESETTABLE_STATUSES: RepoTaskStatus[] = ["failed", "rejected", "killed"];

interface DrawerProps {
  card: PipelineCard | null;
  onClose: () => void;
  onAction: (cardId: string, action: "accept" | "reject" | "retry" | "reset") => void;
  onResume: (cardId: string) => void;
  loadingAction: boolean;
  policyDefaultModel: string | null;
  onCardModelChange: (cardId: string, model: string | null) => void;
}

function Drawer({ card, onClose, onAction, onResume, loadingAction, policyDefaultModel, onCardModelChange }: DrawerProps) {
  const [drawerTab, setDrawerTab] = useState<"info" | "activity" | "review" | "logs">("info");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (card) {
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
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
      <div
        className="fixed bottom-0 right-0 top-0 z-50 flex w-full max-w-lg max-h-screen flex-col border-l border-[var(--border)] bg-[var(--panel)] shadow-2xl sm:bottom-auto"
        role="dialog"
        aria-modal="true"
        aria-label="Card detail"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold leading-snug text-[var(--text)]">{card.title}</h2>
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
            className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-1.5 text-sm text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            aria-label="Close drawer"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* Blocker alert – shown for failed/repairing/waiting_ci */}
          <BlockerBanner card={card} onAction={onAction} loadingAction={loadingAction} />

          {/* Tab bar */}
          <div className="flex shrink-0 border-b border-[var(--border)]">
            <button
              onClick={() => setDrawerTab("info")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition ${
                drawerTab === "info"
                  ? "border-b-2 border-[var(--accent)] text-[var(--accent)]"
                  : "text-[var(--text-dim)] hover:text-[var(--text)]"
              }`}
            >
              Info
            </button>
            <button
              onClick={() => setDrawerTab("activity")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition ${
                drawerTab === "activity"
                  ? "border-b-2 border-[var(--accent)] text-[var(--accent)]"
                  : "text-[var(--text-dim)] hover:text-[var(--text)]"
              }`}
            >
              Activity
            </button>
            <button
              onClick={() => setDrawerTab("review")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition ${
                drawerTab === "review"
                  ? "border-b-2 border-[var(--accent)] text-[var(--accent)]"
                  : "text-[var(--text-dim)] hover:text-[var(--text)]"
              }`}
            >
              Review
            </button>
            <button
              onClick={() => setDrawerTab("logs")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition ${
                drawerTab === "logs"
                  ? "border-b-2 border-[var(--accent)] text-[var(--accent)]"
                  : "text-[var(--text-dim)] hover:text-[var(--text)]"
              }`}
            >
              Logs
            </button>
          </div>

          {/* Tab content */}
          {drawerTab === "info" ? (
            <div className="space-y-4 p-4">
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
            <ActivityTab cardId={card.id} isActive={drawerTab === "activity"} />
          ) : drawerTab === "logs" ? (
            <LogsTab cardId={card.id} isActive={drawerTab === "logs"} />
          ) : (
            <ReviewTab cardId={card.id} isActive={drawerTab === "review"} cardStatus={card.status} />
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2 border-t border-[var(--border)] p-4">
          {RESETTABLE_STATUSES.includes(card.status) ? (
            <>
              {card.metadata?.resume_available ? (
                <button
                  onClick={() => onResume(card.id)}
                  disabled={loadingAction}
                  className="flex-1 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm font-medium text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-40"
                  title={card.metadata?.resume_phase ? `Resume from ${card.metadata.resume_phase}` : "Resume from checkpoint"}
                >
                  Resume{card.metadata?.resume_phase ? ` (${card.metadata.resume_phase})` : ""}
                </button>
              ) : null}
              <button
                onClick={() => onAction(card.id, "reset")}
                disabled={loadingAction}
                className="flex-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300 transition hover:bg-amber-500/20 disabled:opacity-40"
              >
                Reset to Queue
              </button>
            </>
          ) : (
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
              <button
                onClick={() => onAction(card.id, "retry")}
                disabled={loadingAction}
                className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm font-medium text-[var(--text)] transition hover:border-[var(--accent)]/40 disabled:opacity-40"
              >
                Retry
              </button>
            </>
          )}
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
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const [policyDefaultModel, setPolicyDefaultModel] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 pt-3">
        <div className="flex items-center gap-4">
          <div className="mb-1">
            <div className="text-[11px] uppercase tracking-wide text-[var(--text-dim)]">Home / Autopilot</div>
            <h1 className="text-lg font-semibold text-[var(--text)]">Autopilot</h1>
          </div>
          <div className="flex gap-1">
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
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated !== null && activeTab === "board" && (
            <span className="mb-1 text-xs text-[var(--text-dim)]">
              Last updated {formatSeconds(secondsAgo)}
            </span>
          )}
          {activeTab === "board" && (
            <div className="mb-1 flex flex-col items-end gap-1">
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
              {runNextError && (
                <span className="text-[11px] text-red-400">{runNextError}</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      {activeTab === "policy" ? (
        <PolicyTab onSaved={() => {}} />
      ) : (
        <div className="flex flex-1 overflow-x-auto overflow-y-hidden p-4 gap-4">
          {COLUMNS.map((col) => {
            const colCards = cards.filter((c) => col.statuses.includes(c.status));
            return (
              <div
                key={col.id}
                className="flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--panel)]"
              >
                {/* Column header */}
                <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-dim)]">
                    {col.label}
                  </span>
                  <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--panel-2)] px-1.5 text-[10px] font-medium text-[var(--text-dim)]">
                    {colCards.length}
                  </span>
                </div>

                {/* Cards */}
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                  {colCards.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-[var(--border)] p-4 text-center text-xs text-[var(--text-dim)]">
                      No cards
                    </div>
                  ) : (
                    colCards.map((card) => (
                      <Card
                        key={card.id}
                        card={card}
                        onClick={() => setSelectedCard(card)}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
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
        onResume={handleResume}
        loadingAction={loadingAction}
        policyDefaultModel={policyDefaultModel}
        onCardModelChange={handleCardModelChange}
      />
    </div>
  );
}