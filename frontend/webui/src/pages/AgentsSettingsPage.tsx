import { useEffect, useState } from "react";
import { api, type AgentProfile, type AgentPatch, type ModelsResponse } from "../api/client";

const EFFORT_OPTIONS = ["low", "medium", "high"] as const;
const PERMISSION_OPTIONS = ["default", "plan", "full_auto"] as const;

interface Toast {
  id: number;
  kind: "success" | "error";
  message: string;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + "…";
}

export default function AgentsSettingsPage() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [allModels, setAllModels] = useState<ModelsResponse>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [saveBusy, setSaveBusy] = useState(false);

  // Draft state when editing an agent
  const [draft, setDraft] = useState<AgentPatch>({});

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listAgents(), api.listModels()])
      .then(([agentsResp, modelsResp]) => {
        if (cancelled) return;
        setAgents(agentsResp);
        setAllModels(modelsResp);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flatModelOptions: Array<{ provider: string; id: string; label: string }> = [];
  for (const [provider, models] of Object.entries(allModels)) {
    for (const m of models) {
      flatModelOptions.push({ provider, id: m.id, label: m.label || m.id });
    }
  }

  const startEdit = (agent: AgentProfile) => {
    setEditing(agent.name);
    setDraft({
      model: agent.model ?? undefined,
      effort: agent.effort ?? undefined,
      permission_mode: agent.permission_mode ?? undefined,
    });
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft({});
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSaveBusy(true);
    try {
      const updated = await api.patchAgent(editing, draft);
      setAgents((prev) =>
        prev.map((a) => (a.name === editing ? { ...a, ...updated } : a)),
      );
      setEditing(null);
      pushToast("success", `Agent ${editing} saved.`);
    } catch (err) {
      pushToast("error", String(err));
    } finally {
      setSaveBusy(false);
    }
  };

  const pushToast = (kind: "success" | "error", message: string) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  if (loading) {
    return <div className="p-6 text-sm text-[var(--text-dim)]">Loading agents…</div>;
  }

  return (
    <div className="flex flex-1 overflow-y-auto p-6">
      <div className="w-full max-w-5xl space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text)]">Agents</h1>
          <p className="mt-1 text-sm text-[var(--text-dim)]">
            Configure each agent&apos;s model, effort level, and permission mode.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {agents.length === 0 && (
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 text-sm text-[var(--text-dim)]">
            No agents found.
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          {agents.map((agent) => {
            const isEditing = editing === agent.name;
            return (
              <div
                key={agent.name}
                className="rounded-xl border border-[var(--border)] bg-[var(--panel)] shadow-lg"
              >
                <div className="p-5">
                  {/* Header row — always visible */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="truncate text-base font-semibold text-[var(--text)]">
                        {agent.name}
                      </h2>
                      <p className="mt-1 text-xs text-[var(--text-dim)]">
                        {truncate(agent.description, 120)}
                      </p>
                    </div>
                    {!isEditing && (
                      <button
                        type="button"
                        onClick={() => startEdit(agent)}
                        className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] hover:border-cyan-400/40 hover:text-[var(--text)]"
                      >
                        Edit
                      </button>
                    )}
                  </div>

                  {/* Badges */}
                  {!isEditing && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <Badge label="Model" value={agent.model ?? "—"} />
                      <Badge label="Effort" value={agent.effort ?? "—"} capitalize />
                      <Badge label="Perm" value={agent.permission_mode ?? "—"} />
                      {agent.tools_count != null ? (
                        <Badge label="Tools" value={String(agent.tools_count)} />
                      ) : (
                        <Badge label="Tools" value="all" dim />
                      )}
                      {agent.has_system_prompt && <Badge label="sys" value="prompt" dim />}
                    </div>
                  )}

                  {/* Inline editor */}
                  {isEditing && (
                    <div className="mt-4 space-y-3" data-testid={`editor-${agent.name}`}>
                      <Field label="Model">
                        <select
                          value={draft.model ?? ""}
                          onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value || undefined }))}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                        >
                          <option value="">— none —</option>
                          {flatModelOptions.map((opt) => (
                            <option key={`${opt.provider}:${opt.id}`} value={opt.id}>
                              {opt.label} ({opt.provider})
                            </option>
                          ))}
                        </select>
                      </Field>

                      <Field label="Effort">
                        <select
                          value={draft.effort ?? ""}
                          onChange={(e) => setDraft((d) => ({ ...d, effort: e.target.value || undefined }))}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                        >
                          <option value="">— inherit —</option>
                          {EFFORT_OPTIONS.map((e) => (
                            <option key={e} value={e}>
                              {e}
                            </option>
                          ))}
                        </select>
                      </Field>

                      <Field label="Permission Mode">
                        <select
                          value={draft.permission_mode ?? ""}
                          onChange={(e) =>
                            setDraft((d) => ({ ...d, permission_mode: e.target.value || undefined }))
                          }
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                        >
                          <option value="">— inherit —</option>
                          {PERMISSION_OPTIONS.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </select>
                      </Field>

                      <div className="flex justify-end gap-2 pt-2">
                        <button
                          type="button"
                          onClick={cancelEdit}
                          disabled={saveBusy}
                          className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text-dim)] hover:border-[var(--border)] hover:text-[var(--text)] disabled:opacity-60"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={saveEdit}
                          disabled={saveBusy}
                          className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
                        >
                          {saveBusy ? "Saving…" : "Save"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Toast notifications */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`rounded-lg border px-4 py-3 text-sm shadow-xl ${
              t.kind === "success"
                ? "border-emerald-400/40 bg-emerald-500/20 text-emerald-100"
                : "border-red-400/40 bg-red-500/20 text-red-200"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function Badge({
  label,
  value,
  capitalize,
  dim,
}: {
  label: string;
  value: string;
  capitalize?: boolean;
  dim?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-2 py-0.5 text-[11px] text-[var(--text-dim)]">
      <span className="font-medium text-[var(--text-dim)]">{label}:</span>
      <span className={dim ? "text-[var(--text-dim)]" : capitalize ? "capitalize" : ""}>
        {value}
      </span>
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">{label}</span>
      {children}
    </label>
  );
}