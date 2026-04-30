import { useSession } from "../store/session";

interface Props {
  onRespond: (request_id: string, allowed: boolean) => void;
}

export default function PermissionModal({ onRespond }: Props) {
  const req = useSession((s) => s.pendingPermission);
  if (!req) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-2xl">
        <div className="mb-1 text-xs uppercase tracking-wider text-amber-300">
          Permission requested
        </div>
        <div className="mb-2 text-base font-semibold">{req.tool_name}</div>
        <div className="mb-4 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-3 font-mono text-[12px] text-[var(--text-dim)]">
          {req.reason || "(no details)"}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onRespond(req.request_id, false)}
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm hover:bg-[var(--panel)]"
          >
            Deny
          </button>
          <button
            onClick={() => onRespond(req.request_id, true)}
            className="flex-1 rounded-lg bg-[var(--accent-strong)] px-3 py-2 text-sm font-semibold text-white hover:bg-[var(--accent)]"
          >
            Allow
          </button>
        </div>
      </div>
    </div>
  );
}
