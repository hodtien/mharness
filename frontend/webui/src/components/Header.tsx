import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type ModelProfile } from "../api/client";
import { useSession } from "../store/session";
import ChangePasswordModal from "./ChangePasswordModal";

type PermissionMode = "default" | "plan" | "full_auto";

// Connection status badge colors
const CONNECTION_COLORS: Record<string, string> = {
  open: "bg-emerald-400",
  connecting: "bg-amber-400",
  closed: "bg-rose-500",
};

// Runtime state badge: shows model, provider, job count, busy status
export function ModelPicker() {
  const [open, setOpen] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [models, setModels] = useState<Record<string, ModelProfile[]>>({});
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const appState = useSession((s) => s.appState);
  const { ingest } = useSession();

  const current = appState?.model ?? "";

  // Fetch models when dropdown opens
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setLoadError(null);
    api
      .listModels()
      .then(setModels)
      .catch((error: unknown) => {
        setLoadError(error instanceof Error ? error.message : "Failed to load models");
      })
      .finally(() => setLoading(false));
  }, [open]);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open && searchRef.current) {
      setTimeout(() => searchRef.current?.focus(), 50);
    }
  }, [open]);

  // Close on outside click / Escape
  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!dropdownRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  // Resolve models from the active profile first, then fall back to provider.
  const query = search.trim().toLowerCase();
  const activeProfile = appState?.active_profile || appState?.provider || "";
  const providerItems = activeProfile ? models[activeProfile] ?? [] : [];
  const fallbackItems = !providerItems.length && appState?.provider ? models[appState.provider] ?? [] : [];
  const availableModels = providerItems.length ? providerItems : fallbackItems;
  const filtered = query
    ? availableModels.filter((m) => `${m.id} ${m.label}`.toLowerCase().includes(query))
    : availableModels;
  const totalModels = availableModels.length;

  const selectModel = useCallback(
    async (modelId: string) => {
      if (updating || modelId === current) {
        setOpen(false);
        setSearch("");
        return;
      }
      setUpdating(true);
      ingest({ type: "state_snapshot", state: { ...appState, model: modelId } });
      setOpen(false);
      setSearch("");
      try {
        await api.patchModes({ model: modelId });
      } catch {
        ingest({ type: "state_snapshot", state: { ...appState, model: current } });
      } finally {
        setUpdating(false);
      }
    },
    [updating, current, appState, ingest],
  );

  if (!current) return null;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => !updating && setOpen((v) => !v)}
        className={`inline-flex min-h-9 max-w-[10rem] items-center gap-1.5 rounded border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs font-medium text-[var(--text)] hover:brightness-125 ${updating ? "opacity-60" : ""}`}
      >
        <span className="truncate">{current}</span>
        <span aria-hidden className="text-[10px] opacity-60">▾</span>
      </button>

      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1.5 w-72 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--panel)] shadow-xl">
          {/* Search */}
          <div className="border-b border-[var(--border)] p-2">
            <div className="relative">
              <span className="pointer-events-none absolute inset-y-0 left-2.5 flex items-center text-[var(--text-dim)]">
                🔍
              </span>
              <input
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={loading ? "Loading models…" : `Search ${totalModels} models…`}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--panel-2)] py-1.5 pl-8 pr-3 text-xs text-[var(--text)] placeholder-[var(--text-dim)] outline-none focus:border-cyan-400/50"
              />
            </div>
          </div>

          {/* List */}
          <div className="max-h-56 overflow-y-auto py-1">
            {loading ? (
              <div className="px-3 py-4 text-center text-xs text-[var(--text-dim)]">Loading…</div>
            ) : loadError ? (
              <div className="px-3 py-4 text-center text-xs text-rose-400">
                Could not load models — {loadError}
              </div>
            ) : filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-[var(--text-dim)]">
                {query
                  ? `No models match "${query}"`
                  : totalModels === 0
                    ? activeProfile
                      ? `No models available for ${activeProfile}`
                      : "No models found for this provider profile. Check your provider settings."
                    : "No models available"}
              </div>
            ) : (
              filtered.map((m) => {
                const active = m.id === current;
                const label = m.label && m.label !== m.id ? `${m.label} (${m.id})` : m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    onClick={() => selectModel(m.id)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition ${active ? "bg-cyan-400/10 text-cyan-200" : "hover:bg-[var(--panel-2)] text-[var(--text)]"}`}
                  >
                    <span className="flex-1 truncate">{label}</span>
                    {active ? <span className="text-[10px] opacity-60">✓</span> : null}
                  </button>
                );
              })
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RuntimeSummary({ onMobileMenuToggle }: { onMobileMenuToggle: () => void }) {
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
      {appState?.model && (
        <button
          type="button"
          aria-label="Open runtime controls"
          onClick={onMobileMenuToggle}
          className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded border border-[var(--border)] bg-[var(--panel-2)] px-2 text-xs font-medium text-[var(--text)] hover:brightness-125 sm:hidden"
        >
          <span className="truncate max-w-[86px]">{appState.model}</span>
          <span aria-hidden className="text-[10px] opacity-60">▾</span>
        </button>
      )}
      {appState?.provider && (
        <span className="hidden md:inline rounded border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5">
          {appState.provider}
        </span>
      )}
      {hasJobs && (
        <span className="flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
          <span aria-hidden>⚡</span>
          <span>{runningCount} job{runningCount !== 1 ? "s" : ""}</span>
        </span>
      )}
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
        className={`inline-flex min-h-9 items-center gap-1.5 rounded-md border border-[var(--border)] px-2 py-1 text-xs font-medium text-[var(--text)] hover:brightness-125 ${updating ? "opacity-60" : ""}`}
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
  isDefaultPassword?: boolean;
  onLogout?: () => void;
  onPasswordChanged?: () => void;
}

export default function Header({
  onToggleSidebar,
  onInterrupt,
  isDefaultPassword = false,
  onLogout = () => {},
  onPasswordChanged = () => {},
}: Props) {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project");
  const historyTo = projectId ? `/history?project=${encodeURIComponent(projectId)}` : "/history";
  const connectionStatus = useSession((s) => s.connectionStatus);
  const busy = useSession((s) => s.busy);
  const errorBanner = useSession((s) => s.errorBanner);
  const tasks = useSession((s) => s.tasks);
  const appState = useSession((s) => s.appState);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);

  const dotColor = CONNECTION_COLORS[connectionStatus] ?? CONNECTION_COLORS.closed;

  // Running tasks count for interrupt label
  const runningCount = tasks.filter(
    (t) => t.status === "running" || t.status === "queued",
  ).length;

  const currentModel = appState?.model;
  const currentProvider = appState?.provider;

  return (
    <div className="flex flex-col border-b border-[var(--border)] bg-[var(--panel)]">
      <div className="flex min-w-0 items-center gap-2 px-3 py-2 sm:px-5">
        <button
          aria-label="Toggle sidebar"
          onClick={onToggleSidebar}
          className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-sm text-[var(--text-dim)] hover:text-[var(--text)]"
        >
          ☰
        </button>

        <div className="flex min-w-0 items-center gap-1.5">
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${dotColor}`} />
          <span className="truncate text-sm font-semibold tracking-wide">OpenHarness</span>
        </div>

        <div className="hidden sm:flex items-center gap-2">
          <Link
            to={historyTo}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
          >
            History
          </Link>

          <PermissionModeChip />
        </div>

        <div className="min-w-0 flex-1" />

        <RuntimeSummary onMobileMenuToggle={() => setMobileMenuOpen((v) => !v)} />

        {busy && (
          <button
            onClick={onInterrupt}
            aria-label={runningCount > 0 ? `Stop ${runningCount} running job(s)` : "Stop current task"}
            className="shrink-0 flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs text-rose-300 hover:bg-rose-500/20"
          >
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />
            <span>Stop{runningCount > 0 ? ` (${runningCount})` : ""}</span>
          </button>
        )}

        {isDefaultPassword && (
          <button
            type="button"
            onClick={() => setChangePasswordOpen(true)}
            className="hidden shrink-0 items-center rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200 hover:bg-amber-500/20 md:inline-flex"
          >
            Default password
          </button>
        )}

        <button
          type="button"
          onClick={() => setChangePasswordOpen(true)}
          className="hidden shrink-0 items-center rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:text-[var(--text)] sm:inline-flex"
        >
          Password
        </button>

        <button
          type="button"
          onClick={onLogout}
          className="shrink-0 rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
        >
          Logout
        </button>
      </div>

      {mobileMenuOpen && (
        <div className="border-t border-[var(--border)] bg-[var(--panel)] px-3 py-2 sm:hidden">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={historyTo}
              className="inline-flex min-h-9 items-center rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
            >
              History
            </Link>
            <PermissionModeChip />
            {currentProvider && (
              <span className="inline-flex min-h-9 items-center rounded border border-[var(--border)] bg-[var(--panel-2)] px-2.5 text-xs text-[var(--text-dim)]">
                {currentProvider}
              </span>
            )}
            {currentModel && <ModelPicker />}
            {isDefaultPassword && (
              <button
                type="button"
                onClick={() => setChangePasswordOpen(true)}
                className="inline-flex min-h-9 items-center rounded-md border border-amber-500/30 bg-amber-500/10 px-3 text-xs text-amber-200 hover:bg-amber-500/20"
              >
                Default password
              </button>
            )}
            <button
              type="button"
              onClick={() => setChangePasswordOpen(true)}
              className="inline-flex min-h-9 items-center rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 text-xs text-[var(--text-dim)] hover:text-[var(--text)]"
            >
              Password
            </button>
          </div>
        </div>
      )}

      {errorBanner && (
        <div className="bg-rose-500/15 px-3 py-1 text-xs text-rose-300 sm:px-5">
          {errorBanner}
        </div>
      )}
      <ChangePasswordModal
        open={changePasswordOpen}
        onClose={() => setChangePasswordOpen(false)}
        onChanged={onPasswordChanged}
      />
    </div>
  );
}
