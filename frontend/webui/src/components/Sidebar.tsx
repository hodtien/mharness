import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import ProjectSelector from "./ProjectSelector";
import { useSession } from "../store/session";

const SETTINGS_COLLAPSED_KEY = "oh:sidebar:settings-collapsed";

interface Props {
  open: boolean;
  onClose: () => void;
  /** When true, hide the persistent desktop sidebar. Mobile drawer is unaffected. */
  collapsed?: boolean;
}

export default function Sidebar({ open, onClose, collapsed = false }: Props) {
  const tasks = useSession((s) => s.tasks);
  const appState = useSession((s) => s.appState);
  const todoMarkdown = useSession((s) => s.todoMarkdown);
  const compact = useSession((s) => s.compact);
  const planMode = useSession((s) => s.planMode);
  const swarm = useSession((s) => s.swarm);
  const [cron, setCron] = useState<Array<Record<string, unknown>>>([]);
  const [settingsCollapsed, setSettingsCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SETTINGS_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const toggleSettings = () => {
    const next = !settingsCollapsed;
    setSettingsCollapsed(next);
    try {
      localStorage.setItem(SETTINGS_COLLAPSED_KEY, String(next));
    } catch {
      // ignore storage errors
    }
  };

  useEffect(() => {
    api
      .listCron()
      .then((d) => setCron(d.jobs || []))
      .catch(() => setCron([]));
  }, [tasks.length]);

  const content = (
    <div className="flex h-full w-72 flex-col gap-3 overflow-y-auto border-r border-[var(--border)] bg-[var(--panel)] p-3">
      <ProjectSelector />

      <nav aria-label="Primary" className="flex flex-col gap-2">
        <NavItem to="/chat" label="Chat" icon="💬" onClose={onClose} />
        <NavItem to="/history" label="History" icon="🕘" onClose={onClose} />
        <NavItem to="/autopilot" label="Autopilot" icon="🤖" onClose={onClose} />
        <NavItem to="/tasks" label="Jobs" icon="⚙️" onClose={onClose} />
        <NavItem to="/projects" label="Projects" icon="📁" onClose={onClose} />
      </nav>

      <Section
        title={
          <button
            onClick={toggleSettings}
            className="flex w-full items-center justify-between gap-2 text-left focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
            aria-expanded={!settingsCollapsed}
            aria-label={settingsCollapsed ? "Expand Settings section" : "Collapse Settings section"}
          >
            <span>Settings</span>
            {settingsCollapsed ? (
              <span aria-hidden="true" className="text-[11px]">⚙️</span>
            ) : (
              <span aria-hidden="true" className="text-[10px]">▲</span>
            )}
          </button>
        }
      >
        {settingsCollapsed ? (
          <div className="sidebar-settings-grid">
            <NavLink
              to="/settings/modes"
              className={({ isActive }) =>
                `sidebar-settings-link flex items-center justify-center gap-1 rounded-md border transition text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)] ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)]"}`
              }
              onClick={onClose}
            >
              <span aria-hidden="true" style={{ fontSize: "18px", lineHeight: 1 }}>🎚️</span>
            </NavLink>
            <NavLink
              to="/settings/provider"
              className={({ isActive }) =>
                `sidebar-settings-link flex items-center justify-center gap-1 rounded-md border transition text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)] ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)]"}`
              }
              onClick={onClose}
            >
              <span aria-hidden="true" style={{ fontSize: "18px", lineHeight: 1 }}>🔌</span>
            </NavLink>
            <NavLink
              to="/settings/models"
              className={({ isActive }) =>
                `sidebar-settings-link flex items-center justify-center gap-1 rounded-md border transition text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)] ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)]"}`
              }
              onClick={onClose}
            >
              <span aria-hidden="true" style={{ fontSize: "18px", lineHeight: 1 }}>🧠</span>
            </NavLink>
            <NavLink
              to="/settings/agents"
              className={({ isActive }) =>
                `sidebar-settings-link flex items-center justify-center gap-1 rounded-md border transition text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)] ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)]"}`
              }
              onClick={onClose}
            >
              <span aria-hidden="true" style={{ fontSize: "18px", lineHeight: 1 }}>🤖</span>
            </NavLink>
          </div>
        ) : (
          <nav aria-label="Settings" className="flex flex-col gap-1">
            <NavItem to="/settings/modes" label="Modes" icon="🎚️" onClose={onClose} />
            <NavItem to="/settings/provider" label="Provider" icon="🔌" onClose={onClose} />
            <NavItem to="/settings/models" label="Models" icon="🧠" onClose={onClose} />
            <NavItem to="/settings/agents" label="Agents" icon="🤖" onClose={onClose} />
          </nav>
        )}
      </Section>

      <Section title="Status">
        <div className="sidebar-status-group">
          <StatusField label="Model" value={appState?.model} />
          <StatusField label="Provider" value={appState?.provider} />
          <StatusField label="Permission" value={planMode || appState?.permission_mode} tone={planMode === "full_auto" ? "danger" : "success"} />
          <StatusField label="Effort" value={appState?.effort} />
        </div>

        <div className="sidebar-status-subsection">
          <div className="sidebar-section-title">Access</div>
          <StatusField label="Auth" value={appState?.auth_status} tone={appState?.auth_status === "ok" ? "success" : "danger"} />
          <StatusField label="MCP" value={`${appState?.mcp_connected ?? 0} ok / ${appState?.mcp_failed ?? 0} fail`} tone={(appState?.mcp_failed ?? 0) > 0 ? "danger" : "success"} />
        </div>
      </Section>

      {compact && (
        <Section title="Compaction">
          <div className="rounded-md border border-amber-400/30 bg-amber-500/5 px-2 py-1.5 text-[11px] text-amber-200">
            <div className="flex justify-between">
              <span className="font-medium">{compact.phase}</span>
              {compact.attempt ? (
                <span className="text-[var(--text-dim)]">#{compact.attempt}</span>
              ) : null}
            </div>
            {compact.message && (
              <div className="mt-1 truncate text-[var(--text-dim)]">
                {compact.message}
              </div>
            )}
          </div>
        </Section>
      )}

      {todoMarkdown && (
        <Section title="Todos">
          <pre className="whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-2 font-mono text-[11px] leading-relaxed text-[var(--text)]">
            {todoMarkdown}
          </pre>
        </Section>
      )}

      {swarm && (swarm.teammates.length > 0 || swarm.notifications.length > 0) && (
        <Section title={`Swarm (${swarm.teammates.length})`}>
          {swarm.teammates.slice(0, 6).map((t, idx) => (
            <div
              key={idx}
              className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]"
            >
              <div className="font-medium">
                {String(t.name ?? t.agent_id ?? `agent-${idx}`)}
              </div>
              {t.status ? (
                <div className="text-[var(--text-dim)]">{String(t.status)}</div>
              ) : null}
            </div>
          ))}
          {swarm.notifications.length > 0 && (
            <div className="text-[10px] text-[var(--text-dim)]">
              {swarm.notifications.length} notification(s)
            </div>
          )}
        </Section>
      )}

      <div className="sidebar-jobs-section">
        <Section title={`Jobs (${tasks.length})`}>
          {tasks.length === 0 && (
            <div className="text-xs text-[var(--text-dim)]">No background jobs.</div>
          )}
          {tasks.slice(0, 12).map((t) => (
            <div
              key={t.id}
              className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]"
            >
              <div className="flex justify-between gap-2">
                <span className="font-mono text-[var(--text-dim)]">{t.id.slice(0, 8)}</span>
                <span className={`job-badge ${jobBadgeClass(t.status)}`}>{t.status}</span>
              </div>
              <div className="truncate text-[12px]">{t.description || t.type}</div>
            </div>
          ))}
        </Section>
      </div>

      <div className="sidebar-cron-section">
        <Section title={`Cron Jobs (${cron.length})`}>
          {cron.length === 0 && (
            <div className="text-xs text-[var(--text-dim)]">No cron jobs.</div>
          )}
          {cron.slice(0, 8).map((j, idx) => (
            <div
              key={idx}
              className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]"
            >
              <div className="flex justify-between gap-2">
                <span className="truncate font-medium">{String(j.name ?? "?")}</span>
                <span className={`job-badge ${j.enabled ? "job-badge-success" : "job-badge-neutral"}`}>
                  {j.enabled ? "on" : "off"}
                </span>
              </div>
              <div className="font-mono text-[11px] text-[var(--text-dim)]">
                {String(j.schedule ?? "")}
              </div>
            </div>
          ))}
        </Section>
      </div>

      <a
        href="https://github.com/hodtien/openharness/tree/main/docs"
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] text-[var(--text-dim)] transition hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
        style={{ textDecoration: "none", borderWidth: "1px", borderStyle: "solid", borderColor: "transparent" }}
      >
        <span>📖</span>
        <span>Docs</span>
      </a>

      <div className="mt-auto text-[10px] text-[var(--text-dim)]">
        OpenHarness Web UI · v0.1
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop: persistent, can be collapsed via Header toggle */}
      <div
        data-testid="sidebar-desktop"
        className={`${collapsed ? "hidden" : "hidden sm:block"} h-full`}
      >
        {content}
      </div>
      {/* Mobile: drawer */}
      {open && (
        <div data-testid="sidebar-mobile" className="fixed inset-0 z-30 flex sm:hidden">
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

function NavItem({
  to,
  label,
  icon,
  onClose,
}: {
  to: string;
  label: string;
  icon: string;
  onClose: () => void;
}) {
  return (
    <NavLink
      to={to}
      end
      onClick={onClose}
      className={({ isActive }) =>
        `sidebar-nav-link flex items-center gap-1.5 rounded-md border px-2 text-[13px] transition ${
          isActive
            ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100"
            : "border-transparent text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
        }`
      }
    >
      <span aria-hidden="true" className="sidebar-nav-icon">{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}

function Section({ title, children }: { title: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="sidebar-section-title">
        {title}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

type Tone = "success" | "danger" | "warning" | "neutral";

function StatusField({ label, value, tone = "neutral" }: { label: string; value?: string | number; tone?: Tone }) {
  const pillClass = tone === "success"
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

function jobBadgeClass(status: string): string {
  if (["running", "active", "in_progress"].includes(status)) return "job-badge-warning";
  if (["completed", "done", "ok"].includes(status)) return "job-badge-success";
  if (["failed", "error"].includes(status)) return "job-badge-danger";
  return "job-badge-neutral";
}
