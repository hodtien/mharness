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
    expect(screen.getByLabelText(/passes/i)).toBeTruthy();
    expect(screen.getByText("Fast Mode")).toBeTruthy();
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

    const toggle = screen.getByRole("checkbox");
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("/api/modes", expect.objectContaining({ method: "PATCH" }));
    });
  });
});