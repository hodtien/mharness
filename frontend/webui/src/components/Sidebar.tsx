import { useEffect, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import ProjectSelector from "./ProjectSelector";
import { useSession } from "../store/session";

const SETTINGS_COLLAPSED_KEY = "oh:sidebar:settings-collapsed";
const STATUS_COLLAPSED_KEY = "oh:sidebar:status-collapsed";

type IconName =
  | "chat"
  | "history"
  | "autopilot"
  | "jobs"
  | "projects"
  | "modes"
  | "provider"
  | "models"
  | "agents"
  | "schedule"
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
  const [statusCollapsed, setStatusCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STATUS_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    api
      .listCron()
      .then((d) => setCron(d.jobs || []))
      .catch(() => setCron([]));
  }, [tasks.length]);

  const runningJobs = tasks.filter((t) => ["running", "active", "in_progress"].includes(t.status)).length;
  const failedJobs = tasks.filter((t) => ["failed", "error"].includes(t.status)).length;
  const enabledCron = cron.filter((j) => Boolean(j.enabled)).length;
  const mcpFailed = appState?.mcp_failed ?? 0;

  const content = (
    <div className="flex h-full w-72 flex-col gap-3 overflow-y-auto border-r border-[var(--border)] bg-[var(--panel)] p-3">
      <Section title="Project">
        <ProjectSelector />
      </Section>

      <Section title="Navigate">
        <nav aria-label="Primary" className="flex flex-col gap-2">
          <NavItem to="/chat" label="Chat" icon="chat" onClose={onClose} />
          <NavItem to="/history" label="History" icon="history" onClose={onClose} />
          <NavItem to="/autopilot" label="Autopilot" icon="autopilot" onClose={onClose} />
          <NavItem to="/tasks" label="Jobs" icon="jobs" onClose={onClose} />
          <NavItem to="/projects" label="Projects" icon="projects" onClose={onClose} />
        </nav>
      </Section>

      <Section
        title={
          <button onClick={() => setSettingsCollapsed((v) => {
            const next = !v;
            try { localStorage.setItem(SETTINGS_COLLAPSED_KEY, String(next)); } catch {}
            return next;
          })} className="flex w-full items-center justify-between gap-2 text-left" aria-expanded={!settingsCollapsed} aria-label={settingsCollapsed ? "Expand settings navigation" : "Collapse settings navigation"}>
            <span>Settings</span>
            <Icon name={settingsCollapsed ? "caretDown" : "caretUp"} />
          </button>
        }
      >
        {!settingsCollapsed && (
          <nav aria-label="Settings" className="flex flex-col gap-1">
            <NavItem to="/settings/modes" label="Modes" icon="modes" onClose={onClose} />
            <NavItem to="/settings/provider" label="Provider" icon="provider" onClose={onClose} />
            <NavItem to="/settings/models" label="Models" icon="models" onClose={onClose} />
            <NavItem to="/settings/agents" label="Agents" icon="agents" onClose={onClose} />
            <NavItem to="/settings/cron" label="Schedule" icon="schedule" onClose={onClose} />
          </nav>
        )}
      </Section>

      <Section title="Status">
        <div className="flex flex-wrap gap-1">
          <StatusBadge label="Model" value={String(appState?.model ?? "—")} />
          <StatusBadge label="Provider" value={String(appState?.provider ?? "—")} />
          <StatusBadge label="Jobs" value={String(tasks.length)} tone={runningJobs > 0 ? "warning" : "neutral"} />
          <StatusBadge label="Cron" value={`${enabledCron}/${cron.length}`} tone={enabledCron > 0 ? "success" : "neutral"} />
          <StatusBadge label="MCP" value={mcpFailed > 0 ? "degraded" : "ok"} tone={mcpFailed > 0 ? "danger" : "success"} />
        </div>
      </Section>

      <Section
        title={
          <button onClick={() => setStatusCollapsed((v) => {
            const next = !v;
            try { localStorage.setItem(STATUS_COLLAPSED_KEY, String(next)); } catch {}
            return next;
          })} className="flex w-full items-center justify-between gap-2 text-left" aria-expanded={!statusCollapsed} aria-label={statusCollapsed ? "Expand system details" : "Collapse system details"}>
            <span>Details</span>
            <Icon name={statusCollapsed ? "caretDown" : "caretUp"} />
          </button>
        }
      >
        {!statusCollapsed && (
          <>
            <div className="sidebar-status-group">
              <StatusField label="Permission" value={planMode || appState?.permission_mode} tone={planMode === "full_auto" ? "danger" : "success"} />
              <StatusField label="Auth" value={appState?.auth_status} tone={appState?.auth_status === "ok" ? "success" : "danger"} />
              <StatusField label="MCP" value={`${appState?.mcp_connected ?? 0} ok / ${appState?.mcp_failed ?? 0} fail`} tone={(appState?.mcp_failed ?? 0) > 0 ? "danger" : "success"} />
              <StatusField label="Failed Jobs" value={failedJobs} tone={failedJobs > 0 ? "danger" : "success"} />
            </div>
            <Section title={`Jobs (${tasks.length})`}>
              {tasks.slice(0, 3).map((t) => (
                <div key={t.id} className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]">
                  <div className="flex justify-between gap-2">
                    <span className="font-mono text-[var(--text-dim)]">{t.id.slice(0, 8)}</span>
                    <span className={`job-badge ${jobBadgeClass(t.status)}`}>{t.status}</span>
                  </div>
                  <div className="truncate text-[12px]">{t.description || t.type}</div>
                </div>
              ))}
            </Section>
            <Section title={`Cron Jobs (${cron.length})`}>
              {cron.slice(0, 4).map((j, idx) => (
                <div key={idx} className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[11px]">
                  <div className="flex justify-between gap-2">
                    <span className="truncate font-medium">{String(j.name ?? "?")}</span>
                    <span className={`job-badge ${j.enabled ? "job-badge-success" : "job-badge-neutral"}`}>{j.enabled ? "on" : "off"}</span>
                  </div>
                </div>
              ))}
            </Section>
          </>
        )}
      </Section>

      {compact && <Section title="Compaction"><div className="text-xs">{compact.phase}</div></Section>}
      {todoMarkdown && <Section title="Todos"><pre className="whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-2 font-mono text-[11px]">{todoMarkdown}</pre></Section>}
      {swarm && (swarm.teammates.length > 0 || swarm.notifications.length > 0) && <Section title={`Swarm (${swarm.teammates.length})`}><div className="text-xs text-[var(--text-dim)]">{swarm.notifications.length} notification(s)</div></Section>}

      <a href="https://github.com/hodtien/openharness/tree/main/docs" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px] text-[var(--text-dim)] transition hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]" style={{ textDecoration: "none", borderWidth: "1px", borderStyle: "solid", borderColor: "transparent" }} aria-label="Open documentation">
        <Icon name="docs" />
        <span>Docs</span>
      </a>
    </div>
  );

  return <>
    <div data-testid="sidebar-desktop" className={`${collapsed ? "hidden" : "hidden sm:block"} h-full`}>{content}</div>
    {open && <div data-testid="sidebar-mobile" className="fixed inset-0 z-30 flex sm:hidden">{content}<div data-testid="sidebar-mobile-backdrop" className="flex-1 bg-black/40" onClick={onClose} /></div>}
  </>;
}

function NavItem({ to, label, icon, onClose }: { to: string; label: string; icon: IconName; onClose: () => void }) {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project");
  const target = projectId ? `${to}?project=${encodeURIComponent(projectId)}` : to;
  return <NavLink to={target} end onClick={onClose} className={({ isActive }) => `sidebar-nav-link flex items-center gap-1.5 rounded-md border px-2 text-[13px] transition ${isActive ? "border-[var(--accent-strong)]/40 bg-[var(--accent-bg)] text-[var(--accent)]" : "border-transparent text-[var(--text-dim)] hover:border-[var(--border)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"}`} aria-label={label} title={label}><span aria-hidden="true" className="sidebar-nav-icon"><Icon name={icon} /></span><span>{label}</span></NavLink>;
}

function Icon({ name }: { name: IconName }) {
  const glyph: Record<IconName, string> = { chat: "◉", history: "◷", autopilot: "⬢", jobs: "◍", projects: "▣", modes: "☰", provider: "◎", models: "◌", agents: "◈", schedule: "◴", docs: "◧", caretDown: "▾", caretUp: "▴" };
  return <span aria-hidden="true">{glyph[name]}</span>;
}

function Section({ title, children }: { title: React.ReactNode; children: React.ReactNode }) { return <div><div className="sidebar-section-title">{title}</div><div className="flex flex-col gap-2">{children}</div></div>; }

type Tone = "success" | "danger" | "warning" | "neutral";
function StatusField({ label, value, tone = "neutral" }: { label: string; value?: string | number; tone?: Tone }) {
  const pillClass = tone === "success" ? "status-pill status-pill-success" : tone === "danger" ? "status-pill status-pill-danger" : tone === "warning" ? "status-pill status-pill-warning" : "status-pill";
  return <div className="flex items-center justify-between text-xs"><span className="text-[var(--text-dim)]">{label}</span><span className={pillClass}>{value ?? "—"}</span></div>;
}

function StatusBadge({ label, value, tone = "neutral" }: { label: string; value: string; tone?: Tone }) {
  const toneClass = tone === "success" ? "status-pill-success" : tone === "danger" ? "status-pill-danger" : tone === "warning" ? "status-pill-warning" : "";
  return <span className={`status-pill ${toneClass}`} title={`${label}: ${value}`} aria-label={`${label}: ${value}`}>{label}: {value}</span>;
}

function jobBadgeClass(status: string): string {
  if (["running", "active", "in_progress"].includes(status)) return "job-badge-warning";
  if (["completed", "done", "ok"].includes(status)) return "job-badge-success";
  if (["failed", "error"].includes(status)) return "job-badge-danger";
  return "job-badge-neutral";
}
