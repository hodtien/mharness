import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import SettingsControlPage from "./SettingsControlPage";
import { useSession } from "../store/session";

function mockLocalStorage() {
  let store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  });
}

function stubFetchEmpty() {
  const fetchMock = vi.fn((url: string) => {
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
      json: () => Promise.resolve({ jobs: [] }),
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderControlPage() {
  return render(
    <MemoryRouter initialEntries={["/settings"]}>
      <SettingsControlPage />
    </MemoryRouter>,
  );
}

describe("SettingsControlPage (Control Center)", () => {
  beforeEach(() => {
    mockLocalStorage();
    stubFetchEmpty();
    useSession.setState({
      tasks: [],
      appState: null,
    });
  });

  it("renders the Control Center heading", () => {
    renderControlPage();
    expect(screen.getByText(/control center/i)).toBeTruthy();
  });

  it("renders operational status panel", () => {
    renderControlPage();
    expect(screen.getByLabelText(/operational status/i)).toBeTruthy();
    expect(screen.getByText(/Live Status/i)).toBeTruthy();
  });

  it("renders all settings section links", async () => {
    renderControlPage();
    await waitFor(() => {
      expect(screen.getByRole("link", { name: /modes/i })).toBeTruthy();
    });
    expect(screen.getByRole("link", { name: /providers/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /models/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /agents/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /schedule/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /security/i })).toBeTruthy();
  });

  it("shows scheduler-stopped callout when cron jobs are configured but disabled", async () => {
    // Simulate 2 jobs coming back from the API
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/cron/jobs")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: () =>
            Promise.resolve({
              jobs: [
                { name: "scan", enabled: false },
                { name: "tick", enabled: false },
              ],
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
        json: () => Promise.resolve({}),
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderControlPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    expect(screen.getByRole("alert").textContent).toContain("Scheduler stopped");
  });

  it("does not show scheduler-stopped callout when scheduler is running", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/cron/jobs")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: { get: () => null },
          json: () =>
            Promise.resolve({
              jobs: [
                { name: "scan", enabled: true },
              ],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: () => Promise.resolve({ projects: [], active_project_id: null }),
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderControlPage();

    // wait for cron fetch
    await waitFor(() =>
      expect((fetchMock as ReturnType<typeof vi.fn>).mock.calls.some((c: unknown[]) =>
        String(c[0]).includes("/cron/jobs"),
      )).toBe(true),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("displays appState model and provider in live status", () => {
    useSession.setState({
      appState: {
        model: "gpt-4o",
        provider: "openai",
        auth_status: "ok",
      },
    });
    renderControlPage();
    expect(screen.getByText("gpt-4o")).toBeTruthy();
    expect(screen.getByText("openai")).toBeTruthy();
  });
});
