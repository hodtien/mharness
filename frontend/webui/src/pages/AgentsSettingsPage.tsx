import { useEffect, useState } from "react";
import { api, type AgentProfile, type AgentDetail, type AgentPatch, type ModelsResponse } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { toast } from "../store/toast";
import { useUnsavedWarning, FeedbackBadge, useFormFeedback } from "../hooks/useSettingsForm";

const EFFORT_OPTIONS = ["low", "medium", "high"] as const;
const PERMISSION_OPTIONS = ["default", "acceptEdits", "bypassPermissions", "plan", "dontAsk"] as const;


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
  const [saveBusy, setSaveBusy] = useState(false);
  const [validateBusy, setValidateBusy] = useState(false);
  const [validateErrors, setValidateErrors] = useState<string[]>([]);

  // Draft state when editing an agent
  const [draft, setDraft] = useState<AgentPatch>({});
  // Track initial draft to detect changes
  const [initialDraft, setInitialDraft] = useState<AgentPatch>({});

  // Detail modal state
  const [detailAgent, setDetailAgent] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<AgentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [systemPromptExpanded, setSystemPromptExpanded] = useState(false);

  // Clone modal state
  const [cloneSource, setCloneSource] = useState<string | null>(null);
  const [cloneName, setCloneName] = useState("");
  const [cloneBusy, setCloneBusy] = useState(false);

  const { feedback: saveFeedback, errorMessage: saveErrorMessage, showSaving, showSaved, showError: showSaveError } = useFormFeedback();

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
    const init = {
      model: agent.model ?? undefined,
      effort: agent.effort ?? undefined,
      permission_mode: agent.permission_mode ?? undefined,
    };
    setEditing(agent.name);
    setDraft(init);
    setInitialDraft(init);
    setValidateErrors([]);
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft({});
    setInitialDraft({});
    setValidateErrors([]);
  };

  // True when the draft has unsaved changes relative to what was loaded.
  const draftChanged =
    draft.model !== initialDraft.model ||
    draft.effort !== initialDraft.effort ||
    draft.permission_mode !== initialDraft.permission_mode;

  // Warn before navigating away if an edit is in progress with changes
  useUnsavedWarning({ isDirty: draftChanged });

  const saveEdit = async () => {
    if (!editing) return;
    setSaveBusy(true);
    showSaving();
    try {
      const updated = await api.patchAgent(editing, draft);
      setAgents((prev) =>
        prev.map((a) => (a.name === editing ? { ...a, ...updated } : a)),
      );
      setEditing(null);
      setInitialDraft({});
      setValidateErrors([]);
      showSaved();
      toast.success(`Agent ${editing} saved.`);
    } catch (err) {
      showSaveError(String(err));
      toast.error(String(err));
    } finally {
      setSaveBusy(false);
    }
  };

  const validateEdit = async () => {
    if (!editing) return;
    setValidateBusy(true);
    setValidateErrors([]);
    try {
      const result = await api.validateAgent(editing, draft);
      if (result.valid) {
        toast.success("Config looks valid ✓");
      } else {
        setValidateErrors(result.errors);
      }
    } catch (err) {
      toast.error(String(err));
    } finally {
      setValidateBusy(false);
    }
  };

  const openDetail = async (agentName: string) => {
    setDetailAgent(agentName);
    setDetailData(null);
    setDetailError(null);
    setDetailLoading(true);
    setSystemPromptExpanded(false);
    try {
      const data = await api.getAgent(agentName);
      setDetailData(data);
    } catch (err) {
      setDetailError(String(err));
    } finally {
      setDetailLoading(false);
    }
  };

  const openClone = (agentName: string) => {
    setCloneSource(agentName);
    setCloneName(`${agentName}-copy`);
  };

  const submitClone = async () => {
    if (!cloneSource || !cloneName.trim()) return;
    setCloneBusy(true);
    try {
      const created = await api.cloneAgent(cloneSource, cloneName.trim());
      setAgents((prev) => [...prev, created]);
      setCloneSource(null);
      setCloneName("");
      toast.success(`Agent cloned as "${created.name}".`);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setCloneBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 overflow-y-auto p-6">
        <div className="w-full max-w-5xl space-y-4">
          <LoadingSkeleton rows={4} />
        </div>
      </div>
    );
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
            const isUserOwned = !!agent.source_file;
            return (
              <div
                key={agent.name}
                className="rounded-xl border border-[var(--border)] bg-[var(--panel)] shadow-lg"
              >
                <div className="p-5">
                  {/* Header row — always visible */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h2 className="truncate text-base font-semibold text-[var(--text)]">
                          {agent.name}
                        </h2>
                        {isUserOwned && (
                          <span className="shrink-0 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-400">
                            custom
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-[var(--text-dim)]">
                        {truncate(agent.description, 120)}
                      </p>
                      {/* Source file path */}
                      {agent.source_file && (
                        <p className="mt-1 truncate font-mono text-[10px] text-[var(--text-dim)] opacity-60" title={agent.source_file}>
                          {agent.source_file}
                        </p>
                      )}
                    </div>
                    {!isEditing && (
                      <div className="flex shrink-0 flex-col gap-1.5">
                        <button
                          type="button"
                          onClick={() => openDetail(agent.name)}
                          className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] hover:border-cyan-400/40 hover:text-[var(--text)]"
                        >
                          View details
                        </button>
                        <div className="flex gap-1.5">
                          <button
                            type="button"
                            onClick={() => startEdit(agent)}
                            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] hover:border-cyan-400/40 hover:text-[var(--text)]"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={() => openClone(agent.name)}
                            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] hover:border-cyan-400/40 hover:text-[var(--text)]"
                            title="Clone this agent as a new custom agent"
                          >
                            Clone
                          </button>
                        </div>
                      </div>
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
                      {/* Changed indicator */}
                      {draftChanged && (
                        <div className="flex items-center gap-1.5 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                          Unsaved changes
                        </div>
                      )}

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

                      {/* Validate errors */}
                      {validateErrors.length > 0 && (
                        <div className="rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-300 space-y-0.5">
                          {validateErrors.map((e, i) => (
                            <p key={i}>{e}</p>
                          ))}
                        </div>
                      )}

                      <div className="flex items-center justify-between gap-2 pt-2">
                        <FeedbackBadge feedback={saveFeedback} errorMessage={saveErrorMessage} />
                        <div className="flex gap-2">
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
                            onClick={validateEdit}
                            disabled={saveBusy || validateBusy}
                            className="rounded-lg border border-cyan-400/40 bg-[var(--panel-2)] px-4 py-2 text-sm text-cyan-400 hover:bg-cyan-500/10 disabled:opacity-60"
                          >
                            {validateBusy ? "Checking…" : "Validate"}
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
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>


      {/* Detail modal */}
      {detailAgent && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={(e) => { if (e.target === e.currentTarget) setDetailAgent(null); }}
        >
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl">
            {/* Header */}
            <div className="sticky top-0 flex items-center justify-between border-b border-[var(--border)] bg-[var(--panel)] px-6 py-4">
              <h2 className="text-lg font-semibold text-[var(--text)]">
                {detailAgent}
              </h2>
              <button
                type="button"
                onClick={() => setDetailAgent(null)}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text-dim)] hover:text-[var(--text)]"
              >
                ✕
              </button>
            </div>

            <div className="space-y-5 px-6 py-5">
              {detailLoading ? (
                <DetailSkeleton />
              ) : detailError ? (
                <div className="text-sm text-red-300">{detailError}</div>
              ) : detailData ? (
                <>
                  {/* Description */}
                  <div>
                    <Label>Description</Label>
                    <p className="text-sm text-[var(--text)]">{detailData.description}</p>
                  </div>

                  {/* Model / Effort / Permission */}
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <Label>Model</Label>
                      <p className="text-sm text-[var(--text)]">{detailData.model ?? "—"}</p>
                    </div>
                    <div>
                      <Label>Effort</Label>
                      <p className="text-sm capitalize text-[var(--text)]">{detailData.effort ?? "—"}</p>
                    </div>
                    <div>
                      <Label>Permission Mode</Label>
                      <p className="text-sm text-[var(--text)]">{detailData.permission_mode ?? "—"}</p>
                    </div>
                  </div>

                  {/* Source file */}
                  {detailData.source_file ? (
                    <div>
                      <Label>Source File</Label>
                      <p className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs font-mono text-[var(--text-dim)] break-all">
                        {detailData.source_file}
                      </p>
                    </div>
                  ) : (
                    <div>
                      <Label>Source File</Label>
                      <p className="text-xs text-[var(--text-dim)]">Built-in (not editable)</p>
                    </div>
                  )}

                  {/* Tools */}
                  <div>
                    <Label>Tools</Label>
                    {detailData.tools == null ? (
                      <p className="text-sm text-[var(--text-dim)]">All tools</p>
                    ) : detailData.tools.length === 0 ? (
                      <p className="text-sm text-[var(--text-dim)]">No tools</p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {detailData.tools.map((tool) => (
                          <span
                            key={tool}
                            className="rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-2.5 py-0.5 text-xs text-[var(--text-dim)]"
                          >
                            {tool}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* System Prompt — with expand modal */}
                  {detailData.has_system_prompt && (
                    <div>
                      <div className="mb-1 flex items-center justify-between">
                        <Label>System Prompt</Label>
                        {(detailData.system_prompt ?? "").length > 0 && (
                          <button
                            type="button"
                            onClick={() => setSystemPromptExpanded(true)}
                            className="text-xs text-cyan-400 hover:text-cyan-300"
                          >
                            Expand
                          </button>
                        )}
                      </div>
                      {(() => {
                        const sp = detailData.system_prompt ?? "";
                        const truncated = sp.length > 500 ? sp.slice(0, 500) : sp;
                        return (
                          <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--text-dim)]">
                            {truncated}
                            {sp.length > 500 && (
                              <span className="text-[var(--text-dim)] opacity-60">… ({sp.length} chars)</span>
                            )}
                          </pre>
                        );
                      })()}
                    </div>
                  )}
                </>
              ) : null}
            </div>
          </div>
        </div>
      )}

      {/* System prompt expand modal */}
      {systemPromptExpanded && detailData?.system_prompt && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4"
          onClick={(e) => { if (e.target === e.currentTarget) setSystemPromptExpanded(false); }}
        >
          <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl">
            <div className="sticky top-0 flex items-center justify-between border-b border-[var(--border)] bg-[var(--panel)] px-6 py-4">
              <h2 className="text-base font-semibold text-[var(--text)]">System Prompt — {detailAgent}</h2>
              <button
                type="button"
                onClick={() => setSystemPromptExpanded(false)}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-sm text-[var(--text-dim)] hover:text-[var(--text)]"
              >
                ✕
              </button>
            </div>
            <pre className="whitespace-pre-wrap px-6 py-5 text-sm text-[var(--text)]">
              {detailData.system_prompt}
            </pre>
          </div>
        </div>
      )}

      {/* Clone modal */}
      {cloneSource && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={(e) => { if (e.target === e.currentTarget) { setCloneSource(null); setCloneName(""); } }}
        >
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl">
            <div className="border-b border-[var(--border)] px-6 py-4">
              <h2 className="text-base font-semibold text-[var(--text)]">
                Clone agent &ldquo;{cloneSource}&rdquo;
              </h2>
              <p className="mt-1 text-xs text-[var(--text-dim)]">
                Creates a new editable agent file from this template.
              </p>
            </div>
            <div className="px-6 py-5 space-y-4">
              <Field label="New agent name">
                <input
                  type="text"
                  value={cloneName}
                  onChange={(e) => setCloneName(e.target.value)}
                  placeholder="my-custom-agent"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                  onKeyDown={(e) => { if (e.key === "Enter") submitClone(); }}
                  // eslint-disable-next-line jsx-a11y/no-autofocus
                  autoFocus
                />
              </Field>
              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => { setCloneSource(null); setCloneName(""); }}
                  disabled={cloneBusy}
                  className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-60"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={submitClone}
                  disabled={cloneBusy || !cloneName.trim()}
                  className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
                >
                  {cloneBusy ? "Cloning…" : "Clone"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="mb-1 text-xs font-medium text-[var(--text-dim)]">{children}</div>;
}

function DetailSkeleton() {
  return (
    <div className="space-y-3">
      {[200, 150, 180, 120].map((w, i) => (
        <div key={i} className="h-4 w-full animate-pulse rounded bg-[var(--panel-2)]" style={{ width: `${w}px`, maxWidth: '100%' }} />
      ))}
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
