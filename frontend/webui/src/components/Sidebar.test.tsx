import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Sidebar from "./Sidebar";
import { useSession } from "../store/session";

function mockLocalStorage() {
  let store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  });
}

function stubFetchEmpty() {
  const fetchMock = vi.fn((url: string) => {
    // Return valid projects response for listProjects calls
    if (typeof url === "string" && url.includes("/projects")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: () => Promise.resolve({ projects: [], active_project_id: null }),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: () => Promise.resolve({ jobs: [] }),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSidebar(props: {
  open?: boolean;
  collapsed?: boolean;
  onClose?: () => void;
}) {
  return render(
    <MemoryRouter>
      <Sidebar
        open={props.open ?? false}
        collapsed={props.collapsed ?? false}
        onClose={props.onClose ?? (() => {})}
      />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    mockLocalStorage();
    stubFetchEmpty();
    useSession.setState({
      tasks: [],
      appState: null,
      todoMarkdown: null,
      compact: null,
      planMode: null,
      swarm: null,
    });
  });

  it("renders the persistent desktop sidebar by default", async () => {
    renderSidebar({ open: false, collapsed: false });
    const desktop = screen.getByTestId("sidebar-desktop");
    expect(desktop).toBeTruthy();
    expect(desktop.className).toContain("sm:block");
    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();
    await waitFor(() => expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>)).toBeDefined());
  });

  it("hides the desktop sidebar when collapsed=true", () => {
    renderSidebar({ open: false, collapsed: true });
    const desktop = screen.getByTestId("sidebar-desktop");
    expect(desktop.className).toContain("hidden");
    expect(desktop.className).not.toContain("sm:block");
  });

  it("hides the settings list and stores collapsed state", () => {
    renderSidebar({ open: false, collapsed: false });

    fireEvent.click(screen.getByRole("button", { name: /collapse settings section/i }));

    expect(screen.queryByRole("link", { name: "Modes" })).toBeNull();
    expect(screen.getByRole("button", { name: /expand settings section/i })).toBeTruthy();
    expect(window.localStorage.getItem("oh:sidebar:settings-collapsed")).toBe("true");
  });

  it("restores the settings collapsed state from localStorage", () => {
    window.localStorage.setItem("oh:sidebar:settings-collapsed", "true");
    renderSidebar({ open: false, collapsed: false });

    expect(screen.queryByRole("link", { name: "Modes" })).toBeNull();
    expect(screen.getByRole("button", { name: /expand settings section/i })).toBeTruthy();
  });

  it("shows the mobile drawer only when open=true", () => {
    const { rerender } = renderSidebar({ open: false, collapsed: false });
    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();

    rerender(
      <MemoryRouter>
        <Sidebar open={true} collapsed={false} onClose={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("sidebar-mobile")).toBeTruthy();
  });

  it("calls onClose when the mobile backdrop is clicked", () => {
    const onClose = vi.fn();
    renderSidebar({ open: true, collapsed: false, onClose });
    fireEvent.click(screen.getByTestId("sidebar-mobile-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not affect mobile drawer visibility when collapsed=true", () => {
    renderSidebar({ open: true, collapsed: true });
    expect(screen.getByTestId("sidebar-mobile")).toBeTruthy();
    const desktop = screen.getByTestId("sidebar-desktop");
    expect(desktop.className).toContain("hidden");
    expect(desktop.className).not.toContain("sm:block");
  });

  it("collapses and expands the System Status section", () => {
    renderSidebar({ open: false, collapsed: false });

    // Expand status section is visible by default
    expect(screen.getByText("Access")).toBeTruthy();

    // Collapse
    fireEvent.click(screen.getByRole("button", { name: /collapse system status section/i }));
    expect(screen.queryByText("Access")).toBeNull();
    expect(screen.getByRole("button", { name: /expand system status section/i })).toBeTruthy();
    expect(window.localStorage.getItem("oh:sidebar:status-collapsed")).toBe("true");

    // Expand
    fireEvent.click(screen.getByRole("button", { name: /expand system status section/i }));
    expect(screen.getByText("Access")).toBeTruthy();
    expect(window.localStorage.getItem("oh:sidebar:status-collapsed")).toBe("false");
  });

  it("shows top 3 jobs with View all link when more than 3 jobs exist", () => {
    const manyTasks: Array<{ id: string; status: string; type: string; description: string; metadata: Record<string, string> }> = Array.from({ length: 7 }, (_, i) => ({
      id: `task-${i}`,
      status: "running",
      type: `Task ${i}`,
      description: `Description for task ${i}`,
      metadata: {},
    }));
    useSession.setState({ tasks: manyTasks });

    renderSidebar({ open: false, collapsed: false });

    // Should show only 3 jobs
    const jobBadges = screen.getAllByText("running");
    expect(jobBadges).toHaveLength(3);

    // Should show View all link
    expect(screen.getByRole("link", { name: /view all \(7\)/i })).toBeTruthy();
  });

  it("shows all jobs without View all link when 3 or fewer jobs exist", () => {
    const fewTasks: Array<{ id: string; status: string; type: string; description: string; metadata: Record<string, string> }> = [
      { id: "task-1", status: "done", type: "Task 1", description: "", metadata: {} },
      { id: "task-2", status: "running", type: "Task 2", description: "", metadata: {} },
      { id: "task-3", status: "failed", type: "Task 3", description: "", metadata: {} },
    ];
    useSession.setState({ tasks: fewTasks });

    renderSidebar({ open: false, collapsed: false });

    const jobBadges = screen.getAllByText(/done|running|failed/);
    expect(jobBadges).toHaveLength(3);
    expect(screen.queryByRole("link", { name: /view all/i })).toBeNull();
  });

  it("highlights active route in primary navigation", async () => {
    useSession.setState({ tasks: [], appState: null });

    render(
      <MemoryRouter initialEntries={["/autopilot"]}>
        <Sidebar open={false} collapsed={false} onClose={() => {}} />
      </MemoryRouter>,
    );

    // Navigation links should be visible immediately
    const autopilotLink = await screen.findByRole("link", { name: /autopilot/i });
    expect(autopilotLink.className).toContain("bg-[var(--accent-bg)]");
  });

  it("restores status collapsed state from localStorage", () => {
    window.localStorage.setItem("oh:sidebar:status-collapsed", "true");
    renderSidebar({ open: false, collapsed: false });

    expect(screen.queryByText("Access")).toBeNull();
    expect(screen.getByRole("button", { name: /expand system status section/i })).toBeTruthy();
  });
});
