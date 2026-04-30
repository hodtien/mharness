import { useSession } from "../store/session";

interface Props {
  onToggleSidebar: () => void;
  onInterrupt: () => void;
}

export default function Header({ onToggleSidebar, onInterrupt }: Props) {
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
