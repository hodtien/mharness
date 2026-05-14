import { useEffect, useState } from "react";
import { NavLink, useSearchParams } from "react-router-dom";
import { api, type CronConfigResponse } from "../api/client";
import { useSession } from "../store/session";
import type { AppStatePayload } from "../api/types";
import PageHeader from "../components/PageHeader";
import { PathDisplay } from "../components/PathDisplay";

import { getAuthSemanticState } from "../utils/authStatusSemantics";

// ─── Icon glyphs ─────────────────────────────────────────────────────────────

const ICON: Record<string, string> = {
  workspace: "☰",
  models: "◌",
  providers: "◎",
  agents: "◈",
  automation: "◴",
  security: "◉",
  appearance: "◫",
};

// ─── Control Center sections ─────────────────────────────────────────────────

interface ControlSection {
  id: string;
  title: string;
  description: string;
  items: ControlItem[];
}

interface ControlItem {
  to: string;
  label: string;
  description: string;
  icon: string;
}

const SECTIONS: ControlSection[] = [
  {
    id: "workspace",
    title: "Workspace",
    description: "Permission mode, active project, working directory, and behaviour flags.",
    items: [
      {
        to: "/settings/modes",
        label: "Modes",
        description: "Permission mode, fast mode, vim, effort and reasoning passes.",
        icon: ICON.workspace,
      },
    ],
  },
  {
    id: "models",
    title: "Models",
    description: "Active model, custom models, and model-level overrides.",
    items: [
      {
        to: "/settings/models",
        label: "Models",
        description: "Browse, add, or remove custom model definitions.",
        icon: ICON.models,
      },
    ],
  },
  {
    id: "providers",
    title: "Providers",
    description: "API keys, base URLs, and active provider selection.",
    items: [
      {
        to: "/settings/provider",
        label: "Providers",
        description: "Configure API credentials and activate a provider.",
        icon: ICON.providers,
      },
    ],
  },
  {
    id: "agents",
    title: "Agents",
    description: "Named agent profiles and per-agent model / permission overrides.",
    items: [
      {
        to: "/settings/agents",
        label: "Agents",
        description: "View and edit named agent configurations.",
        icon: ICON.agents,
      },
    ],
  },
  {
    id: "automation",
    title: "Automation",
    description: "Scheduler configuration, cron expressions, and last / next run status.",
    items: [
      {
        to: "/settings/cron",
        label: "Schedule",
        description: "Autopilot scan and tick schedule, enable / disable the scheduler.",
        icon: ICON.automation,
      },
    ],
  },
  {
    id: "security",
    title: "Security",
    description: "Password, session tokens, auth status, and config location.",
    items: [
      {
        to: "/settings/security",
        label: "Security",
        description: "Change password, view session / token status, config path.",
        icon: ICON.security,
      },
    ],
  },
];

// ─── Operational Status Panel ─────────────────────────────────────────────────

interface OperationalStatusProps {
  appState: AppStatePayload | null;
  cronConfig: CronConfigResponse | null;
  tasksRunning: number;
  tasksFailed: number;
}

function OperationalStatus({
  appState,
  cronConfig,
  tasksRunning,
  tasksFailed,
}: OperationalStatusProps) {
  const schedulerRunning = cronConfig?.scheduler_running ?? false;
  const authSemantic = getAuthSemanticState(appState?.auth_status);

  return (
    <div
      className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-4 shadow-sm"
      aria-label="Operational status"
    >
      <div className="mb-3 text-xs font-semibold uppercase tracking-widest text-[var(--text-dim)]">
        Live Status
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
        <StatusRow label="Model" value={appState?.model ?? "—"} />
        <StatusRow label="Provider" value={appState?.provider ?? "—"} />
        <StatusRow
          label="Auth"
          value={authSemantic.label}
          tone={authSemantic.tone}
        />
        <StatusRow
          label="Jobs running"
          value={String(tasksRunning)}
          tone={tasksRunning > 0 ? "warning" : "neutral"}
        />
        <StatusRow
          label="Jobs failed"
          value={String(tasksFailed)}
          tone={tasksFailed > 0 ? "danger" : "success"}
        />
        <StatusRow
          label="Scheduler"
          value={schedulerRunning ? "running" : "stopped"}
          tone={schedulerRunning ? "success" : "neutral"}
        />
        <StatusRow
          label="MCP"
          value={`${appState?.mcp_connected ?? 0} ok / ${appState?.mcp_failed ?? 0} fail`}
          tone={(appState?.mcp_failed ?? 0) > 0 ? "danger" : "success"}
        />
        {appState?.cwd && (
          <div className="col-span-2 sm:col-span-3">
            <div className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-dim)]">
                CWD
              </span>
              <PathDisplay path={appState.cwd} copyLabel="Copy working directory" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

type Tone = "success" | "danger" | "warning" | "neutral";

function StatusRow({
  label,
  value,
  tone = "neutral",
  mono = false,
}: {
  label: string;
  value: string;
  tone?: Tone;
  mono?: boolean;
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
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-dim)]">
        {label}
      </span>
      <span
        className={`${pillClass} ${mono ? "font-mono" : ""} inline-block max-w-full truncate`}
      >
        {value}
      </span>
    </div>
  );
}

// ─── Section Card ─────────────────────────────────────────────────────────────

function SectionCard({
  section,
  projectId,
}: {
  section: ControlSection;
  projectId: string | null;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] shadow-sm">
      <div className="border-b border-[var(--border)] px-4 py-3">
        <div className="text-sm font-semibold text-[var(--text)]">{section.title}</div>
        <div className="mt-0.5 text-xs text-[var(--text-dim)]">{section.description}</div>
      </div>
      <div className="flex flex-col divide-y divide-[var(--border)]">
        {section.items.map((item) => {
          const to = projectId
            ? `${item.to}?project=${encodeURIComponent(projectId)}`
            : item.to;
          return (
            <NavLink
              key={item.to}
              to={to}
              className={({ isActive }) =>
                `flex items-start gap-3 px-4 py-3 text-[13px] transition hover:bg-[var(--panel-2)] ${
                  isActive ? "bg-[var(--accent-bg)] text-[var(--accent)]" : "text-[var(--text)]"
                }`
              }
              aria-label={item.label}
            >
              <span className="mt-0.5 shrink-0 text-base text-[var(--text-dim)]" aria-hidden="true">
                {item.icon}
              </span>
              <div className="min-w-0">
                <div className="font-medium">{item.label}</div>
                <div className="mt-0.5 text-xs text-[var(--text-dim)]">{item.description}</div>
              </div>
            </NavLink>
          );
        })}
      </div>
    </div>
  );
}

// ─── Automation Status Callout ─────────────────────────────────────────────────

function AutomationCallout({
  schedulerRunning,
  cronLength,
}: {
  schedulerRunning: boolean;
  cronLength: number;
}) {
  if (schedulerRunning || cronLength === 0) return null;

  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0 text-base" aria-hidden="true">⚠</span>
        <div>
          <div className="font-medium">Scheduler stopped</div>
          <div className="mt-0.5 text-xs text-amber-200/70">
            {cronLength} cron job{cronLength !== 1 ? "s" : ""} configured but the scheduler process is not running.
            Go to <strong>Automation → Schedule</strong> to enable the scheduler.
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SettingsControlPage() {
  const appState = useSession((s) => s.appState);
  const tasks = useSession((s) => s.tasks);
  const [cron, setCron] = useState<Array<Record<string, unknown>>>([]);
  const [cronConfig, setCronConfig] = useState<CronConfigResponse | null>(null);
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project");

  useEffect(() => {
    api
      .listCron()
      .then((d) => setCron(d.jobs || []))
      .catch(() => setCron([]));
    api
      .getCronConfig()
      .then((cfg) => setCronConfig(cfg))
      .catch(() => setCronConfig(null));
  }, []);

  const tasksRunning = tasks.filter((t) =>
    ["running", "active", "in_progress"].includes(t.status),
  ).length;
  const tasksFailed = tasks.filter((t) => ["failed", "error"].includes(t.status)).length;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Control Center"
        description="Workspace, models, providers, agents, automation, and security."
      />
      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-3xl space-y-6">

          {/* Operational status */}
          <OperationalStatus
            appState={appState}
            cronConfig={cronConfig}
            tasksRunning={tasksRunning}
            tasksFailed={tasksFailed}
          />

          {/* Automation stopped alert */}
          <AutomationCallout
            schedulerRunning={cronConfig?.scheduler_running ?? false}
            cronLength={cron.length}
          />

          {/* Settings sections grid */}
          <div className="grid gap-4 sm:grid-cols-2">
            {SECTIONS.map((section) => (
              <SectionCard key={section.id} section={section} projectId={projectId} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
