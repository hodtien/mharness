import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import {
  api,
  type ModelProfile,
  type ModelsResponse,
  type ProviderProfile,
} from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import { toast } from "../store/toast";
import PageHeader from "../components/PageHeader";

interface AddModalState {
  provider: string;
  modelId: string;
  label: string;
  contextWindow: string;
  busy: boolean;
  error: string | null;
}

interface EditModalState {
  provider: string;
  modelId: string;
  label: string;
  contextWindow: string;
  busy: boolean;
  error: string | null;
}

interface DeleteConfirmState {
  provider: string;
  modelId: string;
  busy: boolean;
  error: string | null;
}

export default function ModelsSettingsPage() {
  const [models, setModels] = useState<ModelsResponse>({});
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openProviders, setOpenProviders] = useState<Record<string, boolean>>({});
  const [addModal, setAddModal] = useState<AddModalState | null>(null);
  const [editModal, setEditModal] = useState<EditModalState | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState | null>(null);
  const [search, setSearch] = useState("");

  const reload = async () => {
    setError(null);
    const [modelsResp, providersResp] = await Promise.all([
      api.listModels(),
      api.listProviders(),
    ]);
    setModels(modelsResp);
    setProviders(providersResp.providers);
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listModels(), api.listProviders()])
      .then(([modelsResp, providersResp]) => {
        if (cancelled) return;
        setModels(modelsResp);
        setProviders(providersResp.providers);
        // Default: all accordions expanded.
        const open: Record<string, boolean> = {};
        for (const id of Object.keys(modelsResp)) open[id] = true;
        setOpenProviders(open);
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

  const providerLabels = useMemo(() => {
    const map: Record<string, string> = {};
    for (const p of providers) map[p.id] = p.label;
    return map;
  }, [providers]);

  const filteredProviderEntries = useMemo(() => {
    const query = search.trim().toLowerCase();
    const entries = Object.entries(models).map(([providerId, items]) => {
      const filtered = query
        ? items.filter((model) => {
            const haystack = `${model.id} ${model.label}`.toLowerCase();
            return haystack.includes(query);
          })
        : items;
      const builtIn = filtered.filter((model) => !model.is_custom);
      const custom = filtered.filter((model) => model.is_custom);
      return [providerId, [...custom, ...builtIn]] as [string, ModelProfile[]];
    });
    return entries.filter(([, items]) => items.length > 0);
  }, [models, search]);

  if (loading) {
    return (
      <div className="flex flex-1 overflow-y-auto p-6">
        <div className="w-full max-w-5xl space-y-4">
          <LoadingSkeleton rows={4} />
        </div>
      </div>
    );
  }

  const toggle = (providerId: string) => {
    setOpenProviders((prev) => ({ ...prev, [providerId]: !prev[providerId] }));
  };

  const openAdd = () => {
    const first = providers[0]?.id ?? Object.keys(models)[0] ?? "";
    setAddModal({
      provider: first,
      modelId: "",
      label: "",
      contextWindow: "",
      busy: false,
      error: null,
    });
  };

  

  const submitAdd = async () => {
    if (!addModal) return;
    const trimmedId = addModal.modelId.trim();
    if (!addModal.provider || !trimmedId) {
      setAddModal({ ...addModal, error: "Provider and model id are required." });
      return;
    }
    const ctx = addModal.contextWindow.trim();
    let contextWindow: number | undefined;
    if (ctx) {
      const parsed = Number(ctx);
      if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
        setAddModal({ ...addModal, error: "Context window must be a positive integer." });
        return;
      }
      contextWindow = parsed;
    }
    setAddModal({ ...addModal, busy: true, error: null });
    try {
      await api.addCustomModel({
        provider: addModal.provider,
        model_id: trimmedId,
        label: addModal.label.trim() || undefined,
        context_window: contextWindow,
      });
      await reload();
      setAddModal(null);
      toast.success(`Model ${trimmedId} added.`);
    } catch (err) {
      setAddModal({ ...addModal, busy: false, error: String(err) });
    }
  };

  const openEdit = (provider: string, model: ModelProfile) => {
    setEditModal({
      provider,
      modelId: model.id,
      label: model.label ?? "",
      contextWindow: model.context_window != null ? String(model.context_window) : "",
      busy: false,
      error: null,
    });
  };

  const submitEdit = async () => {
    if (!editModal) return;
    const ctx = editModal.contextWindow.trim();
    let contextWindow: number | undefined;
    if (ctx) {
      const parsed = Number(ctx);
      if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(parsed)) {
        setEditModal({ ...editModal, error: "Context window must be a positive integer." });
        return;
      }
      contextWindow = parsed;
    }
    setEditModal({ ...editModal, busy: true, error: null });
    // No PATCH endpoint exists: delete then re-add with new metadata.
    try {
      await api.deleteCustomModel(editModal.provider, editModal.modelId);
    } catch (err) {
      setEditModal({ ...editModal, busy: false, error: `Failed to update: ${String(err)}` });
      return;
    }
    try {
      await api.addCustomModel({
        provider: editModal.provider,
        model_id: editModal.modelId,
        label: editModal.label.trim() || undefined,
        context_window: contextWindow,
      });
      await reload();
      setEditModal(null);
      toast.success(`Model ${editModal.modelId} updated.`);
    } catch (err) {
      // Re-add failed after delete succeeded — surface error and reload state.
      await reload().catch(() => undefined);
      setEditModal(null);
      toast.error(`Update failed after delete; model ${editModal.modelId} was removed: ${String(err)}`);
    }
  };

  const submitDelete = async () => {
    if (!deleteConfirm) return;
    setDeleteConfirm({ ...deleteConfirm, busy: true, error: null });
    try {
      await api.deleteCustomModel(deleteConfirm.provider, deleteConfirm.modelId);
      await reload();
      const removedId = deleteConfirm.modelId;
      setDeleteConfirm(null);
      toast.success(`Model ${removedId} deleted.`);
    } catch (err) {
      setDeleteConfirm({ ...deleteConfirm, busy: false, error: String(err) });
    }
  };

  const providerEntries = Object.entries(models);
  const totalModels = providerEntries.reduce((acc, [, items]) => acc + items.length, 0);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Models"
        description="Browse the built-in catalog and manage custom models per provider profile. Search by model id or label to find capabilities quickly, then use each provider section to inspect built-in vs. custom entries."
        primaryAction={
          <button
            type="button"
            onClick={openAdd}
            className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400"
          >
            Add custom model
          </button>
        }
        metadata={[
          { label: "Total", value: String(totalModels) },
          { label: "Providers", value: String(providerEntries.length) },
        ]}
      />

      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-5xl space-y-6">

        {error && <ErrorBanner message={error} />}

        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-[var(--text-dim)]">
              🔍
            </span>
            <input
              type="search"
              value={search}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
              placeholder="Filter by model id or label…"
              aria-label="Filter models"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] py-2 pl-10 pr-4 text-sm text-[var(--text)] placeholder-[var(--text-dim)] outline-none focus:border-cyan-400/50"
            />
          </div>
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-xs text-[var(--text-dim)] hover:border-[var(--text-dim)]"
            >
              Clear
            </button>
          )}
        </div>

        <div className="space-y-3">
          {Object.keys(models).length === 0 && !search && (
            <EmptyState message="No provider profiles configured." description="Add a provider in Provider settings first." />
          )}
          {filteredProviderEntries.length === 0 && Object.keys(models).length > 0 ? (
            search ? (
              <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--panel)] p-8 text-center">
                <span aria-hidden="true" className="mb-3 text-4xl">🔍</span>
                <p className="text-sm font-medium text-[var(--text)]">No models match &ldquo;{search}&rdquo;</p>
                <p className="mt-1 text-xs text-[var(--text-dim)]">Try a different search term.</p>
              </div>
            ) : null
          ) : (
            filteredProviderEntries.map(([providerId, items]) => {
              const open = openProviders[providerId] ?? true;
              const label = providerLabels[providerId] ?? providerId;
              const customCount = items.filter((m) => m.is_custom).length;
              return (
                <section
                  key={providerId}
                  className="rounded-xl border border-[var(--border)] bg-[var(--panel)] shadow-lg"
                >
                  <button
                    type="button"
                    onClick={() => toggle(providerId)}
                    aria-expanded={open}
                    aria-controls={`models-panel-${providerId}`}
                    className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left"
                  >
                    <div className="flex items-center gap-3">
                      <span aria-hidden="true" className="text-xs text-[var(--text-dim)]">
                        {open ? "▼" : "▶"}
                      </span>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-[var(--text)]">{label}</span>
                          {customCount > 0 && (
                            <span className="rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-xs text-amber-200">
                              {customCount} custom
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-[var(--text-dim)]">
                          {items.length} model{items.length === 1 ? "" : "s"}
                        </div>
                      </div>
                    </div>
                    <div className="text-xs font-mono text-[var(--text-dim)]">{providerId}</div>
                  </button>
                  {open && (
                    <div id={`models-panel-${providerId}`} className="border-t border-[var(--border)]">
                      {items.length === 0 ? (
                        <div className="px-5 py-6 text-center">
                          <p className="text-sm text-[var(--text-dim)]">No models in this provider.</p>
                          <p className="mt-0.5 text-xs text-[var(--text-dim)]">Add a custom model using the button above.</p>
                        </div>
                      ) : (
                        <ModelsTable
                          providerId={providerId}
                          models={items}
                          onEdit={(model) => openEdit(providerId, model)}
                          onDelete={(model) =>
                            setDeleteConfirm({
                              provider: providerId,
                              modelId: model.id,
                              busy: false,
                              error: null,
                            })
                          }
                        />
                      )}
                    </div>
                  )}
                </section>
              );
            })
          )}
        </div>
      </div>
      </div>

      {addModal && (
        <AddCustomModelModal
          state={addModal}
          providers={providers}
          providerEntries={providerEntries}
          onChange={setAddModal}
          onCancel={() => setAddModal(null)}
          onSubmit={submitAdd}
        />
      )}

      {editModal && (
        <EditCustomModelModal
          state={editModal}
          providerLabel={providerLabels[editModal.provider] ?? editModal.provider}
          onChange={setEditModal}
          onCancel={() => setEditModal(null)}
          onSubmit={submitEdit}
        />
      )}

      {deleteConfirm && (
        <DeleteConfirmModal
          state={deleteConfirm}
          providerLabel={providerLabels[deleteConfirm.provider] ?? deleteConfirm.provider}
          onCancel={() => setDeleteConfirm(null)}
          onConfirm={submitDelete}
        />
      )}
    </div>
  );
}

function ModelsTable({
  providerId,
  models,
  onEdit,
  onDelete,
}: {
  providerId: string;
  models: ModelProfile[];
  onEdit: (model: ModelProfile) => void;
  onDelete: (model: ModelProfile) => void;
}) {
  const { builtInModels, customModels } = useMemo(() => {
    const customModels = models.filter((model) => model.is_custom);
    const builtInModels = models.filter((model) => !model.is_custom);
    return {
      builtInModels: builtInModels.sort((a, b) => a.id.localeCompare(b.id)),
      customModels: customModels.sort((a, b) => a.id.localeCompare(b.id)),
    };
  }, [models]);

  if (models.length === 0) {
    return <div className="px-5 py-3 text-sm text-[var(--text-dim)]">No models.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-[var(--text-dim)]">
            <th className="px-5 py-2 font-medium">Model id</th>
            <th className="px-5 py-2 font-medium">Label</th>
            <th className="px-5 py-2 font-medium">Capabilities</th>
            <th className="px-5 py-2 font-medium">Context window</th>
            <th className="px-5 py-2 font-medium">Default</th>
            <th className="px-5 py-2 font-medium">Type</th>
            <th className="px-5 py-2 font-medium" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          <ModelSectionRows models={customModels} onEdit={onEdit} onDelete={onDelete} providerId={providerId} />
          <ModelSectionRows models={builtInModels} onEdit={onEdit} onDelete={onDelete} providerId={providerId} />
        </tbody>
      </table>
    </div>
  );
}

function CapabilityBadge({ label, variant = "default" }: { label: string; variant?: "default" | "highlight" }) {
  const styles: Record<string, string> = {
    default: "rounded-full border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--text-dim)]",
    highlight: "rounded-full border border-violet-400/40 bg-violet-400/10 px-1.5 py-0.5 text-[10px] text-violet-200",
  };
  return <span className={styles[variant]}>{label}</span>;
}

function ModelSectionRows({
  models,
  onEdit,
  onDelete,
  providerId,
}: {
  models: ModelProfile[];
  onEdit: (model: ModelProfile) => void;
  onDelete: (model: ModelProfile) => void;
  providerId: string;
}) {
  return (
    <>
      {models.map((model) => {
        const ctx = model.context_window;
        const badges: Array<{ label: string; variant?: "default" | "highlight" }> = [];

        if (ctx && ctx >= 100000) {
          badges.push({ label: "long ctx", variant: "highlight" });
        }
        if (/\bfast\b/i.test(model.id) || /\bflash\b/i.test(model.id)) {
          badges.push({ label: "fast", variant: "highlight" });
        }
        if (/vision/i.test(model.id) || /-\d(?:\.\d+)?-vision/i.test(model.id)) {
          badges.push({ label: "vision", variant: "highlight" });
        }
        if (/-\d(?:\.\d+)?-tools/i.test(model.id) || /-tool/i.test(model.id)) {
          badges.push({ label: "tools", variant: "highlight" });
        }

        return (
          <tr
            key={`${providerId}:${model.id}`}
            className="border-t border-[var(--border)] text-[var(--text)]"
          >
            <td className="px-5 py-2 font-mono text-xs">{model.id}</td>
            <td className="px-5 py-2">{model.label}</td>
            <td className="px-5 py-2">
              <div className="flex flex-wrap gap-1">
                {badges.map((b) => (
                  <CapabilityBadge key={b.label} label={b.label} variant={b.variant} />
                ))}
                {badges.length === 0 && <span className="text-xs text-[var(--text-dim)]">—</span>}
              </div>
            </td>
            <td className="px-5 py-2 text-[var(--text-dim)]">
              {ctx ? ctx.toLocaleString() : "—"}
            </td>
            <td className="px-5 py-2">
              {model.is_default ? (
                <span
                  aria-label="default model"
                  className="rounded-full border border-cyan-400/40 bg-cyan-400/10 px-2 py-0.5 text-xs text-cyan-100"
                >
                  ✓ default
                </span>
              ) : (
                <span className="text-xs text-[var(--text-dim)]">—</span>
              )}
            </td>
            <td className="px-5 py-2">
              {model.is_custom ? (
                <span className="rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-xs text-amber-100">
                  custom
                </span>
              ) : (
                <span className="text-xs text-[var(--text-dim)]">built-in</span>
              )}
            </td>
            <td className="px-5 py-2 text-right">
              {model.is_custom && (
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => onEdit(model)}
                    aria-label={`Edit ${model.id}`}
                    className="rounded-md border border-cyan-400/30 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-200 hover:border-cyan-400/60"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(model)}
                    aria-label={`Delete ${model.id}`}
                    className="rounded-md border border-red-400/30 bg-red-500/10 px-3 py-1 text-xs text-red-200 hover:border-red-400/60"
                  >
                    Delete
                  </button>
                </div>
              )}
            </td>
          </tr>
        );
      })}
    </>
  );
}

function AddCustomModelModal({
  state,
  providers,
  providerEntries,
  onChange,
  onCancel,
  onSubmit,
}: {
  state: AddModalState;
  providers: ProviderProfile[];
  providerEntries: Array<[string, ModelProfile[]]>;
  onChange: (next: AddModalState) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  // Prefer the providers list (richer label info); fall back to model groups
  // so we still allow adding models to profiles that have no entries yet.
  const optionIds = new Set<string>();
  const options: Array<{ id: string; label: string }> = [];
  for (const p of providers) {
    if (optionIds.has(p.id)) continue;
    optionIds.add(p.id);
    options.push({ id: p.id, label: p.label });
  }
  for (const [id] of providerEntries) {
    if (optionIds.has(id)) continue;
    optionIds.add(id);
    options.push({ id, label: id });
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="add-custom-model-title"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="add-custom-model-title" className="text-xl font-semibold text-[var(--text)]">
            Add custom model
          </h2>
          <button
            type="button"
            onClick={onCancel}
            className="text-[var(--text-dim)] hover:text-[var(--text)]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="mt-5 space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Provider</span>
            <select
              value={state.provider}
              onChange={(event) => onChange({ ...state, provider: event.target.value })}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            >
              {options.length === 0 && <option value="">No providers</option>}
              {options.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.label} ({opt.id})
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Model id</span>
            <input
              type="text"
              value={state.modelId}
              onChange={(event) => onChange({ ...state, modelId: event.target.value })}
              placeholder="e.g. claude-3-5-sonnet-20241022"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
              required
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Label (optional)</span>
            <input
              type="text"
              value={state.label}
              onChange={(event) => onChange({ ...state, label: event.target.value })}
              placeholder="Display label"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Context window (optional)</span>
            <input
              type="number"
              step={1}
              value={state.contextWindow}
              onChange={(event) => onChange({ ...state, contextWindow: event.target.value })}
              placeholder="200000"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            />
          </label>
        </div>

        {state.error && (
          <div className="mt-4 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {state.error}
          </div>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={state.busy}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-cyan-400/40 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={state.busy}
            className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
          >
            {state.busy ? "Adding…" : "Add model"}
          </button>
        </div>
      </form>
    </div>
  );
}

function EditCustomModelModal({
  state,
  providerLabel,
  onChange,
  onCancel,
  onSubmit,
}: {
  state: EditModalState;
  providerLabel: string;
  onChange: (next: EditModalState) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-custom-model-title"
    >
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="edit-custom-model-title" className="text-xl font-semibold text-[var(--text)]">
            Edit custom model
          </h2>
          <button
            type="button"
            onClick={onCancel}
            disabled={state.busy}
            className="text-[var(--text-dim)] hover:text-[var(--text)] disabled:opacity-60"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="mt-5 space-y-4">
          <div className="text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Provider</span>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)]">
              {providerLabel}{" "}
              <span className="font-mono text-xs text-[var(--text-dim)]">({state.provider})</span>
            </div>
          </div>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Model id</span>
            <input
              type="text"
              value={state.modelId}
              readOnly
              aria-readonly="true"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-[var(--text-dim)] outline-none"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Label</span>
            <input
              type="text"
              value={state.label}
              onChange={(event) => onChange({ ...state, label: event.target.value })}
              placeholder="Display label"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-[var(--text-dim)]">Context window (optional)</span>
            <input
              type="number"
              min={1}
              step={1}
              value={state.contextWindow}
              onChange={(event) => onChange({ ...state, contextWindow: event.target.value })}
              placeholder="200000"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-[var(--text)] outline-none focus:border-cyan-400/60"
            />
          </label>
        </div>

        {state.error && (
          <div className="mt-4 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {state.error}
          </div>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={state.busy}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-cyan-400/40 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={state.busy}
            className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
          >
            {state.busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </div>
  );
}

function DeleteConfirmModal({
  state,
  providerLabel,
  onCancel,
  onConfirm,
}: {
  state: DeleteConfirmState;
  providerLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-model-title"
    >
      <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl">
        <h2 id="delete-model-title" className="text-lg font-semibold text-[var(--text)]">
          Delete custom model?
        </h2>
        <p className="mt-2 text-sm text-[var(--text-dim)]">
          Remove <span className="font-mono text-[var(--text)]">{state.modelId}</span> from{" "}
          <span className="text-[var(--text)]">{providerLabel}</span>? This action cannot be undone.
        </p>

        {state.error && (
          <div className="mt-4 rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {state.error}
          </div>
        )}

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={state.busy}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-cyan-400/40 disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={state.busy}
            className="rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-400 disabled:opacity-60"
          >
            {state.busy ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
