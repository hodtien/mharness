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
    await waitFor(() =>
      expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>)).toBeDefined(),
    );
  });

  it("hides the desktop sidebar when collapsed=true", () => {
    renderSidebar({ open: false, collapsed: true });
    const desktop = screen.getByTestId("sidebar-desktop");
    expect(desktop.className).toContain("hidden");
    expect(desktop.className).not.toContain("sm:block");
  });

  it("renders primary navigation links", () => {
    renderSidebar({ open: false, collapsed: false });
    expect(screen.getByRole("link", { name: /chat/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /autopilot/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /projects/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /history/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /jobs/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /control center/i })).toBeTruthy();
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

  it("labels the sidebar status model as runtime", () => {
    useSession.setState({
      appState: {
        model: "cc/claude-sonnet-4-6",
        provider: "anthropic",
      },
    });

    renderSidebar({ open: false, collapsed: false });

    expect(screen.getByText("Runtime")).toBeTruthy();
    expect(screen.queryByText("Model")).toBeNull();
  });

  it("shows unified scheduler diagnostics labels", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/cron/diagnostics")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: () => Promise.resolve({
            scheduling_feature_enabled: true,
            cron_entries_installed: 2,
            cron_entries_enabled: 1,
            scheduler_process_alive: true,
            scheduler_pid: 12345,
            last_tick_at: null,
            last_scan_at: null,
            active_worker_count: 0,
            stale_worker_count: 0,
            last_error: null,
          }),
        });
      }
      if (url.includes("/projects")) {
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
        json: () => Promise.resolve({ jobs: [{ enabled: true }, { enabled: false }] }),
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSidebar({ open: false, collapsed: false });

    await waitFor(() => {
      expect(screen.getByText("Scheduler")).toBeTruthy();
    });
    expect(screen.getByText("running")).toBeTruthy();
    expect(screen.getByText("Cron entries")).toBeTruthy();
    expect(screen.getByText("1/2 enabled")).toBeTruthy();
    expect(screen.getByText("Feature")).toBeTruthy();
    expect(screen.getByText("enabled")).toBeTruthy();
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

    // Status section expanded by default — 'Access' label visible
    expect(screen.getByText("Access")).toBeTruthy();

    // Collapse
    fireEvent.click(
      screen.getByRole("button", { name: /collapse system status section/i }),
    );
    expect(screen.queryByText("Access")).toBeNull();
    expect(
      screen.getByRole("button", { name: /expand system status section/i }),
    ).toBeTruthy();
    expect(window.localStorage.getItem("oh:sidebar:status-collapsed")).toBe("true");

    // Expand
    fireEvent.click(
      screen.getByRole("button", { name: /expand system status section/i }),
    );
    expect(screen.getByText("Access")).toBeTruthy();
    expect(window.localStorage.getItem("oh:sidebar:status-collapsed")).toBe("false");
  });

  it("restores status collapsed state from localStorage", () => {
    window.localStorage.setItem("oh:sidebar:status-collapsed", "true");
    renderSidebar({ open: false, collapsed: false });

    expect(screen.queryByText("Access")).toBeNull();
    expect(
      screen.getByRole("button", { name: /expand system status section/i }),
    ).toBeTruthy();
  });

  it("highlights active route in primary navigation", async () => {
    useSession.setState({ tasks: [], appState: null });

    render(
      <MemoryRouter initialEntries={["/autopilot"]}>
        <Sidebar open={false} collapsed={false} onClose={() => {}} />
      </MemoryRouter>,
    );

    const autopilotLink = await screen.findByRole("link", { name: /autopilot/i });
    expect(autopilotLink.className).toContain("bg-[var(--accent-bg)]");
  });

  it("shows alert dot on Control entry when jobs have failed", () => {
    useSession.setState({
      tasks: [
        {
          id: "t1",
          status: "failed",
          type: "Task",
          description: "desc",
          metadata: {},
        },
      ],
    });
    renderSidebar({ open: false, collapsed: false });
    // The Control link must still be present
    expect(screen.getByRole("link", { name: /control center/i })).toBeTruthy();
    // Alert dot is a non-accessible span — verify it exists by checking aria-hidden sibling
    const link = screen.getByRole("link", { name: /control center/i });
    // alert dot is inside the link
    expect(link.innerHTML).toContain("rounded-full");
  });

  it("does not show alert dot when no failures", () => {
    useSession.setState({ tasks: [], appState: { mcp_failed: 0 } });
    renderSidebar({ open: false, collapsed: false });
    const link = screen.getByRole("link", { name: /control center/i });
    // No bg-[var(--error)] dot
    expect(link.innerHTML).not.toContain("rounded-full");
  });
});
