import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
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
    <div className="flex h-full w-72 flex-col gap-4 overflow-y-auto border-r border-[var(--border)] bg-[var(--panel)] p-4">
      <nav aria-label="Primary" className="flex flex-col gap-1">
        <NavItem to="/chat" label="Chat" icon="💬" onClose={onClose} />
        <NavItem to="/history" label="History" icon="🕘" onClose={onClose} />
        <NavItem to="/autopilot" label="Autopilot" icon="🤖" onClose={onClose} />
        <NavItem to="/tasks" label="Jobs" icon="⚙️" onClose={onClose} />
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
          <div className="flex gap-2 text-[11px]">
            <NavLink
              to="/settings/modes"
              className={({ isActive }) =>
                `flex items-center gap-1 rounded-md border px-2 py-1 transition ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)] text-[var(--text-dim)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"}`
              }
              onClick={onClose}
            >
              🎚️
            </NavLink>
            <NavLink
              to="/settings/provider"
              className={({ isActive }) =>
                `flex items-center gap-1 rounded-md border px-2 py-1 transition ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)] text-[var(--text-dim)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"}`
              }
              onClick={onClose}
            >
              🔌
            </NavLink>
            <NavLink
              to="/settings/models"
              className={({ isActive }) =>
                `flex items-center gap-1 rounded-md border px-2 py-1 transition ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)] text-[var(--text-dim)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"}`
              }
              onClick={onClose}
            >
              🧠
            </NavLink>
            <NavLink
              to="/settings/agents"
              className={({ isActive }) =>
                `flex items-center gap-1 rounded-md border px-2 py-1 transition ${isActive ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-[var(--border)] text-[var(--text-dim)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"}`
              }
              onClick={onClose}
            >
              🤖
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
        <Row k="model" v={appState?.model} />
        <Row k="provider" v={appState?.provider} />
        <Row k="auth" v={appState?.auth_status} />
        <Row k="permission" v={planMode || appState?.permission_mode} />
        <Row k="effort" v={appState?.effort} />
        <Row k="mcp" v={`${appState?.mcp_connected ?? 0} ok / ${appState?.mcp_failed ?? 0} fail`} />
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

      <Section title={`Jobs (${tasks.length})`}>
        {tasks.length === 0 && (
          <div className="text-xs text-[var(--text-dim)]">No background jobs.</div>
        )}
        {tasks.slice(0, 12).map((t) => (
          <div
            key={t.id}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]"
          >
            <div className="flex justify-between">
              <span className="font-mono text-[var(--text-dim)]">{t.id.slice(0, 8)}</span>
              <span className={statusColor(t.status)}>{t.status}</span>
            </div>
            <div className="truncate text-[12px]">{t.description || t.type}</div>
          </div>
        ))}
      </Section>

      <Section title={`Cron jobs (${cron.length})`}>
        {cron.length === 0 && (
          <div className="text-xs text-[var(--text-dim)]">No cron jobs.</div>
        )}
        {cron.slice(0, 8).map((j, idx) => (
          <div
            key={idx}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]"
          >
            <div className="flex justify-between">
              <span className="truncate font-medium">{String(j.name ?? "?")}</span>
              <span
                className={j.enabled ? "text-emerald-300" : "text-[var(--text-dim)]"}
              >
                {j.enabled ? "on" : "off"}
              </span>
            </div>
            <div className="font-mono text-[11px] text-[var(--text-dim)]">
              {String(j.schedule ?? "")}
            </div>
          </div>
        ))}
      </Section>

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
        `flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition ${
          isActive
            ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100"
            : "border-transparent text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
        }`
      }
    >
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}

function Section({ title, children }: { title: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-dim)]">
        {title}
      </div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v?: string | number }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-[var(--text-dim)]">{k}</span>
      <span className="truncate font-mono text-right">{v ?? "—"}</span>
    </div>
  );
}

function statusColor(status: string): string {
  if (["running", "active", "in_progress"].includes(status)) return "text-amber-300";
  if (["completed", "done", "ok"].includes(status)) return "text-emerald-300";
  if (["failed", "error"].includes(status)) return "text-rose-300";
  return "text-[var(--text-dim)]";
}
