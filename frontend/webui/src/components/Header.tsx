import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useSession } from "../store/session";
import { formatRelativeTime, type HistorySession } from "./HistoryPanel";

interface Props {
  onToggleSidebar: () => void;
  onInterrupt: () => void;
  onResumeSession: (sessionId: string) => Promise<void> | void;
}

type LoadState = "idle" | "loading" | "ready" | "error";

const RECENT_HISTORY_ENDPOINT = "/api/history?limit=5";

function normalizeHistoryResponse(
  data: HistorySession[] | { sessions?: HistorySession[] },
): HistorySession[] {
  if (Array.isArray(data)) return data;
  return Array.isArray(data.sessions) ? data.sessions : [];
}

function SessionsDropdown({ onResumeSession }: Pick<Props, "onResumeSession">) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<LoadState>("idle");
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resumingId, setResumingId] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  const loadSessions = useCallback(async (signal?: AbortSignal) => {
    setState("loading");
    setError(null);
    try {
      const data = await apiFetch<HistorySession[] | { sessions?: HistorySession[] }>(
        RECENT_HISTORY_ENDPOINT,
        { signal },
      );
      setSessions(normalizeHistoryResponse(data).slice(0, 5));
      setState("ready");
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      setError(err instanceof Error ? err.message : String(err));
      setState("error");
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const ctl = new AbortController();
    loadSessions(ctl.signal);
    return () => ctl.abort();
  }, [loadSessions, open]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!dropdownRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const handleResume = useCallback(
    async (sessionId: string) => {
      if (resumingId) return;
      setResumingId(sessionId);
      setError(null);
      try {
        await onResumeSession(sessionId);
        setOpen(false);
        navigate("/chat");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      } finally {
        setResumingId(null);
      }
    },
    [navigate, onResumeSession, resumingId],
  );

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
      >
        Sessions ▾
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="Recent sessions"
          className="absolute left-0 z-30 mt-2 w-72 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--panel)] shadow-xl"
        >
          <div className="border-b border-[var(--border)] px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--accent)]">
            Recent sessions
          </div>

          {state === "loading" ? (
            <div role="status" className="px-3 py-4 text-sm text-[var(--text-dim)]">
              Loading…
            </div>
          ) : null}

          {state === "error" ? (
            <div role="alert" className="px-3 py-3 text-xs text-rose-300">
              <div className="font-medium">Failed to load sessions</div>
              <div className="mt-1 break-words opacity-80">{error}</div>
              <button
                type="button"
                onClick={() => loadSessions()}
                className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 hover:bg-rose-500/20"
              >
                Retry
              </button>
            </div>
          ) : null}

          {state === "ready" && sessions.length === 0 ? (
            <div className="px-3 py-4 text-sm text-[var(--text-dim)]">
              No recent sessions
            </div>
          ) : null}

          {sessions.length > 0 ? (
            <ul className="max-h-80 overflow-y-auto py-1">
              {sessions.map((session) => {
                const summary = session.summary || "(no summary)";
                const displaySummary =
                  summary.length > 40 ? `${summary.slice(0, 40)}…` : summary;
                const isResuming = resumingId === session.session_id;
                return (
                  <li key={session.session_id}>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={Boolean(resumingId)}
                      onClick={() => handleResume(session.session_id)}
                      className="flex w-full flex-col gap-1 px-3 py-2 text-left hover:bg-[var(--panel-2)] disabled:opacity-60"
                    >
                      <span className="w-full truncate text-sm font-medium" title={summary}>
                        {isResuming ? "Resuming…" : displaySummary}
                      </span>
                      <span className="flex gap-2 text-[11px] text-[var(--text-dim)]">
                        <span>{session.model || "—"}</span>
                        <span>{session.message_count} msg</span>
                        <span>{formatRelativeTime(session.created_at)}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}

          <div className="border-t border-[var(--border)] p-2">
            <Link
              to="/history"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block rounded-md px-2 py-1.5 text-center text-xs text-[var(--accent)] hover:bg-[var(--panel-2)]"
            >
              View all
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function Header({ onToggleSidebar, onInterrupt, onResumeSession }: Props) {
  const { appState, connectionStatus, busy, errorBanner } = useSession();
  const dotColor =
    connectionStatus === "open"
      ? "bg-emerald-400"
      : connectionStatus === "connecting"
        ? "bg-amber-400"
        : "bg-rose-500";

  return (
    <div className="flex flex-col border-b border-[var(--border)] bg-[var(--panel)]">
      <div className="flex items-center gap-3 px-3 py-2 sm:px-5">
        <button
          aria-label="Toggle sidebar"
          onClick={onToggleSidebar}
          className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-sm text-[var(--text-dim)] hover:text-[var(--text)]"
        >
          ☰
        </button>
        <div className="flex flex-1 items-center gap-2 min-w-0">
          <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
          <span className="truncate text-sm font-semibold tracking-wide">
            OpenHarness
          </span>
          <SessionsDropdown onResumeSession={onResumeSession} />
          <span className="hidden truncate text-xs text-[var(--text-dim)] sm:inline">
            {appState?.model ? `· ${appState.model}` : ""}
            {appState?.cwd ? ` · ${appState.cwd}` : ""}
            {appState?.permission_mode ? ` · ${appState.permission_mode}` : ""}
          </span>
        </div>
        {busy && (
          <button
            onClick={onInterrupt}
            className="rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs text-rose-300 hover:bg-rose-500/20"
          >
            Stop
          </button>
        )}
      </div>
      {errorBanner && (
        <div className="bg-rose-500/15 px-3 py-1 text-xs text-rose-300 sm:px-5">
          {errorBanner}
        </div>
      )}
      {/* Mobile-only second-line meta */}
      <div className="px-3 pb-2 text-[11px] text-[var(--text-dim)] sm:hidden">
        {appState?.model || "?"} · {appState?.permission_mode || "default"}
      </div>
    </div>
  );
}
