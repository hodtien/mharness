import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import { PermissionModeChip } from "./Header";
import Header from "./Header";
import { useSession } from "../store/session";
import { ModelPicker } from "./Header";

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

describe("ModelPicker", () => {
  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({
      appState: {
        model: "claude-3-5-sonnet",
        provider: "anthropic",
        cwd: "/tmp",
        permission_mode: "default",
      },
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

  it("fetches models and shows active model with checkmark", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              anthropic: [
                { id: "claude-3-5-sonnet", label: "Claude 3.5 Sonnet", is_default: true, is_custom: false },
                { id: "claude-3-5-haiku", label: "Claude 3.5 Haiku", is_default: false, is_custom: false },
              ],
            }),
        });
      }
      return Promise.reject(new Error(`unexpected: ${url} ${init?.method || "GET"}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /claude-3-5-sonnet/i }));

    await screen.findByDisplayValue("");
    expect(await screen.findByText(/Claude 3.5 Sonnet \(claude-3-5-sonnet\)/)).toBeTruthy();
    expect(screen.getByText("✓")).toBeTruthy();
  });

  it("PATCHes /api/modes with model and applies optimistic update on selection", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              anthropic: [
                { id: "claude-3-5-sonnet", label: "Claude 3.5 Sonnet", is_default: true, is_custom: false },
                { id: "claude-3-5-haiku", label: "Claude 3.5 Haiku", is_default: false, is_custom: false },
              ],
            }),
        });
      }
      if (url === "/api/modes" && init?.method === "PATCH") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            permission_mode: "default",
            model: "claude-3-5-haiku",
            fast_mode: false,
            vim_enabled: false,
            effort: "medium",
            passes: 1,
            output_style: "default",
            theme: "default",
          }),
        });
      }
      return Promise.reject(new Error(`unexpected: ${url} ${init?.method || "GET"}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /claude-3-5-sonnet/i }));

    const option = await screen.findByText(/Claude 3.5 Haiku \(claude-3-5-haiku\)/);
    fireEvent.click(option);

    expect(useSession.getState().appState?.model).toBe("claude-3-5-haiku");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/modes",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ model: "claude-3-5-haiku" }),
        }),
      );
    });
  });

  it("filters models by search", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/models") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              anthropic: [
                { id: "claude-3-5-sonnet", label: "Claude 3.5 Sonnet", is_default: true, is_custom: false },
                { id: "claude-3-5-haiku", label: "Claude 3.5 Haiku", is_default: false, is_custom: false },
              ],
              openai: [
                { id: "gpt-4o", label: "GPT-4o", is_default: true, is_custom: false },
              ],
            }),
        });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /claude-3-5-sonnet/i }));

    const input = await screen.findByPlaceholderText(/Search 3 models/i);
    fireEvent.change(input, { target: { value: "gpt" } });

    expect(await screen.findByText(/GPT-4o/)).toBeTruthy();
    expect(screen.queryByText(/Claude 3.5 Haiku/)).toBeNull();
  });
});

describe("Header runtime summary badges", () => {
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

  it("renders model picker button and provider badge", () => {
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
        />
      </BrowserRouter>,
    );

    // Model badge should be visible
    expect(screen.getByText(/claude-3-5-sonnet/)).toBeTruthy();
    // Provider badge should be rendered (visible on md+ breakpoint)
    expect(screen.getByText(/anthropic/)).toBeTruthy();
  });

  it("shows running jobs badge when tasks are running", () => {
    useSession.setState({
      appState: { model: "test", permission_mode: "default" },
      tasks: [
        { id: "1", type: "job", status: "running", description: "task 1", metadata: {} },
        { id: "2", type: "job", status: "queued", description: "task 2", metadata: {} },
        { id: "3", type: "job", status: "done", description: "task 3", metadata: {} },
      ],
    });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
        />
      </BrowserRouter>,
    );

    // Should show "2 jobs" badge (running + queued)
    expect(screen.getByText(/2 jobs/)).toBeTruthy();
  });

  it("shows busy indicator with tool name when busy", () => {
    useSession.setState({
      appState: { model: "test", permission_mode: "default" },
      busy: true,
      transcript: [
        { id: "1", role: "user", text: "hello" },
        { id: "2", role: "assistant", text: "working", tool_name: "bash" },
      ],
    });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
        />
      </BrowserRouter>,
    );

    // Should show busy indicator with tool name
    expect(screen.getByText(/Running bash/)).toBeTruthy();
  });

  it("shows Stop button with running count when busy with jobs", () => {
    const onInterrupt = vi.fn();
    useSession.setState({
      appState: { model: "test", permission_mode: "default" },
      busy: true,
      tasks: [
        { id: "1", type: "job", status: "running", description: "task 1", metadata: {} },
      ],
    });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={onInterrupt}
        />
      </BrowserRouter>,
    );

    // Stop button has aria-label including running count
    const stopBtn = screen.getByRole("button", { name: /Stop 1 running job\(s\)/ });
    expect(stopBtn).toBeTruthy();
    fireEvent.click(stopBtn);
    expect(onInterrupt).toHaveBeenCalled();
  });

  it("shows simple Stop button when busy without jobs", () => {
    const onInterrupt = vi.fn();
    useSession.setState({
      appState: { model: "test", permission_mode: "default" },
      busy: true,
      tasks: [],
    });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={onInterrupt}
        />
      </BrowserRouter>,
    );

    // Stop button has aria-label for simple stop
    const stopBtn = screen.getByRole("button", { name: /Stop current task/ });
    expect(stopBtn).toBeTruthy();
    fireEvent.click(stopBtn);
    expect(onInterrupt).toHaveBeenCalled();
  });

  it("shows connection status dot (green for open)", () => {
    useSession.setState({
      connectionStatus: "open",
      appState: { permission_mode: "default" },
    });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
        />
      </BrowserRouter>,
    );

    // Should show green dot for open connection
    const dot = document.querySelector(".bg-emerald-400");
    expect(dot).toBeTruthy();
  });

  it("handles missing appState gracefully", () => {
    useSession.setState({ appState: null });

    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
        />
      </BrowserRouter>,
    );

    // Should not crash, just show brand
    expect(screen.getByText("OpenHarness")).toBeTruthy();
  });
});
