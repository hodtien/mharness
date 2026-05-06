import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ModesSettingsPage from "./ModesSettingsPage";

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

function mockGetModes(data: object) {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    if (url === "/api/modes" && (!init?.method || init.method === "GET")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
    }
    if (url === "/api/modes" && init?.method === "PATCH") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
    }
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
}

describe("ModesSettingsPage", () => {
  it("renders loading state then content", async () => {
    mockLocalStorage();
    mockGetModes({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: 2, output_style: "default", theme: "default" });

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    expect(screen.getByText(/loading/i)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("Permission Mode")).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText("Default")).toBeTruthy();
    });
  });

  it("renders all setting sections", async () => {
    mockLocalStorage();
    mockGetModes({ permission_mode: "plan", fast_mode: true, vim_enabled: false, effort: "high", passes: 3, output_style: "concise", theme: "dark" });

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => {
      expect(screen.getByText("Permission Mode")).toBeTruthy();
    });
    expect(screen.getByText("Effort")).toBeTruthy();
    expect(screen.getByLabelText("Passes")).toBeTruthy();
    expect(screen.getByText("Fast Mode")).toBeTruthy();
    expect(screen.getByText("Vim keybindings")).toBeTruthy();
    expect(screen.getByText("Output Style")).toBeTruthy();
    expect(screen.getByText("Theme")).toBeTruthy();
  });

  it("calls PATCH when fast mode toggle changes", async () => {
    mockLocalStorage();
    const patchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: 1, output_style: "default", theme: "default" }) });
    });
    vi.stubGlobal("fetch", patchMock);

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Fast Mode")).toBeTruthy());

    const fastModeToggle = screen.getByRole("checkbox", { name: /fast mode/i });
    fireEvent.click(fastModeToggle);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("/api/modes", expect.objectContaining({ method: "PATCH" }));
    });
  });

  it("renders vim keybindings toggle with correct initial state", async () => {
    mockLocalStorage();
    mockGetModes({ permission_mode: "default", fast_mode: false, vim_enabled: true, effort: "medium", passes: 1, output_style: "default", theme: "default" });

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Vim keybindings")).toBeTruthy());

    const vimToggle = screen.getByRole("checkbox", { name: /vim keybindings/i });
    expect((vimToggle as HTMLInputElement).checked).toBe(true);
  });

  it("calls PATCH with vim_enabled when vim toggle changes", async () => {
    mockLocalStorage();
    const patchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: true, effort: "low", passes: 1, output_style: "default", theme: "default" }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: 1, output_style: "default", theme: "default" }) });
    });
    vi.stubGlobal("fetch", patchMock);

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Vim keybindings")).toBeTruthy());

    const vimToggle = screen.getByRole("checkbox", { name: /vim keybindings/i });
    fireEvent.click(vimToggle);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        "/api/modes",
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining("vim_enabled"),
        }),
      );
    });
  });

  it("increments passes value when + button is clicked", async () => {
    mockLocalStorage();
    let currentPasses = 2;
    const patchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const body = JSON.parse(init.body as string);
        if (body.passes) currentPasses = body.passes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: currentPasses, output_style: "default", theme: "default" }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: currentPasses, output_style: "default", theme: "default" }) });
    });
    vi.stubGlobal("fetch", patchMock);

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Passes")).toBeTruthy());

    const increaseButton = screen.getByRole("button", { name: /increase passes/i });
    fireEvent.click(increaseButton);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        "/api/modes",
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"passes":3'),
        }),
      );
    });
  });

  it("decrements passes value when - button is clicked", async () => {
    mockLocalStorage();
    let currentPasses = 3;
    const patchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        const body = JSON.parse(init.body as string);
        if (body.passes) currentPasses = body.passes;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: currentPasses, output_style: "default", theme: "default" }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: currentPasses, output_style: "default", theme: "default" }) });
    });
    vi.stubGlobal("fetch", patchMock);

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Passes")).toBeTruthy());

    const decreaseButton = screen.getByRole("button", { name: /decrease passes/i });
    fireEvent.click(decreaseButton);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        "/api/modes",
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"passes":2'),
        }),
      );
    });
  });

  it("disables decrease button when passes is at minimum (1)", async () => {
    mockLocalStorage();
    mockGetModes({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: 1, output_style: "default", theme: "default" });

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Passes")).toBeTruthy());

    const decreaseButton = screen.getByRole("button", { name: /decrease passes/i });
    expect((decreaseButton as HTMLButtonElement).disabled).toBe(true);
  });

  it("disables increase button when passes is at maximum (5)", async () => {
    mockLocalStorage();
    mockGetModes({ permission_mode: "default", fast_mode: false, vim_enabled: false, effort: "low", passes: 5, output_style: "default", theme: "default" });

    render(<BrowserRouter><ModesSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("Passes")).toBeTruthy());

    const increaseButton = screen.getByRole("button", { name: /increase passes/i });
    expect((increaseButton as HTMLButtonElement).disabled).toBe(true);
  });
});