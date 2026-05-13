import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProjectSelector from "./ProjectSelector";
import type { Project, ProjectsResponse } from "../api/client";

const makeProject = (overrides: Partial<Project> = {}): Project => ({
  id: "proj-001",
  name: "My App",
  path: "/workspace/my-app",
  description: null,
  created_at: null,
  updated_at: null,
  is_active: false,
  ...overrides,
});

const MOCK_RESPONSE: ProjectsResponse = {
  projects: [
    makeProject({ id: "proj-001", name: "My App", path: "/workspace/my-app" }),
    makeProject({ id: "proj-002", name: "CLI Tool", path: "/workspace/cli-tool", is_active: true }),
    makeProject({ id: "proj-003", name: "Web Dashboard", path: "/var/www/dashboard" }),
  ],
  active_project_id: "proj-002",
};

function mockFetch(response: ProjectsResponse = MOCK_RESPONSE) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/projects") {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: () => Promise.resolve(response),
        });
      }
      if (url.startsWith("/api/projects/") && url.endsWith("/activate") && init?.method === "POST") {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: () => Promise.resolve({ ok: true }),
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    }),
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

describe("ProjectSelector", () => {
  it("shows the URL param project name in the trigger button", async () => {
    mockFetch();

    render(
      <MemoryRouter initialEntries={["/chat?project=proj-001"]}>
        <ProjectSelector />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("My App")).toBeTruthy());
    expect(screen.getByRole("button").textContent).toContain("My App");
  });

  it("falls back to server active project when the URL param is missing", async () => {
    mockFetch();

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ProjectSelector />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("CLI Tool")).toBeTruthy());
    expect(screen.getByRole("button").textContent).toContain("CLI Tool");
  });

  it("marks the URL param project with ● in the dropdown", async () => {
    mockFetch();

    render(
      <MemoryRouter initialEntries={["/chat?project=proj-001"]}>
        <ProjectSelector />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("My App")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });

    const options = screen.getAllByRole("option");
    const myAppOption = options.find((o) => o.textContent?.includes("My App"));
    expect(myAppOption?.textContent).toContain("●");
  });

  it("keeps the active project in the Manage Projects link", async () => {
    mockFetch();

    render(
      <MemoryRouter initialEntries={["/chat?project=proj-001"]}>
        <ProjectSelector />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("My App")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });

    const manageLink = await screen.findByRole("link", { name: /manage projects/i });
    expect(manageLink.getAttribute("href")).toContain("project=proj-001");
  });

  it("activates the selected project before updating the URL", async () => {
    mockFetch();

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ProjectSelector />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("CLI Tool")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /my app/i }));
    });

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/projects/proj-001/activate",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(screen.getByRole("button").textContent).toContain("My App");
  });
});
