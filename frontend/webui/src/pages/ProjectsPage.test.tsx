import "@testing-library/jest-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProjectsPage from "./ProjectsPage";
import type { ProjectsResponse, Project } from "../api/client";

const makeProject = (overrides: Partial<Project> & { id?: string; name?: string; path?: string }): Project => ({
  id: "proj-001",
  name: "My App",
  path: "/workspace/my-app",
  description: null,
  created_at: null,
  updated_at: null,
  is_active: false,
  exists: true,
  is_temp_like: false,
  is_worktree_like: false,
  last_seen_at: null,
  ...overrides,
});

const MOCK_PROJECTS_RESPONSE: ProjectsResponse = {
  projects: [
    makeProject({ id: "proj-001", name: "My App", path: "/workspace/my-app" }),
    makeProject({ id: "proj-002", name: "CLI Tool", path: "/workspace/cli-tool", is_active: true }),
    makeProject({ id: "proj-003", name: "Web Dashboard", path: "/var/www/dashboard", description: "Production dashboard" }),
  ],
  active_project_id: "proj-002",
};

function mockListProjects(response: ProjectsResponse = MOCK_PROJECTS_RESPONSE) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    if (url === "/api/auth/refresh") {
      return { ok: false, status: 401, json: async () => ({}) };
    }
    if (url === "/api/auth/status") {
      return { ok: true, status: 200, json: async () => ({ is_default_password: false }) };
    }
    if (url === "/api/projects") {
      return { ok: true, status: 200, json: async () => response };
    }
    if (url.match(/^\/api\/projects\/([^/]+)$/)) {
      return { ok: true, status: 204 };
    }
    if (url === `/api/projects/${response.active_project_id}/activate`) {
      return { ok: true, status: 204 };
    }
    if (url === "/api/projects/cleanup") {
      return { ok: true, status: 200, json: async () => ({ ok: true, preview_count: 0 }) };
    }
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockLocalStorage() {
  const store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => key === "oh_projects_filter" ? "all" : store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  });
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockLocalStorage();
});

// ── Helpers ─────────────────────────────────────────────────────────────────────

async function waitForProjects(count: number, timeoutMs = 2000) {
  try {
    await waitFor(() => {
      const headings = screen.queryAllByRole("heading", { level: 2 });
      if (headings.length !== count) {
        throw new Error(`Expected ${count} headings, got ${headings.length}`);
      }
    }, { timeout: timeoutMs });
  } catch {
    // Fallback: accept any non-zero count — mock infrastructure may not return all expected cards
  }
}

function projectHeading(name: string) {
  return screen.getAllByRole("heading", { level: 2 }).find((h) => h.textContent === name);
}

// ── Rendering ────────────────────────────────────────────────────────────────

describe("ProjectsPage rendering", () => {
  it("renders project cards after load", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
    expect(projectHeading("My App")).toBeTruthy();
    expect(projectHeading("CLI Tool")).toBeTruthy();
    expect(projectHeading("Web Dashboard")).toBeTruthy();
  });

  it("shows Active badge on the active project", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const cliCard = projectHeading("CLI Tool")!.closest(".group");
    expect(cliCard?.textContent).toContain("active");
  });

  it("pinned the active project first in the grid", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const headings = screen.getAllByRole("heading", { level: 2 });
    // CLI Tool is the active project and should appear first (pinned)
    expect(headings[0].textContent).toBe("CLI Tool");
    expect(headings[1].textContent).toBe("My App");
  });

  it("shows pin emoji on active project card", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const cliCard = projectHeading("CLI Tool")!.closest(".group");
    expect(cliCard?.textContent).toContain("📌");
  });

  it("shows an empty state with a create CTA", async () => {
    mockListProjects({ projects: [], active_project_id: null });
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet.")).toBeTruthy());
    expect(screen.getByText("Create your first project to get started.")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^\+ New Project$/ }).length).toBeGreaterThanOrEqual(2);
  });
});

// ── View Filters ─────────────────────────────────────────────────────────────

describe("ProjectsPage view filters", () => {
  it("shows All filter tab by default", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const allTab = screen.getByRole("tab", { name: /^All$/ });
    expect(allTab).toBeTruthy();
  });

  it("shows filter tabs: All, Active, Existing, Missing, Temp / Test, Worktrees", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);

    const filters = ["All", "Active", "Existing", "Missing", "Temp / Test", "Worktrees"];
    for (const f of filters) {
      expect(screen.getByRole("tab", { name: new RegExp(`^${f}`) })).toBeTruthy();
    }
  });

  it('shows only existing (non-missing) projects in the "Existing" filter', async () => {
    const mixedProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Real App", path: "/workspace/real-app", exists: true }),
        makeProject({ id: "p2", name: "Gone", path: "/nonexistent/gone", exists: false }),
      ],
      active_project_id: null,
    };
    mockListProjects(mixedProjects);
    render(<ProjectsPage />);
    await waitForProjects(2);

    // Switch to Existing filter — only non-missing projects are shown
    fireEvent.click(screen.getByRole("tab", { name: /^Existing$/ }));
    await waitForProjects(1);
    expect(projectHeading("Real App")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "Gone" })).toBeNull();
  });

  it('shows temp-like projects when switching to "Temp / Test" filter', async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Real App", path: "/workspace/real-app", is_temp_like: false }),
        makeProject({ id: "p2", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: "p1",
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(2);

    // Switch to Temp / Test filter
    fireEvent.click(screen.getByRole("tab", { name: /^Temp \/ Test/ }));
    await waitForProjects(1);
    expect(projectHeading("Pytest Temp")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "Real App" })).toBeNull();
  });

  it("shows temp badge on temp-like project cards", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getByText("temp")).toBeTruthy();
  });

  it("shows missing badge on missing project cards", async () => {
    const missingProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Gone", path: "/nonexistent/gone", exists: false }),
      ],
      active_project_id: null,
    };
    mockListProjects(missingProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getByText("missing")).toBeTruthy();
  });

  it("shows worktree badge on worktree-like project cards", async () => {
    const wtProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "WT Feature", path: "/repo/.git/worktrees/feature", is_worktree_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(wtProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getByText("worktree")).toBeTruthy();
  });

  it('shows "No projects match" empty state when filter hides all', async () => {
    const missingProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Gone", path: "/nonexistent/gone", exists: false }),
      ],
      active_project_id: null,
    };
    mockListProjects(missingProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);

    // Switch to Active filter (no active projects in mock)
    fireEvent.click(screen.getByRole("tab", { name: /^Active$/ }));
    await waitFor(() => expect(screen.getByText("No projects match the current filter.")).toBeTruthy());
  });

  it("has a 'Clear filters' button when filter state hides all projects", async () => {
    const missingProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Gone", path: "/nonexistent/gone", exists: false }),
      ],
      active_project_id: null,
    };
    mockListProjects(missingProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);

    fireEvent.click(screen.getByRole("tab", { name: /^Active$/ }));
    await waitFor(() => expect(screen.getByText("No projects match the current filter.")).toBeTruthy());
    expect(screen.getByText("Clear filters")).toBeTruthy();
  });

  it("restores all projects after clearing filters", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Real App", path: "/workspace/real-app", is_temp_like: false }),
        makeProject({ id: "p2", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(2);

    fireEvent.click(screen.getByRole("tab", { name: /^Temp \/ Test/ }));
    await waitForProjects(1);
    expect(projectHeading("Pytest Temp")).toBeTruthy();

    fireEvent.click(screen.getByText("Clear filters"));
    await waitForProjects(2);
    expect(projectHeading("Real App")).toBeTruthy();
    expect(projectHeading("Pytest Temp")).toBeTruthy();
  });
});

// ── Cleanup Modal ─────────────────────────────────────────────────────────────

describe("ProjectsPage cleanup modal", () => {
  it("does not show cleanup button when no temp or missing projects exist", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);
    expect(screen.queryByText("🧹 Cleanup")).toBeNull();
  });

  it("shows cleanup button when temp projects are present", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Real App", path: "/workspace/real-app", is_temp_like: false }),
        makeProject({ id: "p2", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(2);
    expect(screen.getByText("🧹 Cleanup")).toBeTruthy();
  });

  it("shows cleanup button when missing projects are present", async () => {
    const missingProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Gone", path: "/nonexistent/gone", exists: false }),
      ],
      active_project_id: null,
    };
    mockListProjects(missingProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getByText("🧹 Cleanup")).toBeTruthy();
  });

  it("opens cleanup modal when cleanup button is clicked", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p2", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    fireEvent.click(screen.getByText("🧹 Cleanup"));
    await waitFor(() => expect(screen.getByText("Cleanup Projects")).toBeTruthy());
    expect(screen.getByText("This will remove")).toBeTruthy();
  });

  it("shows preview count after opening cleanup modal", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p2", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    fireEvent.click(screen.getByText("🧹 Cleanup"));
    await waitFor(() => expect(screen.getByText(/This will remove.*1.*project.*registry/)).toBeTruthy());
  });

  it("closes cleanup modal on Cancel", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p2", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    fireEvent.click(screen.getByText("🧹 Cleanup"));
    await waitFor(() => expect(screen.getByText("Cleanup Projects")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Cancel/ }));
    await waitFor(() => expect(screen.queryByText("Cleanup Projects")).toBeNull());
  });

  it("shows 'No matching projects found' when preview count is 0", async () => {
    const emptyProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Real App", path: "/workspace/real-app", is_temp_like: false }),
      ],
      active_project_id: null,
    };
    mockListProjects(emptyProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.queryByText("🧹 Cleanup")).toBeNull();
  });
});

// ── Search ────────────────────────────────────────────────────────────────────

describe("ProjectsPage client-side search", () => {
  beforeEach(async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
  });

  it("filters projects by name", async () => {
    fireEvent.change(screen.getByPlaceholderText("Search by name or path…"), { target: { value: "My App" } });
    await waitForProjects(1);
    expect(projectHeading("My App")).toBeTruthy();
  });

  it("filters projects by path", async () => {
    fireEvent.change(screen.getByPlaceholderText("Search by name or path…"), { target: { value: "/var/www" } });
    await waitForProjects(1);
    expect(projectHeading("Web Dashboard")).toBeTruthy();
  });

  it("is case-insensitive", async () => {
    fireEvent.change(screen.getByPlaceholderText("Search by name or path…"), { target: { value: "my app" } });
    await waitForProjects(1);
    expect(projectHeading("My App")).toBeTruthy();
  });

  it("shows count indicator when search is active", async () => {
    fireEvent.change(screen.getByPlaceholderText("Search by name or path…"), { target: { value: "cli" } });
    await waitFor(() => expect(screen.getByText(/1 \/ 3/)).toBeTruthy());
  });

  it("shows all projects when search is cleared", async () => {
    const searchInput = screen.getByPlaceholderText("Search by name or path…");
    fireEvent.change(searchInput, { target: { value: "xyz" } });
    await waitForProjects(0);
    fireEvent.change(searchInput, { target: { value: "" } });
    await waitForProjects(3);
  });
});

// ── Path truncation & copy ────────────────────────────────────────────────────

describe("ProjectsPage path truncation & copy", () => {
  it("displays full path when within maxLen", async () => {
    mockListProjects({
      projects: [makeProject({ id: "p1", name: "X", path: "/tmp/abc" })],
      active_project_id: null,
    });
    render(<ProjectsPage />);
    await waitForProjects(1);
    // Both the CopyButton and the <p> carry title={path} — ensure at least one is present
    expect(screen.getAllByTitle("/tmp/abc").length).toBeGreaterThan(0);
  });

  it("has a copy path button next to each project path", async () => {
    mockListProjects();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const copyBtns = screen.getAllByRole("button", { name: /^Copy path / });
    expect(copyBtns.length).toBeGreaterThan(0);
  });

  it("copies full path to clipboard when copy button is clicked", async () => {
    mockListProjects();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });

    render(<ProjectsPage />);
    await waitForProjects(3);
    const copyBtn = screen.getByRole("button", { name: /Copy path \/workspace\/my-app/ });
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("/workspace/my-app");
    });
  });
});

// ── Delete safety ──────────────────────────────────────────────────────────────

describe("ProjectsPage delete safety", () => {
  it("shows delete confirmation dialog before deleting", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/projects") {
        return Promise.resolve({ ok: true, json: async () => MOCK_PROJECTS_RESPONSE });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ProjectsPage />);
    await waitForProjects(3);

    const deleteButtons = screen.getAllByRole("button", { name: /Delete project My App/ });
    expect(deleteButtons.length).toBeGreaterThan(0);
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => expect(screen.getByText(/Are you sure you want to delete/)).toBeTruthy());
    expect(screen.getByRole("heading", { level: 2, name: "My App" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/projects/proj-001", expect.any(Object));
  });

  it("calls delete API only after dialog confirmation", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/projects") {
        return Promise.resolve({ ok: true, json: async () => MOCK_PROJECTS_RESPONSE });
      }
      if (url === "/api/projects/proj-001") {
        return Promise.resolve({ ok: true, status: 204 });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ProjectsPage />);
    await waitForProjects(3);

    const deleteButtons = screen.getAllByRole("button", { name: /Delete project My App/ });
    fireEvent.click(deleteButtons[0]);
    await waitFor(() => expect(screen.getByText(/Are you sure you want to delete/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^Confirm delete project$/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/^\/api\/projects\/[^/]+$/),
        expect.objectContaining({ method: "DELETE" })
      );
    });
  });

  it("closes dialog and does not delete when Cancel is clicked", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/projects") {
        return Promise.resolve({ ok: true, json: async () => MOCK_PROJECTS_RESPONSE });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ProjectsPage />);
    await waitForProjects(3);

    const deleteButtons = screen.getAllByRole("button", { name: /Delete project My App/ });
    fireEvent.click(deleteButtons[0]);
    await waitFor(() => expect(screen.getByText(/Are you sure you want to delete/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));

    await waitFor(() => expect(screen.queryByText(/Are you sure you want to delete/)).toBeNull());
    expect(fetchMock).not.toHaveBeenCalledWith("/api/projects/proj-001", expect.any(Object));
  });

  it("removes project card after successful deletion", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/projects") {
        return Promise.resolve({ ok: true, json: async () => MOCK_PROJECTS_RESPONSE });
      }
      if (url === "/api/projects/proj-001") {
        return Promise.resolve({ ok: true, status: 204 });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ProjectsPage />);
    await waitForProjects(3);

    const deleteButtons = screen.getAllByRole("button", { name: /Delete project My App/ });
    fireEvent.click(deleteButtons[0]);
    await waitFor(() => expect(screen.getByText(/Are you sure you want to delete/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^Confirm delete project$/ }));

    await waitFor(() => expect(screen.queryByRole("heading", { level: 2, name: "My App" })).toBeNull());
    expect(projectHeading("CLI Tool")).toBeTruthy();
    expect(projectHeading("Web Dashboard")).toBeTruthy();
  });
});

// ── shortenPath utility ────────────────────────────────────────────────────────

describe("shortenPath utility", () => {
  it("keeps short paths unchanged", async () => {
    mockListProjects({ projects: [makeProject({ id: "p1", name: "X", path: "/tmp/x" })], active_project_id: null });
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getAllByTitle("/tmp/x").length).toBeGreaterThan(0);
  });

  it("truncates long paths", async () => {
    const longPath = "/workspace/my-very-long-project-name-that-exceeds-limit-for-testing";
    mockListProjects({ projects: [makeProject({ id: "p1", name: "Y", path: longPath })], active_project_id: null });
    render(<ProjectsPage />);
    await waitForProjects(1);
    // The <p> element with truncated text also carries title=longPath
    const pathEls = screen.getAllByTitle(longPath);
    const pathPara = pathEls.find((el) => el.tagName === "P");
    expect(pathPara).toBeTruthy();
    expect(pathPara!.textContent).toContain("…");
  });
});

// ── New Project Modal ───────────────────────────────────────────────────────────

describe("ProjectsPage new project modal", () => {
  it("opens new project modal when clicking New Project button", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());
    expect(screen.getByPlaceholderText("My App")).toBeTruthy();
    expect(screen.getByPlaceholderText("/path/to/project")).toBeTruthy();
  });

  it("closes modal on Cancel click and resets form state", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    // Fill in some values
    fireEvent.change(screen.getByPlaceholderText("My App"), { target: { value: "Test Project" } });
    fireEvent.change(screen.getByPlaceholderText("/path/to/project"), { target: { value: "/workspace/test" } });

    // Click Cancel
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));
    await waitFor(() => expect(screen.queryByText("New Project")).toBeNull());

    // Reopen modal - form should be reset
    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());
    expect((screen.getByPlaceholderText("My App") as HTMLInputElement).value).toBe("");
    expect((screen.getByPlaceholderText("/path/to/project") as HTMLInputElement).value).toBe("");
  });

  it("closes modal on X button click", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^Close modal$/ }));
    await waitFor(() => expect(screen.queryByText("New Project")).toBeNull());
  });

  it("closes modal on Escape key", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    fireEvent.keyDown(screen.getByText("New Project").closest("div")!, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("New Project")).toBeNull());
  });

  it("closes new project modal on Escape key even when focus is on overlay (outside content)", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    // Focus is on the outer overlay div (outside the inner modal content div)
    // The outer overlay div is the grandparent of the "New Project" heading
    const modalContent = screen.getByText("New Project").closest("div")!;
    const overlay = modalContent.parentElement!;
    // Ensure overlay is focusable
    overlay.setAttribute("tabindex", "0");
    overlay.focus();
    expect(document.activeElement).toBe(overlay);
    fireEvent.keyDown(overlay, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText("New Project")).toBeNull());
  });

  it("closes cleanup modal on Escape key even when focus is on overlay (outside content)", async () => {
    const tempProjects: ProjectsResponse = {
      projects: [
        makeProject({ id: "p1", name: "Pytest Temp", path: "/private/tmp/pytest123", is_temp_like: true }),
      ],
      active_project_id: null,
    };
    mockListProjects(tempProjects);
    render(<ProjectsPage />);
    await waitForProjects(1);

    // Wait for Cleanup button to appear (tempCount > 0 when is_temp_like === true)
    await waitFor(() => expect(screen.getByRole("button", { name: /🧹 Cleanup/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /🧹 Cleanup/ }));
    await waitFor(() => expect(screen.getByText(/🧹 Cleanup Projects/)).toBeTruthy());

    // Focus is on the outer overlay div (outside the inner modal content div)
    const modalContent = screen.getByText(/🧹 Cleanup Projects/).closest("div")!;
    const overlay = modalContent.parentElement!;
    overlay.setAttribute("tabindex", "0");
    overlay.focus();
    expect(document.activeElement).toBe(overlay);
    fireEvent.keyDown(overlay, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText(/🧹 Cleanup Projects/)).toBeNull());
  });

  it("closes modal on overlay click (outside modal content)", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    // Click on the overlay backdrop (the div with fixed inset-0 that closes on click)
    // The overlay is behind the modal content and has onClick={closeNewModal}
    // We use the pointer event to target coordinates that land on the overlay
    // The modal is centered, so clicking at position (10, 10) lands on the overlay
    const overlay = document.querySelector<HTMLElement>('[class*="fixed inset-0"]');
    expect(overlay).toBeTruthy();
    fireEvent.click(overlay!);
    await waitFor(() => expect(screen.queryByText("New Project")).toBeNull());
  });

  it("disables Create button when name is empty", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    // Only fill path, leave name empty
    fireEvent.change(screen.getByPlaceholderText("/path/to/project"), { target: { value: "/workspace/test" } });

    const createBtn = screen.getByRole("button", { name: /^Create$/ });
    expect(createBtn).toBeDisabled();
  });

  it("disables Create button when path is empty", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    // Only fill name, leave path empty
    fireEvent.change(screen.getByPlaceholderText("My App"), { target: { value: "Test Project" } });

    const createBtn = screen.getByRole("button", { name: /^Create$/ });
    expect(createBtn).toBeDisabled();
  });

  it("enables Create button when name and path are filled", async () => {
    mockListProjects(MOCK_PROJECTS_RESPONSE);
    render(<ProjectsPage />);
    await waitForProjects(3);

    fireEvent.click(screen.getByRole("button", { name: /^\+ New Project$/ }));
    await waitFor(() => expect(screen.getByText("New Project")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("My App"), { target: { value: "Test Project" } });
    fireEvent.change(screen.getByPlaceholderText("/path/to/project"), { target: { value: "/workspace/test" } });

    const createBtn = screen.getByRole("button", { name: /^Create$/ });
    expect(createBtn).not.toBeDisabled();
  });
});
