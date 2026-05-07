import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { api, type Project, type ProjectsResponse } from "../api/client";
import { toast } from "../store/toast";

/** Truncates a path string for display: shows leading ~ or first segment + trailing segment. */
function truncatePath(path: string, maxLen = 36): string {
  if (!path) return "";
  if (path.length <= maxLen) return path;
  // Try: ~/.../<last-segment>
  const home = path.startsWith("~") ? "~" : null;
  const base = home ? path.slice(1) : path;
  const segs = base.split("/").filter(Boolean);
  if (segs.length <= 1) return home ? `~/${segs[0]?.slice(0, maxLen - 3)}…` : path.slice(0, maxLen);
  const last = segs[segs.length - 1];
  const prefix = home ? "~/" : "/";
  const avail = maxLen - last.length - prefix.length - 2;
  if (avail > 4) {
    return `${prefix}${segs[0].slice(0, avail)}…/${last}`;
  }
  return `${prefix}…/${last}`;
}

export default function ProjectSelector() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ProjectsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.listProjects()
      .then((resp) => setData(resp))
      .catch((err) => setError(String(err)))
      .finally(() => setLoading(false));
  }, []);

  const activeProject: Project | undefined = data?.projects.find(
    (p) => p.id === data.active_project_id,
  );

  const handleActivate = async (projectId: string) => {
    const project = data?.projects.find((p) => p.id === projectId);
    const projectName = project?.name ?? projectId;
    setActivating(projectId);
    try {
      await api.activateProject(projectId);
      // Show toast before reloading
      toast.success(`Switched to project: ${projectName}`);
      // Reload the page so the backend re-initializes with the new project context.
      window.location.reload();
    } catch (err) {
      setError(String(err));
      setActivating(null);
    }
  };

  return (
    <div ref={dropRef} className="relative">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-md border border-[var(--border)] bg-[var(--panel-2)] px-2 py-1.5 text-[13px] text-[var(--text)] transition hover:border-[var(--accent)] hover:bg-[var(--panel)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <span aria-hidden>📁</span>
          <span className="truncate">
            {loading
              ? "Loading…"
              : error
                ? "Error"
                : activeProject?.name ?? "No project"}
          </span>
        </span>
        <span aria-hidden className="shrink-0 text-[var(--text-dim)]">
          {open ? "▲" : "▼"}
        </span>
      </button>

      {/* Dropdown menu */}
      {open && (
        <div
          role="listbox"
          aria-label="Select project"
          className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded-md border border-[var(--border)] bg-[var(--panel)] shadow-xl"
        >
          {loading ? (
            <div className="px-3 py-2 text-xs text-[var(--text-dim)]">Loading…</div>
          ) : error ? (
            <div className="px-3 py-2 text-xs text-red-300">{error}</div>
          ) : data?.projects.length === 0 ? (
            <div className="px-3 py-2 text-xs text-[var(--text-dim)]">No projects.</div>
          ) : (
            <ul className="max-h-72 overflow-y-auto py-1">
              {data!.projects.map((project) => {
                const isActive = project.id === data!.active_project_id;
                const isActivatingThis = activating === project.id;
                return (
                  <li key={project.id} role="option" aria-selected={isActive}>
                    <button
                      type="button"
                      disabled={isActivatingThis}
                      onClick={() => {
                        if (isActive) {
                          setOpen(false);
                          return;
                        }
                        handleActivate(project.id);
                      }}
                      className={
                        "flex w-full flex-col items-start gap-0.5 border-b border-[var(--border)] px-3 py-2 text-left text-[13px] transition last:border-b-0 disabled:cursor-wait disabled:opacity-60 " +
                        (isActive
                          ? "bg-[var(--accent-strong)]/10 text-[var(--text)]"
                          : "hover:bg-[var(--panel-2)] text-[var(--text)]")
                      }
                    >
                      <span className="flex w-full items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-1.5">
                          {isActive && (
                            <span aria-hidden className="shrink-0 text-[10px] text-[var(--accent)]">
                              ●
                            </span>
                          )}
                          <span className="truncate font-medium">{project.name}</span>
                        </span>
                        {isActivatingThis && (
                          <span className="shrink-0 text-[10px] text-[var(--text-dim)]">
                            Switching…
                          </span>
                        )}
                      </span>
                      <span className="truncate pl-[1.15rem] text-[11px] text-[var(--text-dim)]">
                        {truncatePath(project.path)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {/* Footer link */}
          <div className="border-t border-[var(--border)] px-3 py-1.5">
            <NavLink
              to="/projects"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 text-[11px] text-[var(--text-dim)] transition hover:text-[var(--text)]"
            >
              <span aria-hidden>⚙️</span>
              <span>Manage Projects</span>
            </NavLink>
          </div>
        </div>
      )}
    </div>
  );
}
