import React, { useEffect, useState, useCallback, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { apiFetch } from "../api/client";
import PageHeader from "../components/PageHeader";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ErrorBanner from "../components/ErrorBanner";

// ─── Types ────────────────────────────────────────────────────────────────────

export type TaskType = "local_bash" | "local_agent" | "remote_agent" | "in_process_teammate";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "killed";

export interface TaskRecord {
  id: string;
  type: TaskType;
  status: TaskStatus;
  description: string;
  cwd: string;
  output_file: string;
  command: string | null;
  prompt: string | null;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  return_code: number | null;
  metadata: Record<string, string>;
}

// ─── Filter/Sort State ────────────────────────────────────────────────────────

export type SortOrder = "newest" | "default";

export interface FilterState {
  search: string;
  status: TaskStatus | "all";
  type: TaskType | "all";
  reviewStatus: "all" | "reviewed" | "pending_review" | "no_review";
  sort: SortOrder;
}

// ─── Status colors ────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<TaskStatus, string> = {
  pending: "bg-[var(--status-pending-bg)] text-[var(--status-pending-text)] border-[var(--status-pending-border)]",
  running: "bg-[var(--status-running-bg)] text-[var(--status-running-text)] border-[var(--status-running-border)]",
  completed: "bg-[var(--status-done-bg)] text-[var(--status-done-text)] border-[var(--status-done-border)]",
  failed: "bg-[var(--status-failed-bg)] text-[var(--status-failed-text)] border-[var(--status-failed-border)]",
  killed: "bg-[var(--status-rejected-bg)] text-[var(--status-rejected-text)] border-[var(--status-rejected-border)]",
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  killed: "Killed",
};

const STATUS_ICON: Record<TaskStatus, string> = {
  pending: "⏳",
  running: "⟳",
  completed: "✓",
  failed: "✗",
  killed: "⊗",
};

// ─── Status Badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_COLOR[status]}`}>
      <span className="leading-none">{STATUS_ICON[status]}</span>
      <span>{STATUS_LABEL[status]}</span>
    </span>
  );
}

// ─── Review status badge ──────────────────────────────────────────────────────

export type ReviewStatusValue = "done" | "in_progress" | "pending" | "failed" | "timeout" | "error";

export const REVIEW_STATUS_LABELS: Record<ReviewStatusValue, string> = {
  done: "Reviewed",
  in_progress: "Pending review",
  pending: "Pending review",
  failed: "Review failed",
  timeout: "Review timeout",
  error: "Review error",
};

export const REVIEW_STATUS_ICONS: Record<ReviewStatusValue, string> = {
  done: "✅",
  in_progress: "⏳",
  pending: "⏳",
  failed: "❌",
  timeout: "⏱️",
  error: "⚠️",
};

export const REVIEW_STATUS_COLORS: Record<ReviewStatusValue, string> = {
  done: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  in_progress: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  pending: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  failed: "bg-red-500/15 text-red-300 border-red-500/30",
  timeout: "bg-red-500/15 text-red-300 border-red-500/30",
  error: "bg-red-500/15 text-red-300 border-red-500/30",
};

function getReviewStatus(metadata: Record<string, string>): ReviewStatusValue | null {
  const v = metadata["review_status"] ?? null;
  if (!v) return null;
  return v as ReviewStatusValue;
}

function ReviewBadge({
  status,
  onClick,
}: {
  status: ReviewStatusValue | null;
  onClick: (e: React.MouseEvent) => void;
}) {
  if (status === null) {
    return <span className="text-sm text-[var(--text-dim)]">No review needed</span>;
  }
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium transition hover:brightness-125 cursor-pointer ${REVIEW_STATUS_COLORS[status]}`}
      aria-label={`${REVIEW_STATUS_LABELS[status]} review`}
    >
      <span className="leading-none">{REVIEW_STATUS_ICONS[status]}</span>
      <span>{REVIEW_STATUS_LABELS[status]}</span>
    </button>
  );
}

// ─── Review Panel (inside detail drawer) ──────────────────────────────────────

interface ReviewData {
  task_id: string;
  status: string;
  markdown: string;
  created_at: number;
}

function ReviewPanel({ taskId }: { taskId: string }) {
  const [state, setState] = useState<"loading" | "not_found" | "done" | "error">("loading");
  const [review, setReview] = useState<ReviewData | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<ReviewData>(`/api/review/${encodeURIComponent(taskId)}`);
        if (!cancelled) {
          setReview(data);
          setState("done");
        }
      } catch (err) {
        if (!cancelled) {
          const msg = String(err);
          if (msg.includes("404")) {
            setState("not_found");
          } else {
            setErrMsg(msg);
            setState("error");
          }
        }
      }
    })();
    return () => { cancelled = true; };
  }, [taskId]);

  if (state === "loading") {
    return <span className="text-xs text-[var(--text-dim)]">Loading review…</span>;
  }
  if (state === "not_found") {
    return <span className="text-xs text-[var(--text-dim)]">No review yet.</span>;
  }
  if (state === "error") {
    return <span className="text-xs text-red-300">{errMsg}</span>;
  }
  return (
    <div className="prose prose-invert max-w-none text-sm text-[var(--text)]">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>{review?.markdown ?? ""}</ReactMarkdown>
    </div>
  );
}

// ─── Utilities ────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function truncateId(id: string): string {
  return id.slice(0, 8);
}

// ─── Log Viewer ───────────────────────────────────────────────────────────────

interface LogViewerProps {
  taskId: string;
  status: TaskStatus;
  onStop: () => void;
  stopping: boolean;
}

function LogViewer({ taskId, status, onStop, stopping }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const [userScrolled, setUserScrolled] = useState(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLPreElement>(null);
  const isRunning = status === "running";

  const fetchOutput = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await apiFetch<{ lines: string[] }>(`/api/tasks/${encodeURIComponent(taskId)}/output?tail=500`);
      setLines(data.lines ?? []);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [taskId]);

  useEffect(() => {
    fetchOutput();
    if (isRunning) {
      const interval = setInterval(fetchOutput, 2000); // Poll every 2s for running jobs
      return () => clearInterval(interval);
    }
  }, [fetchOutput, isRunning]);

  // Auto-scroll to bottom when lines change (only when running and user hasn't scrolled up)
  useEffect(() => {
    if (isRunning && !userScrolled && bottomRef.current && typeof bottomRef.current.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines.length, isRunning, userScrolled]);

  // Detect user scroll
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 10;
      
      if (isAtBottom) {
        setUserScrolled(false);
        setShowScrollButton(false);
      } else {
        setUserScrolled(true);
        setShowScrollButton(true);
      }
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToBottom = () => {
    if (bottomRef.current && typeof bottomRef.current.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
    setUserScrolled(false);
    setShowScrollButton(false);
  };

  const copyLogs = async () => {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Failed to copy logs:", err);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--text-dim)]">
          Output log
          {refreshing && <span className="ml-1 opacity-60">· refreshing</span>}
        </span>
        <div className="flex items-center gap-2">
          {lines.length > 0 && (
            <button
              onClick={copyLogs}
              className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1 text-xs font-medium text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            >
              {copySuccess ? "✓ Copied" : "Copy log"}
            </button>
          )}
          {isRunning && (
            <button
              onClick={onStop}
              disabled={stopping}
              className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-1 text-xs font-medium text-red-300 transition hover:bg-red-500/20 disabled:opacity-40"
            >
              {stopping ? "Stopping…" : "Stop"}
            </button>
          )}
        </div>
      </div>

      {loading && lines.length === 0 ? (
        <div className="flex items-center justify-center py-4">
          <span className="text-sm text-[var(--text-dim)]">Loading output…</span>
        </div>
      ) : error && lines.length === 0 ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      ) : (
        <div className="relative">
          <pre
            ref={containerRef}
            className="max-h-80 overflow-auto rounded-lg border border-zinc-700 bg-zinc-900 p-3 font-mono text-xs leading-relaxed text-zinc-100"
          >
            {lines.length === 0 ? (
              <span className="text-zinc-500">No output yet.</span>
            ) : (
              lines.map((line, i) => <div key={i}>{line}</div>)
            )}
            <div ref={bottomRef} />
          </pre>
          {showScrollButton && (
            <button
              onClick={scrollToBottom}
              className="absolute bottom-4 right-4 rounded-md border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-3 py-1.5 text-xs font-medium text-[var(--accent)] shadow-lg transition hover:bg-[var(--accent)]/30"
              aria-label="Scroll to bottom"
            >
              ↓ Scroll to bottom
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Detail Drawer ────────────────────────────────────────────────────────────

interface DetailDrawerProps {
  taskId: string;
  onClose: () => void;
  onStop: () => void;
  onRetry: () => void;
  stopping: boolean;
  retrying: boolean;
  focusReview?: boolean;
}

function DetailDrawer({ taskId, onClose, onStop, onRetry, stopping, retrying, focusReview }: DetailDrawerProps) {
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [fetching, setFetching] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const reviewRef = useRef<HTMLDivElement>(null);

  // Scroll to the review section when the drawer is opened by clicking a badge.
  useEffect(() => {
    if (focusReview && task && reviewRef.current && typeof reviewRef.current.scrollIntoView === "function") {
      reviewRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focusReview, task]);

  const fetchDetail = useCallback(async () => {
    try {
      const data = await apiFetch<TaskRecord>(`/api/tasks/${encodeURIComponent(taskId)}`);
      setTask(data);
      setFetchError(null);
    } catch (err) {
      setFetchError(String(err));
    } finally {
      setFetching(false);
    }
  }, [taskId]);

  useEffect(() => {
    setFetching(true);
    setTask(null);
    fetchDetail();
  }, [fetchDetail]);

  useEffect(() => {
    if (!task || task.status !== "running") return;
    const interval = setInterval(fetchDetail, 3000);
    return () => clearInterval(interval);
  }, [fetchDetail, task]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (fetching) {
    return (
      <>
        <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} aria-hidden="true" />
        <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col border-l border-[var(--border)] bg-[var(--panel)] shadow-2xl">
          <div className="flex flex-1 items-center justify-center p-5">
            <LoadingSkeleton rows={3} className="w-full" />
          </div>
        </div>
      </>
    );
  }

  const currentTask = task;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col border-l border-[var(--border)] bg-[var(--panel)] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 font-mono text-xs text-[var(--text-dim)]">
              {truncateId(taskId)}
            </span>
            {currentTask && (
              <StatusBadge status={currentTask.status} />
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-1.5 text-sm text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {fetchError ? (
            <ErrorBanner message={`Failed to load task detail${fetchError ? `: ${fetchError}` : "."}`} />
          ) : currentTask ? (
            <div className="space-y-5">
              {/* Description */}
              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Description</div>
                <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
                  {currentTask.description || <span className="text-[var(--text-dim)]">—</span>}
                </div>
              </div>

              {/* Meta grid */}
              <div className="grid grid-cols-2 gap-3">
                <MetaItem label="Type" value={currentTask.type} />
                <div className="flex flex-col gap-1">
                  <div className="text-xs font-medium text-[var(--text-dim)]">Status</div>
                  <div>
                    <StatusBadge status={currentTask.status} />
                  </div>
                </div>
                <MetaItem label="Created" value={formatTime(currentTask.created_at)} />
                <MetaItem label="Started" value={formatTime(currentTask.started_at ?? 0)} />
                <MetaItem label="Ended" value={formatTime(currentTask.ended_at ?? 0)} />
                {currentTask.return_code !== null && (
                  <MetaItem label="Return code" value={String(currentTask.return_code)} highlight={currentTask.return_code !== 0} />
                )}
              </div>

              {/* Command / Prompt */}
              {currentTask.command && (
                <div>
                  <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Command</div>
                  <pre className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-[var(--text)]">
                    {currentTask.command}
                  </pre>
                </div>
              )}
              {currentTask.prompt && (
                <div>
                  <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Prompt</div>
                  <pre className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-[var(--text)]">
                    {currentTask.prompt}
                  </pre>
                </div>
              )}

              {/* CWD */}
              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Working directory</div>
                <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-[var(--text)]">
                  {currentTask.cwd}
                </div>
              </div>

              {/* Review */}
              {getReviewStatus(currentTask.metadata) && (
                <div ref={reviewRef}>
                  <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Review</div>
                  <div className="max-h-72 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2">
                    <ReviewPanel taskId={currentTask.id} />
                  </div>
                </div>
              )}

              {/* Log Viewer + actions */}
              <LogViewer taskId={currentTask.id} status={currentTask.status} onStop={onStop} stopping={stopping} />

              {currentTask.status === "failed" && (
                <button
                  onClick={onRetry}
                  disabled={retrying}
                  className="w-full rounded-lg border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-4 py-2 text-sm font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/20 disabled:opacity-50"
                >
                  {retrying ? "Retrying…" : "Retry"}
                </button>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}

function MetaItem({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">{label}</div>
      <div className={`rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs ${highlight ? "text-red-300" : "text-[var(--text)]"}`}>
        {value}
      </div>
    </div>
  );
}

// ─── Row expansion: log preview button ───────────────────────────────────────

function ButtonFetchLogPreview({ taskId }: { taskId: string }) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiFetch<{ lines: string[] }>(`/api/tasks/${encodeURIComponent(taskId)}/output?tail=50`)
      .then((data) => {
        if (!cancelled) {
          setLines(data.lines ?? []);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [taskId]);

  if (loading) return <span className="text-zinc-500">Loading…</span>;
  if (error) return <span className="text-red-400">Error</span>;
  if (!lines || lines.length === 0) return <span className="text-zinc-500">No output</span>;
  return (
    <pre className="whitespace-pre-wrap">{lines.join("\n")}</pre>
  );
}

// ─── Main Tasks Page ──────────────────────────────────────────────────────────

const ALL_STATUSES: TaskStatus[] = ["pending", "running", "completed", "failed", "killed"];
const ALL_TYPES: TaskType[] = ["local_bash", "local_agent", "remote_agent", "in_process_teammate"];

const TYPE_LABELS: Record<TaskType, string> = {
  local_bash: "Local Bash",
  local_agent: "Local Agent",
  remote_agent: "Remote Agent",
  in_process_teammate: "In-Process Teammate",
};

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusReview, setFocusReview] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  // Filter/sort state
  const [filters, setFilters] = useState<FilterState>({
    search: "",
    status: "all",
    type: "all",
    reviewStatus: "all",
    sort: "default",
  });

  const fetchTasks = useCallback(async () => {
    try {
      const data = await apiFetch<{ tasks: TaskRecord[] }>("/api/tasks");
      setTasks(data.tasks ?? []);
      setFetchError(null);
    } catch (err) {
      setFetchError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const handleStop = async () => {
    if (!selectedId) return;
    setStopping(true);
    try {
      await apiFetch<TaskRecord>(
        `/api/tasks/${encodeURIComponent(selectedId)}/stop`,
        { method: "POST" },
      );
      await fetchTasks();
    } catch (err) {
      alert(`Failed to stop task: ${err}`);
    } finally {
      setStopping(false);
    }
  };

  const handleRetry = async () => {
    if (!selectedId) return;
    setRetrying(true);
    try {
      const newTask = await apiFetch<TaskRecord>(
        `/api/tasks/${encodeURIComponent(selectedId)}/retry`,
        { method: "POST" },
      );
      setSelectedId(newTask.id);
      await fetchTasks();
    } catch (err) {
      alert(`Failed to retry task: ${err}`);
    } finally {
      setRetrying(false);
    }
  };

  const toggleRowExpansion = (taskId: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) {
        next.delete(taskId);
      } else {
        next.add(taskId);
      }
      return next;
    });
  };

  // Filter and sort logic
  const filtered = tasks.filter((task) => {
    // Search filter
    if (filters.search) {
      const search = filters.search.toLowerCase();
      const matches =
        task.id.toLowerCase().includes(search) ||
        task.description.toLowerCase().includes(search) ||
        (task.command ?? "").toLowerCase().includes(search) ||
        (task.prompt ?? "").toLowerCase().includes(search);
      if (!matches) return false;
    }
    // Status filter
    if (filters.status !== "all" && task.status !== filters.status) return false;
    // Type filter
    if (filters.type !== "all" && task.type !== filters.type) return false;
    // Review status filter
    if (filters.reviewStatus !== "all") {
      const reviewStatus = getReviewStatus(task.metadata);
      if (filters.reviewStatus === "reviewed") {
        if (reviewStatus !== "done") return false;
      } else if (filters.reviewStatus === "pending_review") {
        if (reviewStatus !== "in_progress" && reviewStatus !== "pending") return false;
      } else if (filters.reviewStatus === "no_review") {
        if (reviewStatus !== null) return false;
      }
    }
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    if (filters.sort === "newest") {
      return b.created_at - a.created_at;
    }
    return 0; // default order
  });

  const updateFilter = <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const clearFilters = () => {
    setFilters({ search: "", status: "all", type: "all", reviewStatus: "all", sort: "default" });
  };

  const hasActiveFilters = filters.search !== "" || filters.status !== "all" ||
    filters.type !== "all" || filters.reviewStatus !== "all";

  const runningCount = tasks.filter((t) => t.status === "running").length;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Page Header */}
      <PageHeader
        title="Background Jobs"
        description="Background CLI processes spawned by the system. Autopilot cards are managed in the Autopilot board."
        metadata={[
          { label: "Total", value: String(tasks.length) },
          {
            label: "Running",
            value: String(runningCount),
            accent: runningCount > 0 ? "cyan" : "none",
          },
        ]}
      />

      {/* Toolbar */}
      <div className="flex flex-col gap-3 border-b border-[var(--border)] bg-[var(--panel)] px-5 py-3">
        {/* Search row */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-dim)]">
              🔍
            </span>
            <input
              type="text"
              value={filters.search}
              onChange={(e) => updateFilter("search", e.target.value)}
              placeholder="Search jobs..."
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] py-2 pl-9 pr-4 text-sm text-[var(--text)] placeholder-[var(--text-dim)] focus:border-[var(--accent)]/60 focus:outline-none"
            />
          </div>
          <select
            value={filters.sort}
            onChange={(e) => updateFilter("sort", e.target.value as SortOrder)}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          >
            <option value="default">Default order</option>
            <option value="newest">Newest first</option>
          </select>
          <button
            onClick={fetchTasks}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] transition hover:border-[var(--accent)]/40"
          >
            Refresh
          </button>
        </div>

        {/* Filters row */}
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={filters.status}
            onChange={(e) => updateFilter("status", e.target.value as TaskStatus | "all")}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          >
            <option value="all">All statuses</option>
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </select>
          <select
            value={filters.type}
            onChange={(e) => updateFilter("type", e.target.value as TaskType | "all")}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          >
            <option value="all">All types</option>
            {ALL_TYPES.map((t) => (
              <option key={t} value={t}>{TYPE_LABELS[t]}</option>
            ))}
          </select>
          <select
            value={filters.reviewStatus}
            onChange={(e) => updateFilter("reviewStatus", e.target.value as FilterState["reviewStatus"])}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          >
            <option value="all">All reviews</option>
            <option value="reviewed">Reviewed</option>
            <option value="pending_review">Pending review</option>
            <option value="no_review">No review needed</option>
          </select>
          {hasActiveFilters && (
            <button
              onClick={clearFilters}
              className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text-dim)] transition hover:border-red-500/40 hover:text-red-300"
            >
              Clear filters
            </button>
          )}
          <span className="ml-auto rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1 text-xs text-[var(--text-dim)]">
            {sorted.length} jobs
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <span className="text-sm text-[var(--text-dim)]">Loading jobs…</span>
          </div>
        ) : fetchError ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {fetchError}
            </div>
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <div className="text-sm text-[var(--text-dim)]">
              {hasActiveFilters ? "No jobs match your filters." : "No jobs found."}
            </div>
          </div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--panel-2)]">
              <tr>
                <th className="w-8 px-2 py-2"></th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">ID</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Type</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Status</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Review</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Description</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Created</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((task) => {
                const isExpanded = expandedRows.has(task.id);
                const duration = task.ended_at && task.started_at
                  ? `${Math.round((task.ended_at - task.started_at))}s`
                  : task.started_at ? "running" : "—";
                const model = task.metadata["model"] ?? null;
                const provider = task.metadata["provider"] ?? null;
                return (
                  <React.Fragment key={task.id}>
                    <tr
                      onClick={() => { setFocusReview(false); setSelectedId(task.id); }}
                      className="cursor-pointer border-b border-[var(--border)] transition-colors hover:bg-[var(--panel-2)]/50"
                    >
                      <td className="px-2 py-3 text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); toggleRowExpansion(task.id); }}
                          className="rounded-md p-1 text-[var(--text-dim)] transition hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
                          aria-label={isExpanded ? "Collapse row" : "Expand row"}
                        >
                          {isExpanded ? "▼" : "▶"}
                        </button>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[var(--text-dim)]">
                        {truncateId(task.id)}
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--text)]">
                        {TYPE_LABELS[task.type] ?? task.type}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={task.status} />
                      </td>
                      <td className="px-4 py-3">
                        <ReviewBadge
                          status={getReviewStatus(task.metadata)}
                          onClick={(e) => { e.stopPropagation(); setFocusReview(true); setSelectedId(task.id); }}
                        />
                      </td>
                      <td className="px-4 py-3 text-[var(--text)]">
                        <span className="truncate max-w-xs block">{task.description || <span className="text-[var(--text-dim)]">—</span>}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-[var(--text-dim)]">
                        {formatTime(task.created_at)}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="border-b border-[var(--border)] bg-[var(--panel-2)]/30">
                        <td colSpan={7} className="px-6 py-4">
                          <div className="grid grid-cols-2 gap-4 text-xs">
                            {/* Duration */}
                            <div>
                              <div className="mb-1 font-medium text-[var(--text-dim)]">Duration</div>
                              <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 font-mono">
                                {duration}
                              </div>
                            </div>
                            {/* Model */}
                            {model && (
                              <div>
                                <div className="mb-1 font-medium text-[var(--text-dim)]">Model</div>
                                <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 font-mono">
                                  {model}
                                </div>
                              </div>
                            )}
                            {/* Provider */}
                            {provider && (
                              <div>
                                <div className="mb-1 font-medium text-[var(--text-dim)]">Provider</div>
                                <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 font-mono">
                                  {provider}
                                </div>
                              </div>
                            )}
                            {/* Prompt summary */}
                            {task.prompt && (
                              <div className="col-span-2">
                                <div className="mb-1 font-medium text-[var(--text-dim)]">Prompt summary</div>
                                <div className="truncate rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 font-mono text-[var(--text)]">
                                  {task.prompt.slice(0, 200)}{task.prompt.length > 200 ? "…" : ""}
                                </div>
                              </div>
                            )}
                            {/* Log preview */}
                            <div className="col-span-2">
                              <div className="mb-1 font-medium text-[var(--text-dim)]">Log preview</div>
                              <div className="max-h-32 overflow-auto rounded-lg border border-[var(--border)] bg-zinc-900 px-3 py-2 font-mono text-zinc-400">
                                <ButtonFetchLogPreview taskId={task.id} />
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail Drawer */}
      {selectedId && (
        <DetailDrawer
          taskId={selectedId}
          onClose={() => setSelectedId(null)}
          onStop={handleStop}
          onRetry={handleRetry}
          stopping={stopping}
          retrying={retrying}
          focusReview={focusReview}
        />
      )}
    </div>
  );
}