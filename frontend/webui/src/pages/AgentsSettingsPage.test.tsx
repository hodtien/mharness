import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import AgentsSettingsPage from "./AgentsSettingsPage";

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
    statusText: "OK",
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    headers: { get: () => null },
  };
}

const LONG_DESC =
  "R".repeat(130); // 130 chars — exceeds the 120-char truncation limit

const sampleAgents = [
  {
    name: "general-purpose",
    description: "Generic helper agent for everyday work.",
    model: "gpt-4o-mini",
    effort: "medium",
    permission_mode: "default",
    tools_count: null,
    has_system_prompt: true,
    source_file: null,
  },
  {
    name: "researcher",
    description: LONG_DESC,
    model: null,
    effort: "high",
    permission_mode: "plan",
    tools_count: 4,
    has_system_prompt: true,
    source_file: "/tmp/researcher.md",
  },
];

const sampleModels = {
  "openai-default": [
    { id: "gpt-4o-mini", label: "gpt-4o-mini", context_window: 128000, is_default: true, is_custom: false },
  ],
  "claude-api": [
    { id: "claude-3-5-sonnet", label: "Sonnet", context_window: 200000, is_default: true, is_custom: false },
  ],
};

interface FetchOverrides {
  patch?: (name: string, body: Record<string, unknown>) => { status?: number; data: unknown };
}

function setupFetch(overrides: FetchOverrides = {}) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/agents" && (!init?.method || init.method === "GET")) {
      return Promise.resolve(jsonResponse(sampleAgents));
    }
    if (url === "/api/models" && (!init?.method || init.method === "GET")) {
      return Promise.resolve(jsonResponse(sampleModels));
    }
    if (url.startsWith("/api/agents/") && init?.method === "PATCH") {
      const name = decodeURIComponent(url.slice("/api/agents/".length));
      const body = JSON.parse(String(init?.body ?? "{}"));
      const result = overrides.patch?.(name, body);
      if (result) {
        return Promise.resolve(jsonResponse(result.data, result.status ?? 200));
      }
      const original = sampleAgents.find((a) => a.name === name);
      return Promise.resolve(jsonResponse({ ...original, ...body }));
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  return calls;
}

describe("AgentsSettingsPage", () => {
  it("renders loading state then agent cards with badges", async () => {
    mockLocalStorage();
    setupFetch();

    render(
      <BrowserRouter>
        <AgentsSettingsPage />
      </BrowserRouter>,
    );

    expect(screen.getByText(/loading agents/i)).toBeTruthy();
    await waitFor(() => expect(screen.getByText("general-purpose")).toBeTruthy());
    expect(screen.getByText("researcher")).toBeTruthy();
    // model badge value rendered
    expect(screen.getByText("gpt-4o-mini")).toBeTruthy();
    // long description should be truncated with ellipsis
    const truncated = screen.getByText(/^R+\u2026$/);
    expect(truncated.textContent?.length).toBe(120);
  });

  it("opens inline editor when clicking Edit and saves changes", async () => {
    mockLocalStorage();
    const calls = setupFetch();

    render(
      <BrowserRouter>
        <AgentsSettingsPage />
      </BrowserRouter>,
    );

    await waitFor(() => expect(screen.getByText("general-purpose")).toBeTruthy());

    // Click the first Edit button
    const editButtons = screen.getAllByRole("button", { name: /edit/i });
    fireEvent.click(editButtons[0]);

    // Editor should appear
    await waitFor(() => expect(screen.getByTestId("editor-general-purpose")).toBeTruthy());

    // Change effort to "high"
    const effortSelects = screen.getAllByRole("combobox");
    // 0=model, 1=effort, 2=permission
    fireEvent.change(effortSelects[1], { target: { value: "high" } });

    // Save
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/saved/i)).toBeTruthy());

    // PATCH was issued
    const patch = calls.find((c) => c.init?.method === "PATCH");
    expect(patch).toBeTruthy();
    expect(patch?.url).toBe("/api/agents/general-purpose");
    const body = JSON.parse(String(patch?.init?.body ?? "{}"));
    expect(body.effort).toBe("high");
  });

  it("shows error toast when PATCH fails", async () => {
    mockLocalStorage();
    setupFetch({
      patch: () => ({ status: 400, data: "Invalid effort" }),
    });

    render(
      <BrowserRouter>
        <AgentsSettingsPage />
      </BrowserRouter>,
    );

    await waitFor(() => expect(screen.getByText("general-purpose")).toBeTruthy());

    fireEvent.click(screen.getAllByRole("button", { name: /edit/i })[0]);
    await waitFor(() => expect(screen.getByTestId("editor-general-purpose")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/Invalid effort|400/i)).toBeTruthy());
  });
});
