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
    // Desktop wrapper is hidden on mobile via tailwind, but is in the DOM
    // and does NOT have the 'hidden' class once large screen kicks in.
    expect(desktop).toBeTruthy();
    expect(desktop.className).toContain("sm:block");
    expect(desktop.className).not.toContain("hidden sm:block hidden");
    // Mobile drawer should not be in the DOM when open=false.
    expect(screen.queryByTestId("sidebar-mobile")).toBeNull();
    await waitFor(() => expect((globalThis.fetch as unknown as ReturnType<typeof vi.fn>)).toBeDefined());
  });

  it("hides the desktop sidebar when collapsed=true", () => {
    renderSidebar({ open: false, collapsed: true });
    const desktop = screen.getByTestId("sidebar-desktop");
    // When collapsed, only the 'hidden' class is applied — no sm:block override.
    expect(desktop.className).toContain("hidden");
    expect(desktop.className).not.toContain("sm:block");
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
    // Collapsed only governs desktop; mobile drawer is still openable.
    renderSidebar({ open: true, collapsed: true });
    expect(screen.getByTestId("sidebar-mobile")).toBeTruthy();
    const desktop = screen.getByTestId("sidebar-desktop");
    expect(desktop.className).toContain("hidden");
    expect(desktop.className).not.toContain("sm:block");
  });
});
