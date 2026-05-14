import { useEffect, useMemo, useState } from "react";
import { api, type AgentProfile, type AgentDetail, type AgentPatch, type ModelsResponse } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { toast } from "../store/toast";
import { useUnsavedWarning, FeedbackBadge, useFormFeedback } from "../hooks/useSettingsForm";
import PageHeader from "../components/PageHeader";
import { PathDisplay } from "../components/PathDisplay";

const EFFORT_OPTIONS = ["low", "medium", "high"] as const;
const PERMISSION_OPTIONS = ["default", "acceptEdits", "bypassPermissions", "plan", "dontAsk"] as const;
const BASE_ROUTING_DEFAULTS = [
  { useCase: "Chat", agent: "Default Chat Agent" },
  { useCase: "Code", agent: "Code Agent" },
  { useCase: "Review", agent: "Review Agent" },
  { useCase: "Fast/cheap tasks", agent: "Fast Agent" },
];

const STATIC_OPERATIONAL_AGENT_NAMES = [
  "worker",
  "reviewer",
  "architect",
  "verification",
  "planner",
  "python-reviewer",
  "typescript-reviewer",
];

type ViewMode = "cards" | "compact";

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
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "custom" | "built-in">("all");
  const [modelFilter, setModelFilter] = useState<"all" | "assigned" | "unassigned">("all");
  const [permissionFilter, setPermissionFilter] = useState<string>("all");
  const [toolsFilter, setToolsFilter] = useState<"all" | "none" | "some" | "all-tools">("all");
  const [viewMode, setViewMode] = useState<ViewMode>("cards");
  const [autopilotWorkerAgentName, setAutopilotWorkerAgentName] = useState<string | null>(null);
  const [autopilotReviewAgentName, setAutopilotReviewAgentName] = useState<string | null>(null);

  const { feedback: saveFeedback, errorMessage: saveErrorMessage, showSaving, showSaved, showError: showSaveError } = useFormFeedback();

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listAgents(), api.listModels(), api.getAutopilotPolicyAgents()])
      .then(([agentsResp, modelsResp, policyAgentsResp]) => {
        if (cancelled) return;
        setAgents(agentsResp);
        setAllModels(modelsResp);
        setAutopilotWorkerAgentName(policyAgentsResp.implement_agent);
        setAutopilotReviewAgentName(policyAgentsResp.review_agent);
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

  const flatModelOptions: Array<{ provider: string; id: string; label: string; healthy: boolean }> = [];
  for (const [provider, models] of Object.entries(allModels)) {
    for (const m of models) {
      flatModelOptions.push({ provider, id: m.id, label: m.label || m.id, healthy: true });
    }
  }
  const modelIds = new Set(flatModelOptions.map((model) => model.id));
  const missingModel = (model?: string | null) => Boolean(model && !modelIds.has(model));

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

  const autopilotPolicyAgentNames = useMemo(
    () => Array.from(new Set([autopilotWorkerAgentName, autopilotReviewAgentName].filter((name): name is string => Boolean(name)))),
    [autopilotWorkerAgentName, autopilotReviewAgentName],
  );
  const autopilotPolicyAgentNameSet = useMemo(() => new Set(autopilotPolicyAgentNames), [autopilotPolicyAgentNames]);
  const operationalAgentNames = useMemo(
    () => Array.from(new Set([...autopilotPolicyAgentNames, ...STATIC_OPERATIONAL_AGENT_NAMES])),
    [autopilotPolicyAgentNames],
  );
  const routingDefaults = useMemo(
    () => [
      ...BASE_ROUTING_DEFAULTS,
      ...(autopilotWorkerAgentName ? [{ useCase: "Autopilot Worker", agent: autopilotWorkerAgentName }] : []),
      ...(autopilotReviewAgentName ? [{ useCase: "Autopilot Review", agent: autopilotReviewAgentName }] : []),
    ],
    [autopilotWorkerAgentName, autopilotReviewAgentName],
  );

  const filteredAgents = useMemo(() => {
    const q = search.trim().toLowerCase();
    return agents.filter((agent) => {
      if (q) {
        const role = operationalAgentNames.includes(agent.name) ? "operational" : "agent";
        const haystack = `${agent.name} ${agent.description} ${agent.source_file ?? ""} ${agent.model ?? ""} ${agent.effort ?? ""} ${agent.permission_mode ?? ""} ${role}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (typeFilter === "custom" && !agent.source_file) return false;
      if (typeFilter === "built-in" && agent.source_file) return false;
      if (modelFilter === "assigned" && !agent.model) return false;
      if (modelFilter === "unassigned" && agent.model) return false;
      if (permissionFilter !== "all" && (agent.permission_mode ?? "") !== permissionFilter) return false;
      if (toolsFilter === "none" && (agent.tools_count ?? 0) !== 0) return false;
      if (toolsFilter === "some" && ((agent.tools_count ?? 0) <= 0 || agent.tools_count == null)) return false;
      if (toolsFilter === "all-tools" && agent.tools_count != null) return false;
      return true;
    });
  }, [agents, search, typeFilter, modelFilter, permissionFilter, toolsFilter, operationalAgentNames]);

  const pinnedAgents = useMemo(() => {
    const byName = new Map(filteredAgents.map((agent) => [agent.name, agent]));
    return operationalAgentNames.map((name) => byName.get(name)).filter((agent): agent is AgentProfile => Boolean(agent));
  }, [filteredAgents, operationalAgentNames]);

  const unpinnedAgents = useMemo(() => {
    const pinnedNames = new Set(pinnedAgents.map((agent) => agent.name));
    return filteredAgents.filter((agent) => !pinnedNames.has(agent.name));
  }, [filteredAgents, pinnedAgents]);

  const renderCompactRow = (agent: AgentProfile) => {
    const hasBrokenModel = missingModel(agent.model);
    const isPolicyAgent = autopilotPolicyAgentNameSet.has(agent.name);
    const role = operationalAgentNames.includes(agent.name) ? "Operational" : "General";
    return (
      <tr key={agent.name} className="border-t border-[var(--border)]">
        <td className="px-3 py-2 text-sm font-medium text-[var(--text)]">
          <div className="flex flex-wrap items-center gap-1.5">
            {agent.name}
            {isPolicyAgent && <span className="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">Used by Autopilot</span>}
          </div>
          <div className="max-w-[20rem] truncate text-[10px] text-[var(--text-dim)]" title={agent.description}>{agent.description}</div>
        </td>
        <td className="px-3 py-2 text-xs text-[var(--text-dim)]">{agent.model ?? "—"}</td>
        <td className="px-3 py-2 text-xs text-[var(--text-dim)]">{agent.effort ?? "—"}</td>
        <td className="px-3 py-2 text-xs text-[var(--text-dim)]">{agent.model ? agent.model.split(/[/:]/)[0] : "—"}</td>
        <td className="max-w-[14rem] truncate px-3 py-2 font-mono text-[10px] text-[var(--text-dim)]" title={agent.source_file ?? "built-in"}>{agent.source_file ?? "built-in"}</td>
        <td className={`px-3 py-2 text-xs ${hasBrokenModel ? "text-red-300" : "text-emerald-300"}`}>{hasBrokenModel ? "Unavailable" : "Available"}</td>
        <td className="px-3 py-2 text-xs text-[var(--text-dim)]">{role}</td>
        <td className="px-3 py-2 text-right"><button type="button" onClick={() => openDetail(agent.name)} className="rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--text-dim)] hover:text-[var(--text)]">Details</button></td>
      </tr>
    );
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
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Agents"
        description="Agents are task profiles: purpose, selected model, tools, permission, effort, prompt/instructions, and routing policy. Pick an Agent for normal work; the header model picker is only a temporary override."
        metadata={[{ label: "Agents", value: String(agents.length) }]}
      />
      <div className="flex flex-1 flex-col overflow-y-auto p-6">
      <div className="w-full max-w-5xl space-y-6">

        <section className="rounded-xl border border-cyan-400/20 bg-cyan-500/5 p-4">
          <h2 className="text-sm font-semibold text-cyan-100">Default routing by use case</h2>
          <p className="mt-1 text-xs text-[var(--text-dim)]">Configure model capability once on Models, then route work to an Agent profile. Header model selection temporarily overrides the chosen agent model for the current session.</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {routingDefaults.map((route) => (
              <div key={route.useCase} className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-dim)]">{route.useCase}</div>
                <div className="text-xs font-medium text-[var(--text)]">{route.agent}</div>
              </div>
            ))}
          </div>
        </section>

        {error && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {/* Agents search and filters */}
        <div className="flex flex-col gap-3">
          <div className="relative flex items-center gap-3">
            <div className="relative flex-1">
              <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-[var(--text-dim)]">🔍</span>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name, description, source, model, effort, permission, role…"
                aria-label="Search agents"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] py-2 pl-10 pr-4 text-sm text-[var(--text)] placeholder-[var(--text-dim)] outline-none focus:border-cyan-400/50"
              />
            </div>
            <div className="flex shrink-0 gap-1 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-0.5">
              <button
                type="button"
                onClick={() => setViewMode("cards")}
                title="Card view"
                className={`rounded px-2 py-1 text-xs ${viewMode === "cards" ? "bg-cyan-500/20 text-cyan-100" : "text-[var(--text-dim)] hover:text-[var(--text)]"}`}
              >
                ▦ Cards
              </button>
              <button
                type="button"
                onClick={() => setViewMode("compact")}
                title="Compact table view"
                className={`rounded px-2 py-1 text-xs ${viewMode === "compact" ? "bg-cyan-500/20 text-cyan-100" : "text-[var(--text-dim)] hover:text-[var(--text)]"}`}
              >
                ☰ Table
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {(["all", "custom", "built-in"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setTypeFilter(t)}
                className={`rounded-full border px-2.5 py-1 text-xs ${typeFilter === t ? "border-cyan-400/50 bg-cyan-500/10 text-cyan-100" : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)]"}`}>
                {t === "all" ? "All types" : t === "custom" ? "Custom" : "Built-in"}
              </button>
            ))}
            {(["all", "assigned", "unassigned"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setModelFilter(t)}
                className={`rounded-full border px-2.5 py-1 text-xs ${modelFilter === t ? "border-violet-400/50 bg-violet-500/10 text-violet-100" : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)]"}`}>
                {t === "all" ? "Any model" : t === "assigned" ? "Model set" : "No model"}
              </button>
            ))}
            <select
              value={permissionFilter}
              onChange={(e) => setPermissionFilter(e.target.value)}
              aria-label="Filter by permission mode"
              className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1 text-xs text-[var(--text)] outline-none focus:border-cyan-400/50"
            >
              <option value="all">Any permission</option>
              {PERMISSION_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <select
              value={toolsFilter}
              onChange={(e) => setToolsFilter(e.target.value as "all" | "none" | "some" | "all-tools")}
              aria-label="Filter by tools"
              className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1 text-xs text-[var(--text)] outline-none focus:border-cyan-400/50"
            >
              <option value="all">Any tools</option>
              <option value="all-tools">Unrestricted (all)</option>
              <option value="some">Has tools list</option>
              <option value="none">No tools</option>
            </select>
            {(search || typeFilter !== "all" || modelFilter !== "all" || permissionFilter !== "all" || toolsFilter !== "all") && (
              <button type="button" onClick={() => { setSearch(""); setTypeFilter("all"); setModelFilter("all"); setPermissionFilter("all"); setToolsFilter("all"); }}
                className="rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-2.5 py-1 text-xs text-[var(--text-dim)] hover:border-[var(--text-dim)]">
                Clear filters
              </button>
            )}
          </div>
        </div>

        {agents.length === 0 && (
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 text-sm text-[var(--text-dim)]">
            No agents found.
          </div>
        )}

        {agents.length > 0 && filteredAgents.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--panel)] p-8 text-center">
            <span aria-hidden="true" className="mb-3 text-4xl">🔍</span>
            <p className="text-sm font-medium text-[var(--text)]">No agents match your filters.</p>
            <p className="mt-1 text-xs text-[var(--text-dim)]">
              Try different filters or{" "}
              <button type="button" className="text-cyan-400 hover:underline" onClick={() => { setSearch(""); setTypeFilter("all"); setModelFilter("all"); setPermissionFilter("all"); setToolsFilter("all"); }}>
                clear all filters
              </button>.
            </p>
          </div>
        )}

        {filteredAgents.length > 0 && viewMode === "cards" && pinnedAgents.length > 0 && (
          <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-dim)]">
            <span className="h-2 w-2 rounded-full bg-cyan-400/60" />Operational agents appear first
          </h3>
        )}

        {filteredAgents.length > 0 && viewMode === "compact" && (
          <div className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--panel)]">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--panel-2)] text-[10px] uppercase tracking-wider text-[var(--text-dim)]">
                  <th className="px-3 py-2 font-medium">Name / Description</th>
                  <th className="px-3 py-2 font-medium">Model</th>
                  <th className="px-3 py-2 font-medium">Effort</th>
                  <th className="px-3 py-2 font-medium">Provider</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Role</th>
                  <th className="px-3 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {pinnedAgents.map((agent) => renderCompactRow(agent))}
                {unpinnedAgents.map((agent) => renderCompactRow(agent))}
              </tbody>
            </table>
          </div>
        )}

        {viewMode === "cards" && (
          <div className="grid gap-4 sm:grid-cols-2">
          {[...pinnedAgents, ...unpinnedAgents].map((agent) => {
            const isEditing = editing === agent.name;
            const isUserOwned = !!agent.source_file;
            const hasBrokenModel = missingModel(agent.model);
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
                        {autopilotPolicyAgentNameSet.has(agent.name) && (
                          <span className="shrink-0 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300">
                            Used by Autopilot
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-[var(--text-dim)]">
                        {truncate(agent.description, 120)}
                      </p>
                      {/* Source file path */}
                      {agent.source_file && (
                        <div className="mt-1">
                          <PathDisplay path={agent.source_file} maxLen={50} copyLabel={`Copy source file for ${agent.name}`} />
                        </div>
                      )}
                    </div>
                    {!isEditing && (
                      <div className="flex shrink-0 flex-col gap-1.5">
                        <button
                          type="button"
                          onClick={() => openDetail(agent.name)}
                          title="Preview the system prompt, tools, and full configuration for this agent"
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
                      {agent.has_system_prompt && <Badge label="prompt" value="set" dim />}
                    </div>
                  )}

                  {!isEditing && hasBrokenModel && (
                    <div className="mt-3 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                      Selected model/provider is unavailable: {agent.model}. Choose a healthy model or fix provider credentials.
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
                              {opt.label} ({opt.provider}){opt.healthy ? "" : " — unavailable"}
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
                            {validateBusy ? "Testing…" : "Smoke test"}
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
        )}
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

                  {missingModel(detailData.model) && (
                    <div className="rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                      Selected model/provider is unavailable: {detailData.model}. Run a model probe or select another model before using this agent.
                    </div>
                  )}

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
                        <Label>Prompt / Instructions</Label>
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
