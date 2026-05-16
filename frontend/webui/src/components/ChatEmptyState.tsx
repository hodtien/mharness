import { useNavigate } from "react-router-dom";
import { useSession } from "../store/session";
import { getAuthSemanticState } from "../utils/authStatusSemantics";

interface Action {
  label: string;
  icon: string;
  onClick: () => void;
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="whitespace-nowrap">
      <span className="opacity-60">{label}</span>
      <span className="mx-1 opacity-40">·</span>
      <span className="text-[var(--text)]">{value}</span>
    </span>
  );
}

export default function ChatEmptyState({ onSend }: { onSend: (text: string) => void }) {
  const navigate = useNavigate();
  const appState = useSession((s) => s.appState);

  const actions: Action[] = [
    { label: "Resume recent session", icon: "↺", onClick: () => onSend("/history") },
    { label: "Open Autopilot board", icon: "◈", onClick: () => onSend("/autopilot") },
    {
      label: "Create Autopilot idea",
      icon: "✎",
      onClick: () => {
        // Navigate to Autopilot with new=1 to open the idea creation modal
        const params = new URLSearchParams(window.location.search);
        const basePath = "/autopilot";
        navigate(`${basePath}?${params.toString()}&new=1`);
      },
    },
    { label: "Check system status", icon: "◉", onClick: () => onSend("/status") },
    { label: "/help", icon: "?", onClick: () => onSend("/help") },
  ];

  const mcpConnected = appState?.mcp_connected ?? 0;
  const mcpFailed = appState?.mcp_failed ?? 0;
  const authState = getAuthSemanticState(appState?.auth_status);
  const mcpStatus = mcpFailed > 0 ? `${mcpConnected} up, ${mcpFailed} down` : `${mcpConnected} connected`;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-4 py-8">
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 rounded-lg border border-[var(--border)] bg-[var(--panel)] px-4 py-2 text-xs text-[var(--text-dim)]">
        <StatusItem label="cwd" value={appState?.cwd || "—"} />
        <StatusItem label="project" value={appState?.active_profile || appState?.provider || "—"} />
        <StatusItem label="model" value={appState?.model || "—"} />
        <StatusItem label="mode" value={appState?.permission_mode || "default"} />
        <StatusItem label="auth" value={authState.label} />
        <StatusItem label="mcp" value={mcpStatus} />
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2">
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            onClick={action.onClick}
            className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--text)] transition hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/10 hover:text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
          >
            <span aria-hidden="true" className="text-base">{action.icon}</span>
            <span>{action.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
