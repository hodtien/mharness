import { useCallback, useEffect, useState } from "react";

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
  /** Called after a session has been deleted server-side. */
  onDeleted?: (sessionId: string) => void;
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

async function readError(res: Response): Promise<string> {
  try {
    const text = await res.text();
    return text || `${res.status} ${res.statusText}`;
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export default function HistoryPanel({
  endpoint = HISTORY_ENDPOINT,
  onResume,
  onDeleted,
}: HistoryPanelProps) {
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadSessions = useCallback(
    async (signal?: AbortSignal) => {
      setState("loading");
      setError(null);
      try {
        const res = await fetch(endpoint, { signal });
        if (!res.ok) {
          throw new Error(await readError(res));
        }
        const data = await res.json();
        const list: HistorySession[] = Array.isArray(data)
          ? data
          : Array.isArray(data?.sessions)
            ? data.sessions
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
        const res = await fetch(
          `${endpoint}/${encodeURIComponent(session.session_id)}`,
          { method: "DELETE" },
        );
        if (!res.ok) {
          throw new Error(await readError(res));
        }
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

  return (
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
        <div role="status" aria-live="polite" className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="animate-pulse h-16 rounded-lg border border-[var(--border)] bg-[var(--panel-2)]"
            />
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
        <ul className="flex flex-1 flex-col gap-2 overflow-y-auto">
          {sessions.map((session) => {
            const isBusy = busyId === session.session_id;
            const summary = session.summary || "(no summary)";
            return (
              <li
                key={session.session_id}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium" title={summary}>
                      {summary.length > 60 ? summary.slice(0, 60) + "…" : summary}
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
      ) : null}
    </section>
  );
}
