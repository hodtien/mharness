import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppLayout } from "./App";
import { useSession } from "./store/session";

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
  const fetchMock = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: () => Promise.resolve({ jobs: [] }),
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function setMatchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
  // window.matchMedia is read directly in the component
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

function renderLayout() {
  return render(
    <MemoryRouter>
      <AppLayout onInterrupt={() => {}} onResumeSession={async () => {}} />
    </MemoryRouter>,
  );
}

describe("AppLayout sidebar toggle", () => {
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
      connectionStatus: "closed",
      busy: false,
      errorBanner: null,
    });
  });

  it("toggles desktop sidebar collapse when (min-width: 640px) matches", () => {
    setMatchMedia(true);
    renderLayout();

    const desktop = screen.getByTestId("sidebar-desktop");
    // Initially expanded (visible on sm+).
    expect(desktop.className).toContain("sm:block");
    expect(desktop.className).not.toMatch(/^hidden h-full$/);

    fireEvent.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    // After click: collapsed — only 'hidden' applied.
    expect(desktop.className).toContain("hidden");
    expect(desktop.className).not.toContain("sm:block");

    // Mobile drawer must NOT have appeared on desktop toggle.
    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    // Toggle back to expanded.
    expect(desktop.className).toContain("sm:block");
  });

  it("opens the mobile drawer when (min-width: 640px) does not match", () => {
    setMatchMedia(false);
    renderLayout();

    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /toggle sidebar/i }));
    expect(screen.getByTestId("sidebar-mobile")).toBeTruthy();

    // Desktop sidebar must remain unaffected (still 'hidden sm:block').
    const desktop = screen.getByTestId("sidebar-desktop");
    expect(desktop.className).toContain("sm:block");

    // Click backdrop closes mobile drawer.
    fireEvent.click(screen.getByTestId("sidebar-mobile-backdrop"));
    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();
  });
});
