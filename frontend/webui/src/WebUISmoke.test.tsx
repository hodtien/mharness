import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { useSession } from "./store/session";

type MockWsInstance = {
  url: string;
  readyState: number;
  sent: string[];
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send: (data: string) => void;
  close: () => void;
  addEventListener: () => void;
  removeEventListener: () => void;
  dispatchEvent: () => boolean;
};

const wsInstances: MockWsInstance[] = [];

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

function mockMatchMedia(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function mockFetch() {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";

    if (url === "/api/sessions" && method === "POST") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({ session_id: "smoke-session-1" }),
      });
    }

    if (url === "/api/cron/jobs") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({ jobs: [] }),
      });
    }

    if (url === "/api/history?limit=5") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({ sessions: [] }),
      });
    }

    if (url === "/api/modes" && method === "PATCH") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({
          permission_mode: "plan",
          fast_mode: false,
          vim_enabled: false,
          effort: "medium",
          passes: 1,
          output_style: "default",
          theme: "default",
        }),
      });
    }

    return Promise.resolve({
      ok: false,
      status: 404,
      statusText: "Not Found",
      headers: { get: () => null },
      text: async () => `unexpected ${method} ${url}`,
      json: async () => ({}),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockWebSocketOpen() {
  wsInstances.length = 0;

  // Make a constructor that doubles as the WebSocket class (with OPEN = 1).
  const Ctor = vi.fn().mockImplementation((url: string) => {
    const ws: MockWsInstance = {
      url,
      readyState: 0, // CONNECTING
      sent: [],
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null,
      send(data: string) {
        ws.sent.push(data);
      },
      close() {
        ws.readyState = 3;
        ws.onclose?.(new CloseEvent("close", { code: 1000 }));
      },
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    };
    wsInstances.push(ws);
    setTimeout(() => {
      ws.readyState = 1; // OPEN
      ws.onopen?.(new Event("open"));
      ws.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "ready",
            state: {
              model: "smoke-model",
              cwd: "/tmp/smoke",
              permission_mode: "default",
            },
            tasks: [],
          }),
        }),
      );
    }, 0);
    return ws;
  }) as unknown as typeof WebSocket;

  // Match the static readyState constants the real client checks.
  (Ctor as unknown as { CONNECTING: number; OPEN: number; CLOSING: number; CLOSED: number }).CONNECTING = 0;
  (Ctor as unknown as { CONNECTING: number; OPEN: number; CLOSING: number; CLOSED: number }).OPEN = 1;
  (Ctor as unknown as { CONNECTING: number; OPEN: number; CLOSING: number; CLOSED: number }).CLOSING = 2;
  (Ctor as unknown as { CONNECTING: number; OPEN: number; CLOSING: number; CLOSED: number }).CLOSED = 3;

  vi.stubGlobal("WebSocket", Ctor);
}

function resetSessionStore() {
  useSession.setState({
    appState: null,
    tasks: [],
    transcript: [],
    todoMarkdown: null,
    compact: null,
    planMode: null,
    swarm: null,
    connectionStatus: "closed",
    busy: false,
    errorBanner: null,
    pendingPermission: null,
    pendingQuestion: null,
    pendingSelect: null,
    resumedFrom: null,
  });
}

function renderApp() {
  window.history.pushState({}, "", "/chat?token=smoke-token");
  return render(
    <BrowserRouter>
      <App />
    </BrowserRouter>,
  );
}

async function waitForWebSocketOpen() {
  await waitFor(() => {
    expect(wsInstances.length).toBe(1);
    expect(useSession.getState().connectionStatus).toBe("open");
  });
}

describe("WebUI startup smoke", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockLocalStorage();
    mockFetch();
    mockWebSocketOpen();
    mockMatchMedia(true);
    resetSessionStore();
  });

  it("loads /chat, opens websocket, and shows no initial connection error banner", async () => {
    renderApp();
    await waitForWebSocketOpen();

    // The OpenHarness shell brand label should be on screen.
    expect(screen.getByText("OpenHarness")).toBeTruthy();

    // No error banner anywhere in the header (this would catch the regression
    // where ws closed with detail caused a noisy banner during normal startup).
    expect(useSession.getState().errorBanner).toBeNull();
  });

  it("shows the current header controls and opens the permission-mode dropdown", async () => {
    renderApp();
    await waitForWebSocketOpen();

    expect(screen.getAllByRole("link", { name: /history/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /password/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /logout/i })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /DEFAULT/ }));
    const menu = screen.getByRole("menu", { name: /permission mode/i });
    const items = within(menu).getAllByRole("menuitem");
    const labels = items.map((item) => item.textContent ?? "").join(" ");
    expect(labels).toMatch(/DEFAULT/);
    expect(labels).toMatch(/PLAN/);
    expect(labels).toMatch(/AUTO/);
  });

  it("toggles the OpenHarness desktop sidebar from the shell menu (☰) button", async () => {
    mockMatchMedia(true);
    renderApp();
    await waitForWebSocketOpen();

    const sidebar = screen.getByTestId("sidebar-desktop");
    expect(sidebar.className).toContain("sm:block");

    fireEvent.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    expect(sidebar.className).toContain("hidden");
    expect(sidebar.className).not.toContain("sm:block");

    fireEvent.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    expect(sidebar.className).toContain("sm:block");
  });

  it("opens and closes the mobile sidebar drawer from the shell menu (☰) button", async () => {
    mockMatchMedia(false);
    renderApp();
    await waitForWebSocketOpen();

    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    expect(screen.getByTestId("sidebar-mobile")).toBeTruthy();

    fireEvent.click(screen.getByTestId("sidebar-mobile-backdrop"));
    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();
  });
});
