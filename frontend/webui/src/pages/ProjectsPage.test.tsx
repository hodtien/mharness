import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ProjectsPage from "./ProjectsPage";
import type { ProjectsResponse, Project } from "../api/client";

const makeProject = (overrides: Partial<Project>): Project => ({
  id: "proj-001",
  name: "My App",
  path: "/Users/hodtien/projects/my-app",
  description: null,
  created_at: null,
  updated_at: null,
  is_active: false,
  ...overrides,
});

const MOCK_PROJECTS_RESPONSE: ProjectsResponse = {
  projects: [
    makeProject({ id: "proj-001", name: "My App", path: "/Users/hodtien/projects/my-app" }),
    makeProject({ id: "proj-002", name: "CLI Tool", path: "/Users/hodtien/projects/cli-tool", is_active: true }),
    makeProject({ id: "proj-003", name: "Web Dashboard", path: "/var/www/dashboard", description: "Production dashboard" }),
  ],
  active_project_id: "proj-002",
};

function mockFetch(response: any = MOCK_PROJECTS_RESPONSE) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/api/projects") {
        return Promise.resolve({ ok: true, json: async () => response });
      }
      if (url.match(/^\/api\/projects\/([^/]+)$/)) {
        return Promise.resolve({ ok: true, status: 204 });
      }
      if (url === `/api/projects/${response.active_project_id}/activate`) {
        return Promise.resolve({ ok: true, status: 204 });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    })
  );
}

function mockLocalStorage() {
  const store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLocalStorage();
});

// ── Helpers ─────────────────────────────────────────────────────────────────────

async function waitForProjects(count: number) {
  await waitFor(() => {
    const headings = screen.queryAllByRole("heading", { level: 2 });
    if (headings.length !== count) {
      throw new Error(`Expected ${count} headings, got ${headings.length}`);
    }
  });
}

function projectHeading(name: string) {
  return screen.getAllByRole("heading", { level: 2 }).find((h) => h.textContent === name);
}

// ── Rendering ────────────────────────────────────────────────────────────────

describe("ProjectsPage rendering", () => {
  it("renders project cards after load", async () => {
    mockFetch();
    render(<ProjectsPage />);
    await waitForProjects(3);
    expect(projectHeading("My App")).toBeTruthy();
    expect(projectHeading("CLI Tool")).toBeTruthy();
    expect(projectHeading("Web Dashboard")).toBeTruthy();
  });

  it("shows Active badge on the active project", async () => {
    mockFetch();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const cliCard = projectHeading("CLI Tool")!.closest(".group");
    expect(cliCard?.textContent).toContain("active");
  });

  it("shows New Project CTA in empty state", async () => {
    mockFetch({ projects: [], active_project_id: null });
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet.")).toBeTruthy());
    const ctaButtons = screen.getAllByRole("button", { name: /\+ New Project/ });
    expect(ctaButtons.length).toBeGreaterThanOrEqual(2);
  });
});

// ── Search ────────────────────────────────────────────────────────────────────

describe("ProjectsPage client-side search", () => {
  beforeEach(async () => {
    mockFetch();
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
    mockFetch({
      projects: [makeProject({ id: "p1", name: "X", path: "/tmp/abc" })],
      active_project_id: null,
    });
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getByTitle("/tmp/abc")).toBeTruthy();
  });

  it("has a copy path button next to each project path", async () => {
    mockFetch();
    render(<ProjectsPage />);
    await waitForProjects(3);
    const copyBtns = screen.getAllByRole("button", { name: /^Copy path / });
    expect(copyBtns.length).toBeGreaterThan(0);
  });

  it("copies full path to clipboard when copy button is clicked", async () => {
    mockFetch();
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: writeTextMock } });

    render(<ProjectsPage />);
    await waitForProjects(3);
    const copyBtn = screen.getByRole("button", { name: /Copy path \/Users\/hodtien\/projects\/my-app/ });
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("/Users/hodtien/projects/my-app");
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
    mockFetch({ projects: [makeProject({ id: "p1", name: "X", path: "/tmp/x" })], active_project_id: null });
    render(<ProjectsPage />);
    await waitForProjects(1);
    expect(screen.getByTitle("/tmp/x")).toBeTruthy();
  });

  it("truncates long paths", async () => {
    const longPath = "/Users/hodtien/projects/my-very-long-project-name-that-exceeds-limit-for-testing";
    mockFetch({ projects: [makeProject({ id: "p1", name: "Y", path: longPath })], active_project_id: null });
    render(<ProjectsPage />);
    await waitForProjects(1);
    const pathEl = screen.getByTitle(longPath);
    expect(pathEl.textContent).toContain("…");
  });
});
