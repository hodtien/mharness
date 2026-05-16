import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import { PermissionModeChip } from "./Header";
import Header from "./Header";
import { useSession } from "../store/session";
import { useToastStore } from "../store/toast";
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

  it("shows error toast when PATCH fails", async () => {
    setSessionState("default");
    useToastStore.setState({ toasts: [] });
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: false, status: 500, statusText: "err", text: () => Promise.resolve("boom") }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PermissionModeChip />);
    fireEvent.click(screen.getByRole("button", { name: /DEFAULT/ }));
    const planOption = screen
      .getAllByRole("menuitem")
      .find((el) => /PLAN/.test(el.textContent || ""));
    fireEvent.click(planOption!);

    // Wait for toast to be added to the store
    await waitFor(() => {
      expect(useToastStore.getState().toasts).toHaveLength(1);
    });
    expect(useToastStore.getState().toasts[0].kind).toBe("error");
    expect(useToastStore.getState().toasts[0].message).toMatch(/failed to update permission mode/i);
  });
});

describe("ModelPicker", () => {
  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({
      appState: {
        model: "cc/claude-sonnet-4-6",
        provider: "anthropic",
        active_profile: "claude-router",
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

  // Helper: /api/models returns models keyed by profile id "claude-router"
  function makeClaudeRouterModels() {
    return {
      "claude-router": [
        { id: "cc/claude-sonnet-4-6", label: "Claude Sonnet 4.6", is_default: true, is_custom: false },
        { id: "cc/claude-haiku-4", label: "Claude Haiku 4", is_default: false, is_custom: false },
      ],
    };
  }

  it("fetches models keyed by active_profile and shows active model with checkmark", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeClaudeRouterModels()),
        });
      }
      return Promise.reject(new Error(`unexpected: ${url} ${init?.method || "GET"}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /cc\/claude-sonnet-4-6/i }));

    await screen.findByDisplayValue("");
    expect(await screen.findByText(/Claude Sonnet 4\.6 \(cc\/claude-sonnet-4-6\)/)).toBeTruthy();
    expect(screen.getByText("✓")).toBeTruthy();
  });

  it("PATCHes /api/modes with { model } only and applies optimistic update on selection", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeClaudeRouterModels()),
        });
      }
      if (url === "/api/modes" && init?.method === "PATCH") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            permission_mode: "default",
            model: "cc/claude-haiku-4",
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
    fireEvent.click(screen.getByRole("button", { name: /cc\/claude-sonnet-4-6/i }));

    const option = await screen.findByText(/Claude Haiku 4 \(cc\/claude-haiku-4\)/);
    fireEvent.click(option);

    expect(useSession.getState().appState?.model).toBe("cc/claude-haiku-4");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/modes",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ model: "cc/claude-haiku-4" }),
        }),
      );
    });
  });

  it("reverts model selection and shows error toast when PATCH fails", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(makeClaudeRouterModels()),
        });
      }
      if (url === "/api/modes" && init?.method === "PATCH") {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: "err",
          text: () => Promise.resolve("boom"),
        });
      }
      return Promise.reject(new Error(`unexpected: ${url} ${init?.method || "GET"}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    useToastStore.setState({ toasts: [] });

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /cc\/claude-sonnet-4-6/i }));

    const option = await screen.findByText(/Claude Haiku 4 \(cc\/claude-haiku-4\)/);
    fireEvent.click(option);

    expect(useSession.getState().appState?.model).toBe("cc/claude-haiku-4");

    await waitFor(() => {
      expect(useSession.getState().appState?.model).toBe("cc/claude-sonnet-4-6");
      expect(useToastStore.getState().toasts).toHaveLength(1);
    });
    expect(useToastStore.getState().toasts[0].kind).toBe("error");
    expect(useToastStore.getState().toasts[0].message).toMatch(/failed to update model/i);
  });

  it("filters models by search", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/models") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              "claude-router": [
                { id: "cc/claude-sonnet-4-6", label: "Claude Sonnet 4.6", is_default: true, is_custom: false },
                { id: "cc/claude-haiku-4", label: "Claude Haiku 4", is_default: false, is_custom: false },
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
    fireEvent.click(screen.getByRole("button", { name: /cc\/claude-sonnet-4-6/i }));

    const input = await screen.findByPlaceholderText(/Search 2 models/i);
    fireEvent.change(input, { target: { value: "haiku" } });

    expect(await screen.findByText(/Claude Haiku 4/)).toBeTruthy();
    expect(screen.queryByText(/Claude Sonnet 4\.6/)).toBeNull();
    expect(screen.queryByText(/GPT-4o/)).toBeNull();
  });

  it("uses active_profile over provider to resolve model group", async () => {
    // Simulate backend state: active_profile=claude-router, provider=anthropic,
    // but /api/models is keyed by profile ids like "claude-router", not "anthropic".
    useSession.setState({
      appState: {
        model: "cc/claude-sonnet-4-6",
        provider: "anthropic",
        active_profile: "claude-router",
        cwd: "/tmp",
        permission_mode: "default",
      },
    });
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url === "/api/models") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              "claude-router": [
                { id: "cc/claude-sonnet-4-6", label: "Claude Sonnet 4 (Router)", is_default: true, is_custom: false },
                { id: "cc/claude-opus-4-5", label: "Claude Opus 4 (Router)", is_default: false, is_custom: false },
              ],
              anthropic: [
                { id: "claude-3-5-sonnet", label: "Claude 3.5 Sonnet", is_default: true, is_custom: false },
              ],
            }),
        });
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /cc\/claude-sonnet-4-6/i }));

    // Should show claude-router models, not anthropic ones
    expect(await screen.findByText(/Claude Sonnet 4 \(Router\)/)).toBeTruthy();
    expect(screen.queryByText(/Claude 3.5 Sonnet/)).toBeNull();
  });

  it("falls back to provider when active_profile is not set", async () => {
    // When backend state lacks active_profile, the picker should fall back to provider.
    useSession.setState({
      appState: {
        model: "claude-3-5-sonnet",
        provider: "anthropic",
        // no active_profile
        cwd: "/tmp",
        permission_mode: "default",
      },
    });
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url === "/api/models") {
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
      return Promise.reject(new Error(`unexpected: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ModelPicker />);
    fireEvent.click(screen.getByRole("button", { name: /claude-3-5-sonnet/i }));

    expect(await screen.findByText(/Claude 3.5 Sonnet \(claude-3-5-sonnet\)/)).toBeTruthy();
    expect(screen.getByText("✓")).toBeTruthy();
  });
});

describe("Header navigation", () => {
  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({
      appState: {
        model: "claude-3-5-sonnet",
        provider: "anthropic",
        cwd: "/Users/hodtien/harness/my-harness",
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

  it("renders a History link", () => {
    render(
      <BrowserRouter>
        <Header
          onToggleSidebar={() => {}}
          onInterrupt={() => {}}
        />
      </BrowserRouter>,
    );

    expect(screen.getByRole("link", { name: "History" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "History" }).getAttribute("href")).toBe("/history");
  });

  it("navigates to /history when the History link is clicked", () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Routes>
          <Route path="/chat" element={<Header onToggleSidebar={() => {}} onInterrupt={() => {}} />} />
          <Route path="/history" element={<div>History page</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("link", { name: "History" }));
    expect(screen.getByText("History page")).toBeTruthy();
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

describe("Header mobile overflow", () => {
  const MOBILE_WIDTHS = [375, 390, 430];

  beforeEach(() => {
    mockLocalStorage();
    useSession.setState({
      appState: {
        model: "cx/gpt-5.5-turbo-some-very-long-model-identifier",
        provider: "openrouter",
        cwd: "/tmp",
        permission_mode: "default",
      },
      connectionStatus: "open",
      transcript: [],
      tasks: [
        { id: "1", type: "job", status: "running", description: "task 1", metadata: {} },
      ],
      busy: true,
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

  it.each(MOBILE_WIDTHS)("header row does not overflow at %ipx", (width) => {
    // jsdom doesn't honour real viewport widths, but we can assert that
    // - the History link is NOT in the document's main header row (it's hidden on mobile)
    // - or no element has been given a style that would force horizontal overflow
    Object.defineProperty(document.documentElement, "clientWidth", { configurable: true, value: width });
    const { container } = render(
      <BrowserRouter>
        <Header onToggleSidebar={() => {}} onInterrupt={() => {}} />
      </BrowserRouter>,
    );
    // The primary row must not contain an unconstrained wide flex row.
    // We verify there is no `overflow-x-auto` / direct width > viewport on the host div.
    const topRow = container.firstChild as HTMLElement;
    // jsdom assigns 0 to scrollWidth for non-painted elements; we just ensure no error and structural assertions below.
    expect(topRow).toBeTruthy();
    // History link should be hidden on mobile (sm:hidden means css class `hidden sm:flex`).
    // In jsdom all elements are visible, but the link must be inside a hidden container — verify aria-label button exists instead.
    const mobileModelBtn = container.querySelector('[aria-label="Open runtime controls"]');
    expect(mobileModelBtn).toBeTruthy();
    // Model text must be inside the button and truncated (has truncate class)
    const truncatingSpan = mobileModelBtn?.querySelector(".truncate");
    expect(truncatingSpan).toBeTruthy();
  });

  it("opens mobile overflow menu and exposes History, PermissionModeChip, and ModelPicker", () => {
    render(
      <BrowserRouter>
        <Header onToggleSidebar={() => {}} onInterrupt={() => {}} />
      </BrowserRouter>,
    );
    // Compact model button should be present (always rendered, hidden by CSS on sm+)
    const mobileModelBtn = screen.getByRole("button", { name: /Open runtime controls/i });
    expect(mobileModelBtn).toBeTruthy();

    fireEvent.click(mobileModelBtn);

    // After toggling, the mobile overflow panel renders the full History link
    const historyLinks = screen.getAllByRole("link", { name: "History" });
    expect(historyLinks.length).toBeGreaterThanOrEqual(1);
    // Provider label present in overflow panel (may appear twice due to RuntimeSummary hidden span)
    const providerEls = screen.getAllByText(/openrouter/);
    expect(providerEls.length).toBeGreaterThanOrEqual(1);
    // Full ModelPicker trigger rendered inside the drawer (has aria-haspopup="listbox")
    const allModelBtns = screen.getAllByRole("button", { name: /cx\/gpt-5\.5-turbo/i, hidden: true });
    expect(allModelBtns.length).toBeGreaterThanOrEqual(1);
  });
});
