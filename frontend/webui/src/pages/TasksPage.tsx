import { useEffect, useState, useCallback, useRef } from "react";
import { apiFetch } from "../api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

export type TaskType = "local_bash" | "local_agent" | "remote_agent" | "in_process_teammate";
export type TaskStatus = "pending" | "running" | "completed" | "failed" | "killed";

export interface TaskRecord {
  id: string;
  type: TaskType;
  status: TaskStatus;
  description: string;
  cwd: string;
  output_file: string;
  command: string | null;
  prompt: string | null;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  return_code: number | null;
  metadata: Record<string, string>;
}

// ─── Status colors ────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<TaskStatus, string> = {
  pending: "bg-yellow-500/20 text-yellow-300",
  running: "bg-blue-500/20 text-blue-300",
  completed: "bg-emerald-500/20 text-emerald-300",
  failed: "bg-red-500/20 text-red-300",
  killed: "bg-gray-500/20 text-gray-400",
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  killed: "Killed",
};

// ─── Utilities ────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function truncateId(id: string): string {
  return id.slice(0, 8);
}

// ─── Log Viewer ───────────────────────────────────────────────────────────────

interface LogViewerProps {
  taskId: string;
  status: TaskStatus;
  onStop: () => void;
  stopping: boolean;
}

function LogViewer({ taskId, status, onStop, stopping }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const isRunning = status === "running";

  const fetchOutput = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await apiFetch<{ lines: string[] }>(`/api/tasks/${encodeURIComponent(taskId)}/output?tail=500`);
      setLines(data.lines ?? []);
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [taskId]);

  useEffect(() => {
    fetchOutput();
    if (isRunning) {
      const interval = setInterval(fetchOutput, 2000);
      return () => clearInterval(interval);
    }
  }, [fetchOutput, isRunning]);

  // Auto-scroll to bottom when lines change (only when running)
  useEffect(() => {
    if (isRunning && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines.length, isRunning]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--text-dim)]">
          Output log
          {refreshing && <span className="ml-1 opacity-60">· refreshing</span>}
        </span>
        {isRunning && (
          <button
            onClick={onStop}
            disabled={stopping}
            className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-1 text-xs font-medium text-red-300 transition hover:bg-red-500/20 disabled:opacity-40"
          >
            {stopping ? "Stopping…" : "Stop"}
          </button>
        )}
      </div>

      {loading && lines.length === 0 ? (
        <div className="flex items-center justify-center py-4">
          <span className="text-sm text-[var(--text-dim)]">Loading output…</span>
        </div>
      ) : error && lines.length === 0 ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      ) : (
        <pre className="max-h-80 overflow-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3 font-mono text-[11px] leading-relaxed text-[var(--text)]">
          {lines.length === 0 ? (
            <span className="text-[var(--text-dim)]">No output yet.</span>
          ) : (
            lines.map((line, i) => <div key={i}>{line}</div>)
          )}
          <div ref={bottomRef} />
        </pre>
      )}
    </div>
  );
}

// ─── Detail Drawer ────────────────────────────────────────────────────────────

interface DetailDrawerProps {
  task: TaskRecord;
  onClose: () => void;
  onStop: () => void;
  stopping: boolean;
}

function DetailDrawer({ task, onClose, onStop, stopping }: DetailDrawerProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-lg flex-col border-l border-[var(--border)] bg-[var(--panel)] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 font-mono text-xs text-[var(--text-dim)]">
              {truncateId(task.id)}
            </span>
            <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_COLOR[task.status]}`}>
              {STATUS_LABEL[task.status]}
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] p-1.5 text-sm text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          <div className="space-y-5">
            {/* Description */}
            <div>
              <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Description</div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)]">
                {task.description || <span className="text-[var(--text-dim)]">—</span>}
              </div>
            </div>

            {/* Meta grid */}
            <div className="grid grid-cols-2 gap-3">
              <MetaItem label="Type" value={task.type} />
              <MetaItem label="Status" value={STATUS_LABEL[task.status]} />
              <MetaItem label="Created" value={formatTime(task.created_at)} />
              <MetaItem label="Started" value={formatTime(task.started_at ?? 0)} />
              <MetaItem label="Ended" value={formatTime(task.ended_at ?? 0)} />
              {task.return_code !== null && (
                <MetaItem label="Return code" value={String(task.return_code)} highlight={task.return_code !== 0} />
              )}
            </div>

            {/* Command / Prompt */}
            {task.command && (
              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Command</div>
                <pre className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-[var(--text)]">
                  {task.command}
                </pre>
              </div>
            )}
            {task.prompt && (
              <div>
                <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Prompt</div>
                <pre className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-[var(--text)]">
                  {task.prompt}
                </pre>
              </div>
            )}

            {/* CWD */}
            <div>
              <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">Working directory</div>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-xs text-[var(--text)]">
                {task.cwd}
              </div>
            </div>

            {/* Log Viewer */}
            <LogViewer taskId={task.id} status={task.status} onStop={onStop} stopping={stopping} />
          </div>
        </div>
      </div>
    </>
  );
}

function MetaItem({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">{label}</div>
      <div className={`rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs ${highlight ? "text-red-300" : "text-[var(--text)]"}`}>
        {value}
      </div>
    </div>
  );
}

// ─── Main Tasks Page ──────────────────────────────────────────────────────────

const ALL_STATUSES: TaskStatus[] = ["pending", "running", "completed", "failed", "killed"];

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [selected, setSelected] = useState<TaskRecord | null>(null);
  const [stopping, setStopping] = useState(false);

  const fetchTasks = useCallback(async () => {
    try {
      const data = await apiFetch<{ tasks: TaskRecord[] }>("/api/tasks");
      setTasks(data.tasks ?? []);
      setFetchError(null);
    } catch (err) {
      setFetchError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const handleStop = async () => {
    if (!selected) return;
    setStopping(true);
    try {
      const updated = await apiFetch<TaskRecord>(
        `/api/tasks/${encodeURIComponent(selected.id)}/stop`,
        { method: "POST" },
      );
      setSelected(updated);
      await fetchTasks();
    } catch (err) {
      alert(`Failed to stop task: ${err}`);
    } finally {
      setStopping(false);
    }
  };

  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--panel)] px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[var(--text)]">
            {filter === "all" ? "All tasks" : STATUS_LABEL[filter as TaskStatus]}
          </span>
          <span className="rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 text-xs text-[var(--text-dim)]">
            {filtered.length}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as TaskStatus | "all")}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] focus:border-[var(--accent)]/60 focus:outline-none"
          >
            <option value="all">All statuses</option>
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
          <button
            onClick={fetchTasks}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text)] transition hover:border-[var(--accent)]/40"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <span className="text-sm text-[var(--text-dim)]">Loading tasks…</span>
          </div>
        ) : fetchError ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {fetchError}
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <div className="text-sm text-[var(--text-dim)]">
              {filter === "all" ? "No tasks found." : `No ${STATUS_LABEL[filter as TaskStatus].toLowerCase()} tasks.`}
            </div>
          </div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--panel-2)]">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">ID</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Type</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Status</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Description</th>
                <th className="px-4 py-2 text-left font-medium text-[var(--text-dim)]">Created</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((task) => (
                <tr
                  key={task.id}
                  onClick={() => setSelected(task)}
                  className="cursor-pointer border-b border-[var(--border)] transition-colors hover:bg-[var(--panel-2)]/50"
                >
                  <td className="px-4 py-3 font-mono text-xs text-[var(--text-dim)]">
                    {truncateId(task.id)}
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--text)]">
                    {task.type}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_COLOR[task.status]}`}>
                      {STATUS_LABEL[task.status]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[var(--text)]">
                    <span className="truncate max-w-xs block">{task.description || <span className="text-[var(--text-dim)]">—</span>}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--text-dim)]">
                    {formatTime(task.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail Drawer */}
      {selected && (
        <DetailDrawer
          task={selected}
          onClose={() => setSelected(null)}
          onStop={handleStop}
          stopping={stopping}
        />
      )}
    </div>
  );
}