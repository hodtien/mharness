import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { PermissionModeChip } from "./Header";
import Header from "./Header";
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

function setSessionState(permission_mode: string) {
  useSession.setState({
    appState: {
      model: "test",
      cwd: "/tmp",
      permission_mode,
    },
  });
}

describe("PermissionModeChip", () => {
  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({ appState: null });
  });

  it("renders current permission mode label", () => {
    setSessionState("default");
    render(<PermissionModeChip />);
    expect(screen.getByRole("button", { name: /DEFAULT/ })).toBeTruthy();
  });

  it("opens menu and lists 3 options", () => {
    setSessionState("default");
    render(<PermissionModeChip />);
    fireEvent.click(screen.getByRole("button", { name: /DEFAULT/ }));
    const menu = screen.getByRole("menu");
    expect(menu).toBeTruthy();
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(3);
    const labels = items.map((el) => el.textContent || "");
    expect(labels.some((l) => /DEFAULT/.test(l))).toBe(true);
    expect(labels.some((l) => /PLAN/.test(l))).toBe(true);
    expect(labels.some((l) => /AUTO/.test(l))).toBe(true);
  });

  it("PATCHes /api/modes and applies optimistic update on selection", async () => {
    setSessionState("default");
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              permission_mode: "plan",
              fast_mode: false,
              vim_enabled: false,
              effort: "low",
              passes: 1,
              output_style: "default",
              theme: "default",
            }),
        });
      }
      return Promise.reject(new Error(`unexpected: ${init?.method}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<PermissionModeChip />);
    fireEvent.click(screen.getByRole("button", { name: /DEFAULT/ }));

    const planOption = screen
      .getAllByRole("menuitem")
      .find((el) => /PLAN/.test(el.textContent || ""));
    expect(planOption).toBeTruthy();
    fireEvent.click(planOption!);

    // Optimistic update: store should immediately reflect "plan"
    expect(useSession.getState().appState?.permission_mode).toBe("plan");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/modes",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ permission_mode: "plan" }),
        }),
      );
    });
  });

  it("reverts state when PATCH fails", async () => {
    setSessionState("default");
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: false, status: 500, statusText: "err", text: () => Promise.resolve("boom") }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PermissionModeChip />);
    fireEvent.click(screen.getByRole("button", { name: /DEFAULT/ }));
    const fullAuto = screen
      .getAllByRole("menuitem")
      .find((el) => /AUTO/.test(el.textContent || ""));
    fireEvent.click(fullAuto!);

    // Optimistic flip
    expect(useSession.getState().appState?.permission_mode).toBe("full_auto");

    await waitFor(() => {
      expect(useSession.getState().appState?.permission_mode).toBe("default");
    });
  });
});

describe("Header breadcrumb", () => {
  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({
      appState: null,
      connectionStatus: "open",
      transcript: [],
      tasks: [],
      busy: false,
      errorBanner: null,
      pendingPermission: null,
      pendingQuestion: null,
      pendingSelect: null,
      compact: null,
      todoMarkdown: null,
      planMode: null,
      swarm: null,
      resumedFrom: null,
    });
  });

  it("renders model badge, provider badge, and truncated path with tooltip", () => {
    useSession.setState({
      appState: {
        model: "claude-3-5-sonnet",
        provider: "anthropic",
        cwd: "/Users/hodtien/harness/my-harness",
        permission_mode: "default",
      },
    });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
          onResumeSession={() => Promise.resolve()}
        />
      </BrowserRouter>,
    );

    // Model badge should be visible
    expect(screen.getByText(/claude-3-5-sonnet/)).toBeTruthy();

    // Provider badge should be rendered (visible on md+ breakpoint)
    expect(screen.getByText(/anthropic/)).toBeTruthy();

    // Path should be rendered with truncation (visible on lg+ breakpoint)
    const pathSpan = screen.getByTitle("/Users/hodtien/harness/my-harness");
    expect(pathSpan).toBeTruthy();
    expect(pathSpan.textContent).toMatch(/\.\.\./); // should show "...my-harness"
  });

  it("handles missing appState gracefully", () => {
    useSession.setState({ appState: null });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
          onResumeSession={() => Promise.resolve()}
        />
      </BrowserRouter>,
    );

    // Should not crash, just show brand
    expect(screen.getByText("OpenHarness")).toBeTruthy();
  });
});
