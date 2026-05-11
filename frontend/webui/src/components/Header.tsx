import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../store/session";

type PermissionMode = "default" | "plan" | "full_auto";

// Connection status badge colors
const CONNECTION_COLORS: Record<string, string> = {
  open: "bg-emerald-400",
  connecting: "bg-amber-400",
  closed: "bg-rose-500",
};

// Runtime state badge: shows model, provider, job count, busy status
function RuntimeSummary() {
  const appState = useSession((s) => s.appState);
  const tasks = useSession((s) => s.tasks);
  const busy = useSession((s) => s.busy);
  const busyLabel = useSession((s) => s.transcript[s.transcript.length - 1]?.tool_name);

  const runningCount = tasks.filter(
    (t) => t.status === "running" || t.status === "queued",
  ).length;

  const hasJobs = runningCount > 0;

  return (
    <div className="flex items-center gap-1.5 text-xs text-[var(--text-dim)]">
      {/* Model badge */}
      {appState?.model && (
        <span className="rounded border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5 font-medium text-[var(--text)]">
          {appState.model}
        </span>
      )}
      {/* Provider badge (tablet+) */}
      {appState?.provider && (
        <span className="hidden md:inline rounded border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5">
          {appState.provider}
        </span>
      )}
      {/* Running jobs badge */}
      {hasJobs && (
        <span className="flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
          <span aria-hidden>⚡</span>
          <span>{runningCount} job{runningCount !== 1 ? "s" : ""}</span>
        </span>
      )}
      {/* Busy indicator */}
      {busy && (
        <span className="flex items-center gap-1 rounded border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.5 text-rose-300">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />
          <span className="truncate max-w-[120px]">
            {busyLabel ? `Running ${busyLabel}` : "Busy"}
          </span>
        </span>
      )}
    </div>
  );
}

const permissionOptions: Array<{ value: PermissionMode; label: string; color: string }> = [
  { value: "default", label: "DEFAULT", color: "bg-[var(--text-dim)]" },
  { value: "plan", label: "PLAN", color: "bg-[var(--accent)]" },
  { value: "full_auto", label: "AUTO", color: "bg-[var(--status-pending-text)]" },
];

export function PermissionModeChip() {
  const [open, setOpen] = useState(false);
  const [updating, setUpdating] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const { appState, ingest } = useSession();

  const current = (appState?.permission_mode as PermissionMode) || "default";
  const option = permissionOptions.find((o) => o.value === current) || permissionOptions[0];

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

  const selectMode = useCallback(
    async (mode: PermissionMode) => {
      if (updating || mode === current) {
        setOpen(false);
        return;
      }
      setUpdating(true);
      // Optimistic update via session ingest
      ingest({ type: "state_snapshot", state: { ...appState, permission_mode: mode } });
      setOpen(false);
      try {
        await api.patchModes({ permission_mode: mode });
      } catch {
        // Revert on failure
        ingest({ type: "state_snapshot", state: { ...appState, permission_mode: current } });
      } finally {
        setUpdating(false);
      }
    },
    [updating, current, appState, ingest],
  );

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => !updating && setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] px-2 py-1 text-xs font-medium text-[var(--text)] hover:brightness-125 ${updating ? "opacity-60" : ""}`}
      >
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${option.color}`} />
        {option.label}
        ▾
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="Permission mode"
          className="absolute right-0 z-30 mt-2 w-36 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--panel)] shadow-xl"
        >
          {permissionOptions.map((opt) => {
            const active = opt.value === current;
            return (
              <button
                key={opt.value}
                type="button"
                role="menuitem"
                onClick={() => selectMode(opt.value)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition ${active ? "bg-cyan-400/10 text-cyan-200" : "hover:bg-[var(--panel-2)] text-[var(--text)]"}`}
              >
                <span className={`inline-block h-2 w-2 rounded-full ${opt.color}`} />
                {opt.label}
                {active ? <span className="ml-auto text-[10px] opacity-60">✓</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

interface Props {
  onToggleSidebar: () => void;
  onInterrupt: () => void;
}

export default function Header({ onToggleSidebar, onInterrupt }: Props) {
  const connectionStatus = useSession((s) => s.connectionStatus);
  const busy = useSession((s) => s.busy);
  const errorBanner = useSession((s) => s.errorBanner);
  const tasks = useSession((s) => s.tasks);

  const dotColor = CONNECTION_COLORS[connectionStatus] ?? CONNECTION_COLORS.closed;

  // Running tasks count for interrupt label
  const runningCount = tasks.filter(
    (t) => t.status === "running" || t.status === "queued",
  ).length;

  return (
    <div className="flex flex-col border-b border-[var(--border)] bg-[var(--panel)]">
      <div className="flex items-center gap-2 px-3 py-2 sm:px-5">
        <button
          aria-label="Toggle sidebar"
          onClick={onToggleSidebar}
          className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-sm text-[var(--text-dim)] hover:text-[var(--text)]"
        >
          ☰
        </button>

        {/* Connection dot + brand */}
        <div className="flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
          <span className="truncate text-sm font-semibold tracking-wide">OpenHarness</span>
        </div>

        <Link
          to="/history"
          className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
        >
          History
        </Link>

        {/* Permission mode chip */}
        <PermissionModeChip />

        {/* Runtime summary: model, provider, jobs, busy */}
        <RuntimeSummary />

        <div className="flex-1" />

        {/* Busy: primary interrupt action with running count label */}
        {busy && (
          <button
            onClick={onInterrupt}
            aria-label={runningCount > 0 ? `Stop ${runningCount} running job(s)` : "Stop current task"}
            className="flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs text-rose-300 hover:bg-rose-500/20"
          >
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />
            <span>Stop{runningCount > 0 ? ` (${runningCount})` : ""}</span>
          </button>
        )}
      </div>

      {/* Error banner */}
      {errorBanner && (
        <div className="bg-rose-500/15 px-3 py-1 text-xs text-rose-300 sm:px-5">
          {errorBanner}
        </div>
      )}
    </div>
  );
}
