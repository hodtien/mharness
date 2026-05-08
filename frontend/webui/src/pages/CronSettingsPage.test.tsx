import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import CronSettingsPage from "./CronSettingsPage";

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

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 204 ? "No Content" : "OK",
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    headers: { get: () => null },
  };
}

const defaultCronConfig = {
  enabled: true,
  scan_cron: "*/15 * * * *",
  tick_cron: "0 * * * *",
  timezone: "UTC",
  install_mode: "auto",
  scan_cron_description: "Every 15 minutes",
  tick_cron_description: "Every hour",
  next_scan_runs: ["2025-01-01T09:00:00", "2025-01-01T09:15:00", "2025-01-01T09:30:00"],
  next_tick_runs: ["2025-01-01T09:00:00", "2025-01-01T10:00:00", "2025-01-01T11:00:00"],
};

function mockGetCron(data = defaultCronConfig) {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    if (url === "/api/cron/config" && (!init?.method || init.method === "GET")) {
      return Promise.resolve(jsonResponse(data));
    }
    if (url === "/api/cron/config" && init?.method === "PATCH") {
      const body = JSON.parse(String(init?.body ?? "{}"));
      const merged = { ...defaultCronConfig, ...body };
      return Promise.resolve(jsonResponse(merged));
    }
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
}

async function renderPage() {
  render(
    <BrowserRouter>
      <CronSettingsPage />
    </BrowserRouter>,
  );
}

describe("CronSettingsPage", () => {
  it("renders loading state then page title", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    // Loading state shows skeleton with aria-busy
    expect(screen.getByLabelText("Loading content")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText("Autopilot Schedule")).toBeTruthy();
    });
  });

  it("renders enabled toggle and cron inputs", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Enable Autopilot Scheduling")).toBeTruthy();
    });
    expect(screen.getByLabelText(/enable autopilot scheduling/i)).toBeTruthy();
    expect(screen.getByLabelText(/scan cron/i)).toBeTruthy();
    expect(screen.getByLabelText(/tick cron/i)).toBeTruthy();
  });

  it("renders next runs preview when enabled", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Next scan runs")).toBeTruthy();
      expect(screen.getByText("Next tick runs")).toBeTruthy();
    });
  });

  it("renders preset buttons", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Aggressive (5m / 15m)")).toBeTruthy();
      expect(screen.getByText("Default (15m / 1h)")).toBeTruthy();
      expect(screen.getByText("Conservative (30m / 2h)")).toBeTruthy();
    });
  });

  it("renders cron expression examples", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Cron Expression Examples")).toBeTruthy();
    });
    expect(screen.getByText("Every 5 minutes")).toBeTruthy();
    expect(screen.getByText("Every hour")).toBeTruthy();
  });

  it("calls PATCH when Apply is clicked with changes", async () => {
    mockLocalStorage();
    const patchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/cron/config" && init?.method === "PATCH") {
        return Promise.resolve(jsonResponse({ ...defaultCronConfig, scan_cron: "*/30 * * * *" }));
      }
      return Promise.resolve(jsonResponse(defaultCronConfig));
    });
    vi.stubGlobal("fetch", patchMock);

    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText(/scan cron/i)).toBeTruthy();
    });

    const scanInput = screen.getByLabelText(/scan cron/i) as HTMLInputElement;
    fireEvent.change(scanInput, { target: { value: "*/30 * * * *" } });

    const applyButton = screen.getByRole("button", { name: /apply/i });
    expect((applyButton as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        "/api/cron/config",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
  });

  it("disables Apply button when there are no changes", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText(/scan cron/i)).toBeTruthy();
    });

    const applyButton = screen.getByRole("button", { name: /apply/i });
    expect((applyButton as HTMLButtonElement).disabled).toBe(true);
  });

  it("applies preset when preset button is clicked", async () => {
    mockLocalStorage();
    const patchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/cron/config" && init?.method === "PATCH") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return Promise.resolve(jsonResponse({ ...defaultCronConfig, ...body }));
      }
      return Promise.resolve(jsonResponse(defaultCronConfig));
    });
    vi.stubGlobal("fetch", patchMock);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Aggressive (5m / 15m)")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Aggressive (5m / 15m)"));

    const applyButton = screen.getByRole("button", { name: /apply/i });
    expect((applyButton as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows too-frequent warning when scan interval is under 5 minutes", async () => {
    mockLocalStorage();
    mockGetCron({ ...defaultCronConfig, scan_cron: "*/1 * * * *" });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Schedule may be too frequent")).toBeTruthy();
    });
  });

  it("shows too-frequent warning when tick interval is under 15 minutes", async () => {
    mockLocalStorage();
    mockGetCron({ ...defaultCronConfig, tick_cron: "*/5 * * * *" });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Schedule may be too frequent")).toBeTruthy();
    });
  });

  it("hides next runs preview when cron is disabled", async () => {
    mockLocalStorage();
    mockGetCron({ ...defaultCronConfig, enabled: false, next_scan_runs: [], next_tick_runs: [] });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Enable Autopilot Scheduling")).toBeTruthy();
    });

    // When disabled, the next runs preview should not appear
    expect(screen.queryByText("Next scan runs")).toBeNull();
  });

  it("calls PATCH with enabled: false when toggle is turned off", async () => {
    mockLocalStorage();
    const patchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/cron/config" && init?.method === "PATCH") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        return Promise.resolve(jsonResponse({ ...defaultCronConfig, ...body, enabled: body.enabled ?? true }));
      }
      return Promise.resolve(jsonResponse(defaultCronConfig));
    });
    vi.stubGlobal("fetch", patchMock);

    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText(/enable autopilot scheduling/i)).toBeTruthy();
    });

    // Toggle from checked=true to checked=false
    const toggle = screen.getByLabelText(/enable autopilot scheduling/i) as HTMLInputElement;
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith(
        "/api/cron/config",
        expect.objectContaining({
          method: "PATCH",
        }),
      );
    });
    // Verify the body string contains enabled:false
    const calls = patchMock.mock.calls;
    const patchCall = calls.find(([u, i]) => u === "/api/cron/config" && i?.method === "PATCH");
    expect(patchCall).toBeDefined();
    const bodyStr = patchCall?.[1]?.body as string;
    expect(bodyStr).toContain('"enabled":false');
  });

  it("renders timezone info", async () => {
    mockLocalStorage();
    mockGetCron();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/UTC/)).toBeTruthy();
    });
  });
});
