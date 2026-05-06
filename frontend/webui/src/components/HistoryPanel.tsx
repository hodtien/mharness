import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import HistoryDetailDrawer from "./HistoryDetailDrawer";
import HistoryCardSkeleton from "./HistoryCardSkeleton";

/**
 * Session metadata returned by `GET /api/history`.
 *
 * The shape mirrors the dicts produced by
 * `openharness.services.session_storage.list_session_snapshots`.
 */
export interface HistorySession {
  session_id: string;
  summary: string;
  model: string;
  message_count: number;
  /** Unix timestamp in seconds (float). */
  created_at: number;
}

interface HistoryPanelProps {
  /** Override the default `/api/history` endpoint (handy for tests). */
  endpoint?: string;
  /** Called when the user clicks "Resume" on a session. */
  onResume?: (session: HistorySession) => void;
  /**
   * Called after the detail-drawer's "Resume session" button has successfully
   * created a new session via `POST /api/sessions`. Receives the freshly
   * created session id and the original resumed-from id.
   */
  onResumeFromDrawer?: (newSessionId: string, resumeId: string) => void;
  /** Called after a session has been deleted server-side. */
  onDeleted?: (sessionId: string) => void;
  /** Called when the user clicks to view session transcript. */
  onDetailSelect?: (session: HistorySession) => void;
}

type LoadState = "loading" | "ready" | "error";

const HISTORY_ENDPOINT = "/api/history";

export function formatRelativeTime(createdAt: number): string {
  if (!createdAt || !Number.isFinite(createdAt)) return "—";

  const ms = createdAt < 1e12 ? createdAt * 1000 : createdAt;
  const diffSeconds = Math.max(0, Math.floor((Date.now() - ms) / 1000));

  if (diffSeconds < 60) return "just now";

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

/**
 * Returns a group label for a session timestamp:
 * - "Today" for sessions created today
 * - "Yesterday" for sessions created yesterday
 * - "X days ago" for 2-6 days
 * - "Last week" for 7-13 days
 * - Formatted date (e.g., "Jan 15, 2024") for older sessions
 */
export function getDateGroupLabel(createdAt: number): string {
  if (!createdAt || !Number.isFinite(createdAt)) return "Unknown";

  const ms = createdAt < 1e12 ? createdAt * 1000 : createdAt;
  const now = new Date();
  const sessionDate = new Date(ms);

  // Reset hours to compare dates only
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const sessionStart = new Date(
    sessionDate.getFullYear(),
    sessionDate.getMonth(),
    sessionDate.getDate(),
  );

  const diffDays = Math.floor(
    (todayStart.getTime() - sessionStart.getTime()) / (24 * 3600 * 1000),
  );

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays >= 2 && diffDays <= 6) return `${diffDays} days ago`;
  if (diffDays >= 7 && diffDays <= 13) return "Last week";

  // For older sessions, format as date
  return sessionDate.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

interface SessionGroup {
  label: string;
  sessions: HistorySession[];
}

/**
 * Group sessions by date for display with sticky headers.
 */
export function groupSessionsByDate(sessions: HistorySession[]): SessionGroup[] {
  const groups = new Map<string, HistorySession[]>();

  // Sort sessions by created_at descending (newest first)
  const sorted = [...sessions].sort((a, b) => b.created_at - a.created_at);

  for (const session of sorted) {
    const label = getDateGroupLabel(session.created_at);
    const existing = groups.get(label);
    if (existing) {
      existing.push(session);
    } else {
      groups.set(label, [session]);
    }
  }

  // Convert map to array, preserving chronological order
  const result: SessionGroup[] = [];
  const labelOrder = [
    "Today",
    "Yesterday",
    "2 days ago",
    "3 days ago",
    "4 days ago",
    "5 days ago",
    "6 days ago",
    "Last week",
  ];

  // Add known labels first
  for (const label of labelOrder) {
    const sessions = groups.get(label);
    if (sessions) {
      result.push({ label, sessions });
      groups.delete(label);
    }
  }

  // Add remaining groups (older dates) sorted by first session timestamp
  const remaining = Array.from(groups.entries())
    .map(([label, sessions]) => ({ label, sessions }))
    .sort((a, b) => b.sessions[0].created_at - a.sessions[0].created_at);

  result.push(...remaining);

  return result;
}

export default function HistoryPanel({
  endpoint = HISTORY_ENDPOINT,
  onResume,
  onResumeFromDrawer,
  onDeleted,
  onDetailSelect,
}: HistoryPanelProps) {
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<HistorySession | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadSessions = useCallback(
    async (signal?: AbortSignal) => {
      setState("loading");
      setError(null);
      try {
        const data = await apiFetch<HistorySession[] | { sessions: HistorySession[] }>(endpoint, { signal });
        const list: HistorySession[] = Array.isArray(data)
          ? data
          : Array.isArray((data as { sessions: HistorySession[] })?.sessions)
            ? (data as { sessions: HistorySession[] }).sessions
            : [];
        setSessions(list);
        setState("ready");
      } catch (err) {
        if ((err as { name?: string })?.name === "AbortError") return;
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      }
    },
    [endpoint],
  );

  useEffect(() => {
    const ctl = new AbortController();
    loadSessions(ctl.signal);
    return () => ctl.abort();
  }, [loadSessions]);

  const handleResume = useCallback(
    (session: HistorySession) => {
      onResume?.(session);
    },
    [onResume],
  );

  const handleDetailSelect = useCallback(
    (session: HistorySession) => {
      if (onDetailSelect) {
        onDetailSelect(session);
      }
      setSelectedSession(session);
    },
    [onDetailSelect],
  );

  const handleDelete = useCallback(
    async (session: HistorySession) => {
      if (busyId) return;
      const ok =
        typeof window !== "undefined" && typeof window.confirm === "function"
          ? window.confirm(`Delete session "${session.summary || session.session_id}"?`)
          : true;
      if (!ok) return;

      setBusyId(session.session_id);
      try {
        await apiFetch(`${endpoint}/${encodeURIComponent(session.session_id)}`, {
          method: "DELETE",
        });
        setSessions((prev) =>
          prev.filter((s) => s.session_id !== session.session_id),
        );
        onDeleted?.(session.session_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      } finally {
        setBusyId(null);
      }
    },
    [busyId, endpoint, onDeleted],
  );

  const closeDrawer = useCallback(() => {
    setSelectedSession(null);
  }, []);

  const handleDrawerResume = useCallback(
    (newSessionId: string, resumeId: string) => {
      onResumeFromDrawer?.(newSessionId, resumeId);
    },
    [onResumeFromDrawer],
  );

  const handleCopy = useCallback(
    (session: HistorySession) => {
      const ms = session.created_at < 1e12 ? session.created_at * 1000 : session.created_at;
      const createdAtStr = new Date(ms).toLocaleString();
      const text = [
        session.summary || "(no summary)",
        `Model: ${session.model || "—"}`,
        `Messages: ${session.message_count}`,
        `Created: ${createdAtStr}`,
      ].join("\n");

      navigator.clipboard.writeText(text).then(() => {
        setCopiedId(session.session_id);
        setTimeout(() => setCopiedId(null), 1500);
      });
    },
    [],
  );

  return (
    <>
    <section
      className="flex h-full w-full flex-col gap-3 p-4"
      aria-label="Session history"
    >
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--accent)]">
          History
        </h2>
        <button
          type="button"
          onClick={() => loadSessions()}
          disabled={state === "loading"}
          className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs hover:bg-[var(--panel)] disabled:opacity-50"
        >
          {state === "loading" ? "Loading…" : "Refresh"}
        </button>
      </header>

      {state === "loading" && sessions.length === 0 ? (
        <div role="status" aria-live="polite" aria-label="Loading history" className="flex flex-col gap-2">
          <span className="sr-only">Loading history…</span>
          {Array.from({ length: 3 }).map((_, index) => (
            <HistoryCardSkeleton key={index} />
          ))}
        </div>
      ) : null}

      {state === "error" ? (
        <div
          role="alert"
          className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200"
        >
          <div className="font-medium">Failed to load history</div>
          <div className="mt-1 break-words text-xs opacity-80">{error}</div>
          <button
            type="button"
            onClick={() => loadSessions()}
            className="mt-2 rounded-md border border-red-400/40 bg-red-500/10 px-2 py-1 text-xs hover:bg-red-500/20"
          >
            Retry
          </button>
        </div>
      ) : null}

      {state === "ready" && sessions.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-1 text-sm text-[var(--text-dim)]">
          <div className="text-base">No previous sessions</div>
          <div className="text-xs">
            Sessions you start will appear here once they have messages.
          </div>
        </div>
      ) : null}

      {sessions.length > 0 ? (
        <div className="flex flex-1 flex-col overflow-y-auto">
          {groupSessionsByDate(sessions).map((group) => (
            <div key={group.label} className="flex flex-col">
              <div className="sticky top-0 z-10 bg-[var(--panel-2)] px-2 py-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-dim)]">
                {group.label}
              </div>
              <ul className="flex flex-col gap-2 px-2 pb-4">
                {group.sessions.map((session) => {
                  const isBusy = busyId === session.session_id;
                  const summary = session.summary || "(no summary)";
                  const displaySummary =
                    summary.length > 60 ? `${summary.slice(0, 60)}…` : summary;
                  return (
                    <li
                      key={session.session_id}
                      className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium" title={summary}>
                            {displaySummary}
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--text-dim)]">
                            <span
                              title="Model"
                              className="rounded bg-[var(--accent-strong)]/20 px-1.5 py-0.5 text-[10px] font-medium text-[var(--text)]"
                            >
                              {session.model || "—"}
                            </span>
                            <span title="Message count">
                              {session.message_count} msg
                            </span>
                            <span title="Created at">
                              {formatRelativeTime(session.created_at)}
                            </span>
                          </div>
                        </div>
                        <div className="flex shrink-0 gap-2">
                          <button
                            type="button"
                            onClick={() => handleCopy(session)}
                            disabled={isBusy}
                            className="rounded-md border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-xs hover:bg-[var(--accent-strong)]/20 disabled:opacity-50"
                            title="Copy session info"
                          >
                            {copiedId === session.session_id ? "✓" : "📋"}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDetailSelect(session)}
                            disabled={isBusy}
                            className="rounded-md border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-xs hover:bg-[var(--accent-strong)]/20 disabled:opacity-50"
                          >
                            View
                          </button>
                          <button
                            type="button"
                            onClick={() => handleResume(session)}
                            disabled={isBusy}
                            className="rounded-md border border-[var(--border)] bg-[var(--panel)] px-2 py-1 text-xs hover:bg-[var(--accent-strong)]/20 disabled:opacity-50"
                          >
                            Resume
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(session)}
                            disabled={isBusy}
                            className="rounded-md border border-red-500/40 bg-red-500/10 px-2 py-1 text-xs text-red-200 hover:bg-red-500/20 disabled:opacity-50"
                          >
                            {isBusy ? "Deleting…" : "Delete"}
                          </button>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      ) : null}
    </section>
    <HistoryDetailDrawer
      session={selectedSession}
      onClose={closeDrawer}
      onResume={handleDrawerResume}
    />
    </>
  );
}
