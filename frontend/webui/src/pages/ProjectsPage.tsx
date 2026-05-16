import { useEffect, useState } from "react";
import { api, type Project, type ProjectsResponse } from "../api/client";
import LoadingSkeleton from "../components/LoadingSkeleton";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import { toast } from "../store/toast";
import { useSession } from "../store/session";
import PageHeader from "../components/PageHeader";
import { PathDisplay } from "../components/PathDisplay";

type ViewFilter = "all" | "active" | "existing" | "missing" | "temp" | "worktree";

const FILTER_LABELS: Record<ViewFilter, string> = {
  all: "All",
  active: "Active",
  existing: "Existing",
  missing: "Missing",
  temp: "Temp / Test",
  worktree: "Worktrees",
};

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
  const [confirmDeleteName, setConfirmDeleteName] = useState<string>("");

  // View filter (default: hide temp-like projects, persisted across reloads)
  const [viewFilter, setViewFilter] = useState<ViewFilter>(() => {
    try {
      const saved = localStorage.getItem("oh_projects_filter");
      if (saved && Object.keys(FILTER_LABELS).includes(saved)) {
        return saved as ViewFilter;
      }
    } catch {
      // localStorage unavailable (e.g. SSR), fall through to default
    }
    return "active";
  });

  // Persist filter selection when it changes
  useEffect(() => {
    try {
      localStorage.setItem("oh_projects_filter", viewFilter);
    } catch {
      // ignore storage errors
    }
  }, [viewFilter]);

  // Stale banner state (dismissible per session)
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // Client-side search filter
  const [searchQuery, setSearchQuery] = useState("");

  // Inline edit draft
  const [draft, setDraft] = useState({ name: "", description: "" });

  // New project form
  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);
  const [newError, setNewError] = useState<string | null>(null);

  // Reset new project form state
  const resetNewForm = () => {
    setNewName("");
    setNewPath("");
    setNewDesc("");
    setNewError(null);
  };

  // New project modal is valid when name and path are non-empty
  const isNewFormValid = newName.trim().length > 0 && newPath.trim().length > 0;

  // Close new project modal handler
  const closeNewModal = () => {
    setShowNewModal(false);
    resetNewForm();
  };

  // Cleanup modal
  const [showCleanupModal, setShowCleanupModal] = useState(false);
  const [cleanupFilter, setCleanupFilter] = useState<ViewFilter>("temp");
  const [cleanupPreview, setCleanupPreview] = useState<number | null>(null);
  const [cleanupLoading, setCleanupLoading] = useState(false);

  // Global keyboard handler for modal Escape key (handles focus outside modal content)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (showNewModal) {
        closeNewModal();
      } else if (showCleanupModal) {
        setShowCleanupModal(false);
        setCleanupPreview(null);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [showNewModal, showCleanupModal]);

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

  const handleCleanupPreview = async (filter?: ViewFilter) => {
    const selectedFilter = filter ?? cleanupFilter;
    setCleanupLoading(true);
    setCleanupPreview(null);
    try {
      const apiFilter: Record<string, boolean> = {};
      if (selectedFilter === "missing") apiFilter.missing_only = true;
      else if (selectedFilter === "temp") apiFilter.temp_like_only = true;
      else if (selectedFilter === "worktree") apiFilter.worktree_like_only = true;
      const result = await api.cleanupProjects(apiFilter);
      setCleanupPreview(result.preview_count ?? 0);
    } catch (err) {
      toast.error(String(err));
    } finally {
      setCleanupLoading(false);
    }
  };

  const handleCleanupConfirm = async () => {
    setCleanupLoading(true);
    try {
      const filter: Record<string, boolean> = {};
      if (cleanupFilter === "missing") filter.missing_only = true;
      else if (cleanupFilter === "temp") filter.temp_like_only = true;
      else if (cleanupFilter === "worktree") filter.worktree_like_only = true;
      filter.confirmed = true;
      const result = await api.cleanupProjects(filter);
      const count = result.deleted_count ?? 0;
      setShowCleanupModal(false);
      setCleanupPreview(null);
      toast.success(`Removed ${count} project record${count !== 1 ? "s" : ""} from registry.`);
      loadProjects();
    } catch (err) {
      toast.error(String(err));
    } finally {
      setCleanupLoading(false);
    }
  };

  // Apply view filter and search
  const lowerQ = searchQuery.trim().toLowerCase();
  const projects = data?.projects ?? [];
  const filteredProjects = projects.filter((p) => {
    // Search filter
    if (lowerQ) {
      if (!p.name.toLowerCase().includes(lowerQ) && !p.path.toLowerCase().includes(lowerQ)) {
        return false;
      }
    }
    // View filter
    switch (viewFilter) {
      case "active":
        return p.id === data?.active_project_id;
      case "existing":
        return p.exists !== false;
      case "missing":
        return p.exists === false;
      case "temp":
        return p.is_temp_like === true;
      case "worktree":
        return p.is_worktree_like === true;
      case "all":
      default:
        return true;
    }
  });

  // Count badges for badges
  const tempCount = projects.filter((p) => p.is_temp_like === true).length;
  const missingCount = projects.filter((p) => p.exists === false).length;

  const activeProjectId = data?.active_project_id ?? null;
  const orderedProjects = [...filteredProjects].sort((a, b) => {
    if (a.id === activeProjectId) return -1;
    if (b.id === activeProjectId) return 1;
    return 0;
  });

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
          {error && <ErrorBanner message={`Failed to load projects${error ? `: ${error}` : "."}`} />}

          {/* Stale registry warning banner */}
          {!bannerDismissed && projects.length > 0 && tempCount + missingCount >= 3 && (
            <div className="rounded-lg border border-orange-400/40 bg-orange-500/10 px-4 py-3 text-sm">
              <div className="flex items-start gap-3">
                <span aria-hidden className="mt-0.5 shrink-0 text-base">⚠️</span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-orange-200">
                    Your registry has {tempCount + missingCount} stale entries ({missingCount} missing, {tempCount} temp).
                  </p>
                  <p className="mt-1 text-orange-300/80">
                    Use the <strong>Cleanup</strong> button to remove registry records — your actual project directories are not affected.
                  </p>
                </div>
                <button
                  type="button"
                  aria-label="Dismiss warning"
                  onClick={() => setBannerDismissed(true)}
                  className="shrink-0 rounded px-2 py-1 text-xs text-orange-400 hover:bg-orange-400/20"
                >
                  ✕
                </button>
              </div>
            </div>
          )}

          {projects.length === 0 && (
            <EmptyState
              message="No projects yet."
              description="Create your first project to get started."
              action={{ label: "+ New Project", onClick: () => setShowNewModal(true) }}
            />
          )}

          {!!projects.length && (
            <>
              {/* Toolbar: filter tabs + search */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex flex-wrap gap-1" role="tablist" aria-label="Project filter">
                  {(Object.keys(FILTER_LABELS) as ViewFilter[]).map((f) => (
                    <button
                      key={f}
                      type="button"
                      role="tab"
                      aria-selected={viewFilter === f}
                      onClick={() => setViewFilter(f)}
                      className={`shrink-0 rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                        viewFilter === f
                          ? "border-cyan-400/60 bg-cyan-500/20 text-cyan-200"
                          : "border-[var(--border)] bg-[var(--panel-2)] text-[var(--text-dim)] hover:border-cyan-400/40 hover:text-[var(--text)]"
                      }`}
                    >
                      {FILTER_LABELS[f]}
                      {f === "temp" && tempCount > 0 && (
                        <span className="ml-1 rounded-full bg-orange-500/20 px-1.5 py-0.5 text-[10px] text-orange-300">
                          {tempCount}
                        </span>
                      )}
                      {f === "missing" && missingCount > 0 && (
                        <span className="ml-1 rounded-full bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-300">
                          {missingCount}
                        </span>
                      )}
                    </button>
                  ))}
                </div>

                <div className="flex-1" />

                {/* Cleanup button */}
                {(tempCount > 0 || missingCount > 0) && (
                  <button
                    type="button"
                    onClick={() => {
                      const targetFilter: ViewFilter = missingCount > 0 ? "missing" : "temp";
                      setShowCleanupModal(true);
                      setCleanupFilter(targetFilter);
                      handleCleanupPreview(targetFilter);
                    }}
                    className="shrink-0 rounded-lg border border-orange-400/30 bg-orange-500/10 px-3 py-1.5 text-xs text-orange-300 hover:border-orange-400/60 hover:bg-orange-500/20"
                  >
                    🧹 Cleanup
                  </button>
                )}

                <input
                  type="text"
                  placeholder="Search by name or path…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-56 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                />
                {searchQuery && (
                  <span className="shrink-0 text-xs text-[var(--text-dim)]">
                    {filteredProjects.length} / {projects.length}
                  </span>
                )}
              </div>
            </>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            {orderedProjects.map((project) => {
              const isEditing = editing === project.id;
              const isActive = activeProjectId === project.id;
              const isDeleting = deleting === project.id;
              const isActivating = activating === project.id;
              return (
                <div
                  key={project.id}
                  className={`group rounded-xl border bg-[var(--panel)] shadow-lg transition ${
                    isActive
                      ? "border-cyan-400/50 shadow-cyan-400/10 ring-1 ring-cyan-400/20"
                      : "border-[var(--border)]"
                  }`}
                >
                  <div className="p-5">
                    {/* Header row */}
                    {!isEditing ? (
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            {isActive && (
                              <span aria-hidden className="shrink-0 text-[10px] text-cyan-400">📌</span>
                            )}
                            <h2 className="truncate text-base font-semibold text-[var(--text)]">
                              {project.name}
                            </h2>
                            {isActive && (
                              <span className="shrink-0 rounded-full border border-cyan-400/40 bg-cyan-400/10 px-2 py-0.5 text-[11px] font-medium text-cyan-200">
                                active
                              </span>
                            )}
                            {!isActive && project.is_temp_like && (
                              <span className="shrink-0 rounded-full border border-orange-400/40 bg-orange-400/10 px-2 py-0.5 text-[11px] font-medium text-orange-200">
                                temp
                              </span>
                            )}
                            {!isActive && project.exists === false && (
                              <span className="shrink-0 rounded-full border border-red-400/40 bg-red-400/10 px-2 py-0.5 text-[11px] font-medium text-red-200">
                                missing
                              </span>
                            )}
                            {!isActive && project.is_worktree_like && (
                              <span className="shrink-0 rounded-full border border-purple-400/40 bg-purple-400/10 px-2 py-0.5 text-[11px] font-medium text-purple-200">
                                worktree
                              </span>
                            )}
                          </div>
                          <div className="mt-1 flex items-center gap-1">
                            <PathDisplay path={project.path} maxLen={48} copyLabel={`Copy path for ${project.name}`} />
                          </div>
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
                            aria-label={`Delete project ${project.name}`}
                            onClick={() => { setConfirmDeleteId(project.id); setConfirmDeleteName(project.name); }}
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

          {/* Empty filter state */}
          {projects.length > 0 && filteredProjects.length === 0 && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-8 text-center">
              <p className="text-sm text-[var(--text-dim)]">
                No projects match the current filter.
              </p>
              <button
                type="button"
                onClick={() => { setViewFilter("all"); setSearchQuery(""); }}
                className="mt-3 text-xs text-cyan-400 hover:underline"
              >
                Clear filters
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation dialog */}
      {confirmDeleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl">
            <h2 className="mb-3 text-base font-semibold text-[var(--text)]">
              Delete Project
            </h2>
            <p className="mb-5 text-sm text-[var(--text-dim)]">
              Are you sure you want to delete <strong>{confirmDeleteName}</strong>?
              This only removes the project record from the registry — no directories are deleted.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDeleteId(null)}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-[var(--border)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  const id = confirmDeleteId;
                  setConfirmDeleteId(null);
                  handleDelete(id);
                }}
                className="rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-400"
              >
                Confirm delete project
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New project modal */}
      {showNewModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={closeNewModal}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => { if (e.key === "Escape") closeNewModal(); }}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-[var(--text)]">New Project</h2>
              <button
                type="button"
                onClick={closeNewModal}
                aria-label="Close modal"
                className="shrink-0 rounded-lg p-1 text-[var(--text-dim)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
              >
                ✕
              </button>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Name</span>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="My App"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Path</span>
                <input
                  type="text"
                  value={newPath}
                  onChange={(e) => setNewPath(e.target.value)}
                  placeholder="/path/to/project"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-dim)]">Description (optional)</span>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  rows={2}
                  className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-cyan-400/60"
                />
              </label>
              {newError && <p className="text-xs text-red-400">{newError}</p>}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeNewModal}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-[var(--border)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || !isNewFormValid}
                className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {creating ? "Creating…" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cleanup confirmation modal */}
      {showCleanupModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => { setShowCleanupModal(false); setCleanupPreview(null); }}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-[var(--border)] bg-[var(--panel)] p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => { if (e.key === "Escape") { setShowCleanupModal(false); setCleanupPreview(null); } }}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-[var(--text)]">🧹 Cleanup Projects</h2>
              <button
                type="button"
                onClick={() => { setShowCleanupModal(false); setCleanupPreview(null); }}
                aria-label="Close modal"
                className="shrink-0 rounded-lg p-1 text-[var(--text-dim)] hover:bg-[var(--panel-2)] hover:text-[var(--text)]"
              >
                ✕
              </button>
            </div>
            <p className="mb-3 text-sm text-[var(--text-dim)]">
              Remove registered project records for paths that no longer exist or are temporary test directories.
              <strong> This only unregisters the records — no directories are deleted.</strong>
            </p>
            <div className="mb-4 space-y-2">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text)]">
                <input
                  type="radio"
                  name="cleanupFilter"
                  value="temp"
                  checked={cleanupFilter === "temp"}
                  onChange={() => {
                    setCleanupFilter("temp");
                    handleCleanupPreview("temp");
                  }}
                />
                Temp / Test projects
                {tempCount > 0 && <span className="ml-1 text-xs text-orange-400">({tempCount})</span>}
              </label>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text)]">
                <input
                  type="radio"
                  name="cleanupFilter"
                  value="missing"
                  checked={cleanupFilter === "missing"}
                  onChange={() => {
                    setCleanupFilter("missing");
                    handleCleanupPreview("missing");
                  }}
                />
                Missing projects
                {missingCount > 0 && <span className="ml-1 text-xs text-red-400">({missingCount})</span>}
              </label>
            </div>
            {cleanupPreview !== null && (
              <div className="mb-4 rounded-lg border border-orange-400/30 bg-orange-500/10 p-3 text-sm text-orange-200">
                This will remove <strong>{cleanupPreview}</strong> project record{cleanupPreview !== 1 ? "s" : ""} from the registry.
              </div>
            )}
            {cleanupPreview === 0 && (
              <div className="mb-4 text-sm text-[var(--text-dim)]">No matching projects found.</div>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { setShowCleanupModal(false); setCleanupPreview(null); }}
                className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-4 py-2 text-sm text-[var(--text)] hover:border-[var(--border)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCleanupConfirm}
                disabled={cleanupLoading || cleanupPreview === 0}
                className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-400 disabled:opacity-60"
              >
                {cleanupLoading ? "Working…" : "Confirm cleanup"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
