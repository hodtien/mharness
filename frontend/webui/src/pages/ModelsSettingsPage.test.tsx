import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ModelsSettingsPage from "./ModelsSettingsPage";

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

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve(data),
    headers: { get: () => null },
  };
}

const sampleProviders = {
  providers: [
    {
      id: "openai-default",
      label: "OpenAI",
      provider: "openai",
      api_format: "openai",
      default_model: "gpt-4o-mini",
      base_url: null,
      has_credentials: false,
      is_active: false,
    },
    {
      id: "claude-api",
      label: "Anthropic",
      provider: "anthropic",
      api_format: "anthropic",
      default_model: "claude-3-5-sonnet",
      base_url: null,
      has_credentials: true,
      is_active: true,
    },
  ],
};

const sampleModels = {
  "openai-default": [
    { id: "gpt-4o-mini", label: "gpt-4o-mini", context_window: 128000, is_default: true, is_custom: false },
    { id: "gpt-custom", label: "gpt-custom", context_window: null, is_default: false, is_custom: true },
  ],
  "claude-api": [
    { id: "claude-3-5-sonnet", label: "Sonnet", context_window: 200000, is_default: true, is_custom: false },
  ],
};

function setupFetch(extra: Record<string, () => object> = {}) {
  vi.stubGlobal(
    "fetch",
    (url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse(sampleModels));
      }
      if (url === "/api/providers") {
        return Promise.resolve(jsonResponse(sampleProviders));
      }
      for (const [pattern, fn] of Object.entries(extra)) {
        if (url.includes(pattern)) return Promise.resolve(jsonResponse(fn()));
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    },
  );
}

describe("ModelsSettingsPage", () => {
  it("renders loading state then provider accordions", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    expect(screen.getByText(/loading/i)).toBeTruthy();
    await waitFor(() => expect(screen.getByText("OpenAI")).toBeTruthy());
    expect(screen.getByText("Anthropic")).toBeTruthy();
  });

  it("shows model rows with built-in and custom badges", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0));
    expect(screen.getAllByText("gpt-custom").length).toBeGreaterThan(0);
    expect(screen.getByText("custom")).toBeTruthy();
    expect(screen.getAllByText("built-in").length).toBeGreaterThan(0);
  });

  it("shows context window and default badge", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText(/128,000|128000/)).toBeTruthy());
    expect(screen.getByText(/200,000|200000/)).toBeTruthy();
    expect(screen.getAllByText(/✓ default/).length).toBeGreaterThan(0);
  });

  it("hides delete button for built-in models, shows for custom", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /delete gpt-custom/i })).toBeTruthy(),
    );
    expect(screen.queryByRole("button", { name: /delete gpt-4o-mini/i })).toBeNull();
  });

  it("collapses and expands accordion on click", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("OpenAI")).toBeTruthy());

    const heading = screen.getByRole("button", { name: /openai/i });
    // Currently open — table row visible
    expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0);
    fireEvent.click(heading);
    // After collapse: row no longer visible
    await waitFor(() => expect(screen.queryByText("gpt-4o-mini")).toBeNull());
    // Re-expand
    fireEvent.click(heading);
    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0));
  });

  it("opens add model modal and submits", async () => {
    mockLocalStorage();
    const postCalls: Array<{ url: string; body: string }> = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse(sampleModels));
      }
      if (url === "/api/providers") {
        return Promise.resolve(jsonResponse(sampleProviders));
      }
      if (url === "/api/models" && init?.method === "POST") {
        postCalls.push({ url, body: String(init.body) });
        return Promise.resolve(jsonResponse({ ok: true, provider: "openai-default", model_id: "gpt-5" }));
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByRole("button", { name: /add custom model/i })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /add custom model/i }));

    await waitFor(() => expect(screen.getByPlaceholderText(/claude-3-5-sonnet|e\.g\./i)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/claude-3-5-sonnet|e\.g\./i), {
      target: { value: "gpt-5" },
    });

    fireEvent.click(screen.getByRole("button", { name: /add model/i }));

    await waitFor(() => expect(postCalls.length).toBe(1));
    const parsed = JSON.parse(postCalls[0].body);
    expect(parsed.model_id).toBe("gpt-5");
  });

  it("shows confirm dialog when delete is clicked, then calls DELETE", async () => {
    mockLocalStorage();
    const deleteCalls: string[] = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse(sampleModels));
      }
      if (url === "/api/providers") {
        return Promise.resolve(jsonResponse(sampleProviders));
      }
      if (url.includes("gpt-custom") && init?.method === "DELETE") {
        deleteCalls.push(url);
        return Promise.resolve(jsonResponse({ ok: true, provider: "openai-default", model_id: "gpt-custom" }));
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByRole("button", { name: /delete gpt-custom/i })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /delete gpt-custom/i }));

    await waitFor(() => expect(screen.getByText(/delete custom model\?/i)).toBeTruthy());
    expect(screen.getAllByText("gpt-custom").length).toBeGreaterThan(0);

    // Confirm delete
    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleteCalls.length).toBe(1));
    expect(deleteCalls[0]).toContain("gpt-custom");
  });

  it("cancel on delete dialog dismisses without calling API", async () => {
    mockLocalStorage();
    const deleteCalls: string[] = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      if (url === "/api/models" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse(sampleModels));
      }
      if (url === "/api/providers") {
        return Promise.resolve(jsonResponse(sampleProviders));
      }
      if (init?.method === "DELETE") {
        deleteCalls.push(url);
        return Promise.resolve(jsonResponse({ ok: true }));
      }
      return Promise.reject(new Error(`unexpected: ${url}`));
    });

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByRole("button", { name: /delete gpt-custom/i })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /delete gpt-custom/i }));
    await waitFor(() => expect(screen.getByText(/delete custom model\?/i)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByText(/delete custom model\?/i)).toBeNull());
    expect(deleteCalls.length).toBe(0);
  });
});
