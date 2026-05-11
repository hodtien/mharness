import { useEffect, useState } from "react";
import { api, type Project, type ProjectsResponse } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { toast } from "../store/toast";
import { useSession } from "../store/session";
import PageHeader from "../components/PageHeader";

export default function ProjectsPage() {
  const { setActiveProjectId } = useSession();
  const [data, setData] = useState<ProjectsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Inline edit draft
  const [draft, setDraft] = useState({ name: "", description: "" });

  // New project form
  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);
  const [newError, setNewError] = useState<string | null>(null);

  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = () => {
    setLoading(true);
    setError(null);
    api.listProjects()
      .then((resp) => setData(resp))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  const startEdit = (project: Project) => {
    setEditing(project.id);
    setDraft({ name: project.name, description: project.description ?? "" });
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft({ name: "", description: "" });
  };

  const saveEdit = async () => {
    if (!editing) return;
    if (!draft.name.trim()) {
      toast.error("Project name is required.");
      return;
    }
    const original = data?.projects.find((p) => p.id === editing);
    const noChanges =
      original &&
      draft.name.trim() === original.name.trim() &&
      draft.description === (original.description ?? "");
    if (noChanges) {
      setEditing(null);
      setSaving(false);
      toast.warn("No changes to save.");
      return;
    }
    setSaving(true);
    try {
      const patch: Record<string, string | null> = {};
      if (draft.name.trim()) patch.name = draft.name.trim();
      if (draft.description !== undefined) patch.description = draft.description;
      const updated = await api.updateProject(editing, patch);
      setData((prev) =>
        prev ? { ...prev, projects: prev.projects.map((p) => (p.id === editing ? updated : p)) } : prev,
      );
      setEditing(null);
      toast.success(`Project updated.`);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (projectId: string) => {
    setDeleting(projectId);
    try {
      await api.deleteProject(projectId);
      setData((prev) =>
        prev ? { ...prev, projects: prev.projects.filter((p) => p.id !== projectId) } : prev,
      );
      toast.success("Project deleted.");
    } catch (err) {
      toast.error(String(err));
    } finally {
      setDeleting(null);
    }
  };

  const handleActivate = async (projectId: string) => {
    if (activating !== null) return; // Prevent parallel activations
    const projectName = data?.projects.find((p) => p.id === projectId)?.name ?? projectId;
    setActivating(projectId);
    try {
      await api.activateProject(projectId);
      setActiveProjectId(projectId);
      setData((prev) =>
        prev ? { ...prev, active_project_id: projectId } : prev,
      );
      toast.success(`Switched to project: ${projectName}`);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setActivating(null);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) {
      setNewError("Project name is required.");
      return;
    }
    if (!newPath.trim()) {
      setNewError("Project path is required.");
      return;
    }
    setCreating(true);
    setNewError(null);
    try {
      const created = await api.createProject({
        name: newName.trim(),
        path: newPath.trim(),
        description: newDesc.trim() || undefined,
      });
      setData((prev) =>
        prev ? { ...prev, projects: [...prev.projects, created] } : prev,
      );
      setShowNewModal(false);
      setNewName("");
      setNewPath("");
      setNewDesc("");
      toast.success(`Project "${created.name}" created.`);
    } catch (err) {
      setNewError(String(err));
    } finally {
      setCreating(false);
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
    <div className="flex flex-1 flex-col overflow-hidden">
      <PageHeader
        title="Projects"
        description="Manage your registered project directories."
        primaryAction={
          <button
            type="button"
            onClick={() => setShowNewModal(true)}
            className="shrink-0 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400"
          >
            + New Project
          </button>
        }
        metadata={[
          {
            label: "Projects",
            value: String(data?.projects.length ?? 0),
          },
          ...(data?.active_project_id
            ? [
                {
                  label: "Active",
                  value:
                    data.projects.find((p) => p.id === data.active_project_id)?.name ??
                    data.active_project_id,
                  accent: "cyan" as const,
                },
              ]
            : []),
        ]}
      />

      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="w-full max-w-5xl space-y-6">
        {error && (
          <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
            {error}
          </div>
        )}

        {data?.projects.length === 0 && (
          <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 text-sm text-[var(--text-dim)] text-center">
            No projects yet. Click <strong>+ New Project</strong> to add one.
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          {data?.projects.map((project) => {
            const isEditing = editing === project.id;
            const isActive = data.active_project_id === project.id;
            const isDeleting = deleting === project.id;
            const isActivating = activating === project.id;
            return (
              <div
                key={project.id}
                className={`rounded-xl border bg-[var(--panel)] shadow-lg ${
                  isActive
                    ? "border-cyan-400/50 shadow-cyan-400/10"
                    : "border-[var(--border)]"
                }`}
              >
                <div className="p-5">
                  {/* Header row */}
                  {!isEditing ? (
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h2 className="truncate text-base font-semibold text-[var(--text)]">
                            {project.name}
                          </h2>
                          {isActive && (
                            <span className="shrink-0 rounded-full border border-cyan-400/40 bg-cyan-400/10 px-2 py-0.5 text-[11px] font-medium text-cyan-200">
                              active
                            </span>
                          )}
                        </div>
                        <p className="mt-1 truncate font-mono text-xs text-[var(--text-dim)]">
                          {project.path}
                        </p>
                        {project.description && (
                          <p className="mt-1 text-xs text-[var(--text-dim)]">
                            {project.description}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 flex-col gap-1.5">
                        {!isActive && (
                          <button
                            type="button"
                            onClick={() => handleActivate(project.id)}
                            disabled={isActivating}
                            className="shrink-0 rounded-lg border border-cyan-400/30 bg-cyan-500/10 px-3 py-1.5 text-xs text-cyan-300 hover:border-cyan-400/60 hover:bg-cyan-500/20 disabled:opacity-60"
                          >
                            {isActivating ? "Activating…" : "Activate"}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => startEdit(project)}
                          className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] hover:border-cyan-400/40 hover:text-[var(--text)]"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(project.id)}
                          disabled={isDeleting}
                          className="shrink-0 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-300 hover:border-red-400/60 hover:bg-red-500/20 disabled:opacity-60"
                        >
                          {isDeleting ? "Deleting…" : "Delete"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Name</span>
                        <input
                          type="text"
                          value={draft.name}
                          onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                        />
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Description</span>
                        <textarea
                          value={draft.description}
                          onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                          rows={2}
                          className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                        />
                      </label>
                      <div className="flex justify-end gap-2 pt-1">
                        <button
                          type="button"
                          onClick={cancelEdit}
                          disabled={saving}
                          className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text-dim)] hover:border-[var(--border)] hover:text-[var(--text)] disabled:opacity-60"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={saveEdit}
                          disabled={saving}
                          className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
                        >
                          {saving ? "Saving…" : "Save"}
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
      </div>

      {/* New Project Modal */}
      {showNewModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={(e) => { if (e.target === e.currentTarget) setShowNewModal(false); }}
        >
          <div className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--panel)] shadow-2xl">
            {/* Header */}
            <div className="sticky top-0 flex items-center justify-between border-b border-[var(--border)] bg-[var(--panel)] px-6 py-4">
              <h2 className="text-lg font-semibold text-[var(--text)]">New Project</h2>
              <button
                type="button"
                onClick={() => setShowNewModal(false)}
                className="text-[var(--text-dim)] hover:text-[var(--text)]"
              >
                ✕
              </button>
            </div>

            {/* Body */}
            <div className="p-6 space-y-4">
              {newError && (
                <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-sm text-red-200">
                  {newError}
                </div>
              )}
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Project Name</span>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. My App"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                  autoFocus
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Project Path</span>
                <input
                  type="text"
                  value={newPath}
                  onChange={(e) => setNewPath(e.target.value)}
                  placeholder="/absolute/path/to/project"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 font-mono text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Description (optional)</span>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  rows={3}
                  placeholder="Brief description of the project…"
                  className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                />
              </label>
            </div>

            {/* Footer */}
            <div className="flex justify-end gap-3 border-t border-[var(--border)] px-6 py-4">
              <button
                type="button"
                onClick={() => setShowNewModal(false)}
                disabled={creating}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text-dim)] hover:border-[var(--border)] hover:text-[var(--text)] disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating}
                className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:opacity-60"
              >
                {creating ? "Creating…" : "Create Project"}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDeleteId && (
        <DeleteConfirmDialog
          projectName={data?.projects.find((p) => p.id === confirmDeleteId)?.name ?? ""}
          onConfirm={() => { handleDelete(confirmDeleteId); setConfirmDeleteId(null); }}
          onCancel={() => setConfirmDeleteId(null)}
        />
      )}
    </div>
  );
}

// Delete confirmation dialog
function DeleteConfirmDialog({
  projectName,
  onConfirm,
  onCancel,
}: {
  projectName: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div className="w-full max-w-sm rounded-2xl border border-red-400/30 bg-[var(--panel)] shadow-2xl">
        <div className="p-6">
          <h3 className="text-base font-semibold text-[var(--text)]">Delete Project?</h3>
          <p className="mt-2 text-sm text-[var(--text-dim)]">
            Are you sure you want to delete <strong>{projectName}</strong>? This cannot be undone.
          </p>
        </div>
        <div className="flex justify-end gap-3 border-t border-[var(--border)] px-6 py-4">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text-dim)] hover:border-[var(--border)] hover:text-[var(--text)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-lg border border-red-400/50 bg-red-500/20 px-4 py-2 text-sm font-medium text-red-200 hover:border-red-400 hover:bg-red-500/30"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
