import { useCallback, useEffect, useState } from "react";
import { api, apiFetch } from "../api/client";
import type { HistorySession } from "./HistoryPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ContentBlock {
  type: "text" | "tool_use" | "tool_result";
  text?: string;
  name?: string;
  content?: string;
  truncated?: boolean;
}

interface SnapshotMessage {
  role: "user" | "assistant";
  content: ContentBlock[] | string;
}

interface SessionSnapshot {
  session_id: string;
  model: string;
  cwd?: string;
  messages: SnapshotMessage[];
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  /** The history session to show detail for. When null the drawer is closed. */
  session: HistorySession | null;
  /** Called when the drawer should be dismissed. */
  onClose: () => void;
  /** Called with (newSessionId, resumeFromId) after Resume succeeds. */
  onResume: (sessionId: string, resumeId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function HistoryDetailDrawer({ session, onClose, onResume }: Props) {
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [resumeBusy, setResumeBusy] = useState(false);

  // Fetch detail whenever the selected session changes.
  useEffect(() => {
    if (!session) {
      setSnapshot(null);
      setLoadState("loading");
      setError(null);
      return;
    }

    const ctl = new AbortController();
    setLoadState("loading");
    setError(null);
    setSnapshot(null);

    apiFetch<SessionSnapshot>(`/api/history/${encodeURIComponent(session.session_id)}`, {
      signal: ctl.signal,
    })
      .then((data) => {
        setSnapshot(data);
        setLoadState("ready");
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === "AbortError") return;
        setError(err instanceof Error ? err.message : String(err));
        setLoadState("error");
      });

    return () => ctl.abort();
  }, [session]);

  // Escape key closes the drawer.
  useEffect(() => {
    if (!session) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [session, onClose]);

  const handleResume = useCallback(async () => {
    if (!session || resumeBusy) return;
    setResumeBusy(true);
    try {
      const { session_id } = await api.createSession(session.session_id);
      onResume(session_id, session.session_id);
    } finally {
      setResumeBusy(false);
    }
  }, [session, resumeBusy, onResume]);

  if (!session) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        data-testid="drawer-backdrop"
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={session.summary || "Session detail"}
        className="fixed right-0 top-0 z-50 flex h-full w-full flex-col border-l border-[var(--border)] bg-[var(--panel)] shadow-2xl sm:w-[480px] md:w-[560px]"
      >
        {/* Header */}
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold uppercase tracking-wider text-[var(--accent)]">
              Session transcript
            </div>
            <div className="mt-0.5 truncate text-sm font-medium" title={session.summary}>
              {session.summary || "(no summary)"}
            </div>
            <div className="mt-1 flex gap-x-3 text-xs text-[var(--text-dim)]">
              <span className="rounded bg-[var(--accent-strong)]/20 px-1.5 py-0.5 text-[10px] font-medium text-[var(--text)]">
                {session.model || "—"}
              </span>
              <span>{session.message_count} msg</span>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs hover:bg-[var(--panel)]"
          >
            ✕
          </button>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {loadState === "loading" && (
            <div
              role="status"
              aria-label="Loading session"
              aria-live="polite"
              className="flex flex-col gap-2"
            >
              <span className="sr-only">Loading session…</span>
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse h-14 rounded-lg border border-[var(--border)] bg-[var(--panel-2)]"
                />
              ))}
            </div>
          )}

          {loadState === "error" && (
            <div
              role="alert"
              className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200"
            >
              <div className="font-medium">Failed to load session</div>
              <div className="mt-1 break-words text-xs opacity-80">{error}</div>
            </div>
          )}

          {loadState === "ready" && snapshot && (
            <div className="flex flex-col gap-3">
              {snapshot.messages.map((msg, idx) => (
                <MessageBubble key={idx} message={msg} />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="shrink-0 border-t border-[var(--border)] px-4 py-3">
          <button
            type="button"
            onClick={handleResume}
            disabled={resumeBusy || loadState === "loading"}
            className="w-full rounded-md border border-[var(--accent-strong)]/50 bg-[var(--accent-strong)]/10 px-3 py-2 text-sm font-medium text-[var(--text)] hover:bg-[var(--accent-strong)]/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {resumeBusy ? "Resuming…" : "Resume session"}
          </button>
        </footer>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({ message }: { message: SnapshotMessage }) {
  const { role, content } = message;

  const blocks: ContentBlock[] = typeof content === "string"
    ? [{ type: "text", text: content }]
    : content;

  const textBlocks = blocks.filter((b) => b.type === "text" && b.text);
  const toolBlocks = blocks.filter((b) => b.type === "tool_use" || b.type === "tool_result");

  const isUser = role === "user";

  return (
    <div
      data-testid={`msg-${role}`}
      className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={`w-full max-w-[90%] rounded-2xl border px-3 py-2 text-sm leading-relaxed ${
          isUser
            ? "border-sky-500/40 bg-sky-500/10 text-sky-100"
            : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--assistant)]"
        }`}
      >
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider opacity-60">
          {role}
        </div>
        {textBlocks.map((b, i) => (
          <div key={i} className="whitespace-pre-wrap break-words">
            {b.text}
          </div>
        ))}
        {toolBlocks.map((b, i) => (
          <div
            key={i}
            className="mt-1 rounded border border-amber-400/30 bg-amber-500/5 px-2 py-1 text-xs text-amber-200"
          >
            <div className="mb-0.5 font-mono text-[10px] uppercase tracking-wider text-amber-300/80">
              {b.type === "tool_use" ? `tool · ${b.name || "?"}` : "tool result"}
            </div>
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px]">
              {b.content ?? b.text ?? ""}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}
