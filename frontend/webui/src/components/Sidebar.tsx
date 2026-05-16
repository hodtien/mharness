import { useEffect, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";
import { api, type SchedulerDiagnosticsResponse } from "../api/client";
import ProjectSelector from "./ProjectSelector";
import { useSession } from "../store/session";
import { getAuthSemanticState } from "../utils/authStatusSemantics";
import { formatSchedulerDiagnostics, formatCronStatus } from "../utils/schedulerDiagnostics";

const STATUS_COLLAPSED_KEY = "oh:sidebar:status-collapsed";

type IconName =
  | "chat"
  | "history"
  | "autopilot"
  | "jobs"
  | "projects"
  | "control"
  | "docs"
  | "caretDown"
  | "caretUp";

interface Props {
  open: boolean;
  onClose: () => void;
  collapsed?: boolean;
}

export default function Sidebar({ open, onClose, collapsed = false }: Props) {
  const tasks = useSession((s) => s.tasks);
  const appState = useSession((s) => s.appState);
  const [diagnostics, setDiagnostics] = useState<SchedulerDiagnosticsResponse | null>(null);
  const [statusCollapsed, setStatusCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STATUS_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    api
      .getSchedulerDiagnostics()
      .then(setDiagnostics)
      .catch(() => setDiagnostics(null));
  }, [tasks.length]);

  const schedulerDisplay = formatSchedulerDiagnostics(diagnostics);
  const cronDisplay = formatCronStatus(diagnostics);
  const runningJobs = tasks.filter((t) =>
    ["running", "active", "in_progress"].includes(t.status),
  ).length;
  const failedJobs = tasks.filter((t) =>
    ["failed", "error"].includes(t.status),
  ).length;
  const mcpFailed = appState?.mcp_failed ?? 0;

  /** A brief "pulse" dot shown next to Control when there's something to notice */
  const controlAlert = failedJobs > 0 || mcpFailed > 0;

  const content = (
    <div className="flex h-full w-72 flex-col gap-3 overflow-y-auto border-r border-[var(--border)] bg-[var(--panel)] p-3">
      {/* ── Project ─────────────────────────────────── */}
      <Section title="Project">
        <ProjectSelector />
      </Section>

      {/* ── Primary navigation ──────────────────────── */}
      <Section title="Navigate">
        <nav aria-label="Primary" className="flex flex-col gap-1">
          <NavItem to="/chat" label="Chat" icon="chat" onClose={onClose} />
          <NavItem to="/autopilot" label="Autopilot" icon="autopilot" onClose={onClose} />
          <NavItem to="/projects" label="Projects" icon="projects" onClose={onClose} />
          <NavItem to="/history" label="History" icon="history" onClose={onClose} />
          <NavItem to="/tasks" label="Jobs" icon="jobs" onClose={onClose} />
        </nav>
      </Section>

      {/* ── Control Center entry ─────────────────────── */}
      <Section title="Control">
        <ControlEntry alert={controlAlert} onClose={onClose} />
      </Section>

      {/* ── Operational status (collapsible) ─────────── */}
      <Section
        title={
          <button
            onClick={() =>
              setStatusCollapsed((v) => {
                const next = !v;
                try {
                  localStorage.setItem(STATUS_COLLAPSED_KEY, String(next));
                } catch {}
                return next;
              })
            }
            className="flex w-full items-center justify-between gap-2 text-left"
            aria-expanded={!statusCollapsed}
            aria-label={
              statusCollapsed
                ? "Expand system status section"
                : "Collapse system status section"
            }
          >
            <span>Status</span>
            <Icon name={statusCollapsed ? "caretDown" : "caretUp"} />
          </button>
        }
      >
        {!statusCollapsed && (
          <div className="sidebar-status-group">
            <StatusField
              label="Runtime"
              value={appState?.model ?? "—"}
            />
            <StatusField
              label="Provider"
              value={appState?.provider ?? "—"}
            />
            <StatusField
              label="Access"
              value={getAuthSemanticState(appState?.auth_status).label}
              tone={getAuthSemanticState(appState?.auth_status).tone}
            />
            <StatusField
              label="Jobs"
              value={`${runningJobs} running / ${failedJobs} failed`}
              tone={failedJobs > 0 ? "danger" : runningJobs > 0 ? "warning" : "success"}
            />
            <StatusField
              label={schedulerDisplay.label}
              value={schedulerDisplay.value}
              tone={schedulerDisplay.tone}
            />
            <StatusField
              label={cronDisplay.label}
              value={cronDisplay.value}
              tone={cronDisplay.tone}
            />
            <StatusField
              label="Feature"
              value={diagnostics?.scheduling_feature_enabled ? "enabled" : "disabled"}
              tone={diagnostics?.scheduling_feature_enabled ? "success" : "neutral"}
            />
            <StatusField
              label="MCP"
              value={`${appState?.mcp_connected ?? 0} ok / ${mcpFailed} fail`}
              tone={mcpFailed > 0 ? "danger" : "success"}
            />
          </div>
        )}
      </Section>

      {/* ── Docs link ──────────────────────────────── */}
      <a
        href="https://github.com/hodtien/openharness/tree/main/docs"
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] text-[var(--text-dim)] transition hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
        style={{
          textDecoration: "none",
          borderWidth: "1px",
          borderStyle: "solid",
          borderColor: "transparent",
        }}
        aria-label="Open documentation"
      >
        <Icon name="docs" />
        <span>Docs</span>
      </a>
    </div>
  );

  return (
    <>
      <div
        data-testid="sidebar-desktop"
        className={`${collapsed ? "hidden" : "hidden sm:block"} h-full`}
      >
        {content}
      </div>
      {open && (
        <div
          data-testid="sidebar-mobile"
          className="fixed inset-0 z-30 flex sm:hidden"
        >
          {content}
          <div
            data-testid="sidebar-mobile-backdrop"
            className="flex-1 bg-black/40"
            onClick={onClose}
          />
        </div>
      )}
    </>
  );
}

// ── Control Center entry ────────────────────────────────────────────────────

function ControlEntry({ alert, onClose }: { alert: boolean; onClose: () => void }) {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project");
  const to = projectId ? `/settings?project=${encodeURIComponent(projectId)}` : "/settings";
  return (
    <NavLink
      to={to}
      onClick={onClose}
      className={({ isActive }) =>
        `sidebar-nav-link flex items-center gap-1.5 rounded-md border px-2 text-[13px] transition ${
          isActive
            ? "border-[var(--accent-strong)]/40 bg-[var(--accent-bg)] text-[var(--accent)]"
            : "border-transparent text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
        }`
      }
      aria-label="Control Center"
    >
      <span aria-hidden="true" className="sidebar-nav-icon">
        <Icon name="control" />
      </span>
      <span>Control</span>
      {alert && (
        <span
          className="ml-auto h-1.5 w-1.5 rounded-full bg-[var(--error)]"
          aria-hidden="true"
        />
      )}
    </NavLink>
  );
}

// ── NavItem ─────────────────────────────────────────────────────────────────

function NavItem({
  to,
  label,
  icon,
  onClose,
}: {
  to: string;
  label: string;
  icon: IconName;
  onClose: () => void;
}) {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project");
  const target = projectId ? `${to}?project=${encodeURIComponent(projectId)}` : to;
  return (
    <NavLink
      to={target}
      end
      onClick={onClose}
      className={({ isActive }) =>
        `sidebar-nav-link flex items-center gap-1.5 rounded-md border px-2 text-[13px] transition ${
          isActive
            ? "border-[var(--accent-strong)]/40 bg-[var(--accent-bg)] text-[var(--accent)]"
            : "border-transparent text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
        }`
      }
      aria-label={label}
      title={label}
    >
      <span aria-hidden="true" className="sidebar-nav-icon">
        <Icon name={icon} />
      </span>
      <span>{label}</span>
    </NavLink>
  );
}

// ── Icon ─────────────────────────────────────────────────────────────────────

function Icon({ name }: { name: IconName }) {
  const glyph: Record<IconName, string> = {
    chat: "◉",
    history: "◷",
    autopilot: "⬢",
    jobs: "◍",
    projects: "▣",
    control: "◧",
    docs: "◫",
    caretDown: "▾",
    caretUp: "▴",
  };
  return <span aria-hidden="true">{glyph[name]}</span>;
}

// ── Section ───────────────────────────────────────────────────────────────────

function Section({
  title,
  children,
}: {
  title: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="sidebar-section-title">{title}</div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

// ── StatusField ───────────────────────────────────────────────────────────────

type Tone = "success" | "danger" | "warning" | "neutral";
function StatusField({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value?: string | number;
  tone?: Tone;
}) {
  const pillClass =
    tone === "success"
      ? "status-pill status-pill-success"
      : tone === "danger"
        ? "status-pill status-pill-danger"
        : tone === "warning"
          ? "status-pill status-pill-warning"
          : "status-pill";
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-[var(--text-dim)]">{label}</span>
      <span className={pillClass}>{value ?? "—"}</span>
    </div>
  );
}
