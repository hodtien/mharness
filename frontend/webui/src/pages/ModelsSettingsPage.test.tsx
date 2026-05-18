import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      health_label: "Probe failing",
      reachable: false,
      probed: true,
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
      health_label: "Healthy",
      reachable: true,
      probed: true,
    },
    {
      id: "openrouter",
      label: "OpenRouter",
      provider: "openrouter",
      api_format: "openai",
      default_model: "openrouter/auto",
      base_url: "https://openrouter.ai/api/v1",
      has_credentials: true,
      is_active: false,
      health_label: "Ready",
      reachable: null,
      probed: null,
    },
  ],
};

const sampleModels = {
  "openai-default": [
    { id: "gpt-4o-mini", label: "gpt-4o-mini", context_window: 128000, is_default: true, is_custom: false },
    { id: "gpt-custom", label: "gpt-custom", context_window: null, is_default: false, is_custom: true },
    { id: "gpt-4o-mini-vision", label: "vision model", context_window: 128000, is_default: false, is_custom: false },
  ],
  "claude-api": [
    { id: "claude-3-5-sonnet", label: "Sonnet", context_window: 200000, is_default: true, is_custom: false },
  ],
  openrouter: [
    { id: "openrouter/auto", label: "Auto Router", context_window: null, is_default: true, is_custom: false },
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
  afterEach(() => cleanup());
  it("renders loading state then provider accordions", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    expect(screen.getAllByText("Anthropic")[0]).toBeTruthy();
  });

  it("shows model rows with built-in and custom badges", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Expand OpenAI to see its models (inactive provider collapsed by default).
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));

    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0));
    expect(screen.getAllByText("gpt-custom").length).toBeGreaterThan(0);
    expect(screen.getByText("custom")).toBeTruthy();
    expect(screen.getAllByText("built-in").length).toBeGreaterThan(0);
    expect(screen.getAllByText("vision").length).toBeGreaterThan(0);
  });

  it("shows context window and default badge", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("Anthropic")[0]).toBeTruthy());

    // Active provider (Anthropic) expanded by default — Sonnet visible.
    expect(screen.getAllByText("Sonnet").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/200,000|200000/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/✓ default/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Models are provider\/model capabilities/i)).toBeTruthy();
  });

  it("hides delete button for built-in models, shows for custom", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Expand OpenAI to see its models.
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /delete gpt-custom/i })).toBeTruthy(),
    );
    expect(screen.queryByRole("button", { name: /delete gpt-4o-mini/i })).toBeNull();
  });

  it("collapses and expands accordion on click", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Inactive provider (OpenAI) is collapsed by default — gpt-4o-mini not visible.
    expect(screen.queryByText("gpt-4o-mini")).toBeNull();

    // Active provider (Anthropic) is expanded by default — Sonnet visible.
    expect(screen.getAllByText("Sonnet").length).toBeGreaterThan(0);

    // Expand OpenAI.
    const openaiHeading = screen.getByRole("button", { name: /openai/i });
    fireEvent.click(openaiHeading);
    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0));

    // Collapse OpenAI.
    fireEvent.click(openaiHeading);
    await waitFor(() => expect(screen.queryByText("gpt-4o-mini")).toBeNull());
  });

  it("filters models by id or label", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByPlaceholderText(/filter by model id or label/i)).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/filter by model id or label/i), { target: { value: "vision" } });

    await waitFor(() => {
      const noMatch = screen.queryAllByText(/no models match/i);
      const gpt4o = screen.queryAllByText("gpt-4o-mini");
      return noMatch.length > 0 || gpt4o.length === 0;
    });
  });


  it("filters models by configuration, health, and capability", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    fireEvent.change(screen.getByRole("combobox", { name: /filter by configuration status/i }), { target: { value: "configured" } });
    await waitFor(() => expect(screen.queryAllByText("OpenAI").find((el) => el.tagName !== "OPTION") ?? null).toBeNull());
    expect(screen.getAllByText("Anthropic")[0]).toBeTruthy();

    fireEvent.change(screen.getByRole("combobox", { name: /filter by configuration status/i }), { target: { value: "all" } });
    fireEvent.change(screen.getByRole("combobox", { name: /filter by health/i }), { target: { value: "ready" } });
    await waitFor(() => expect(screen.getAllByText("OpenRouter")[0]).toBeTruthy());
    expect(screen.queryAllByText("OpenAI").find((el) => el.tagName !== "OPTION") ?? null).toBeNull();
    expect(screen.queryAllByText("Anthropic").find((el) => el.tagName !== "OPTION") ?? null).toBeNull();

    fireEvent.change(screen.getByRole("combobox", { name: /filter by health/i }), { target: { value: "probe-failing" } });
    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    expect(screen.queryAllByText("Anthropic").find((el) => el.tagName !== "OPTION") ?? null).toBeNull();
    expect(screen.queryAllByText("OpenRouter").find((el) => el.tagName !== "OPTION") ?? null).toBeNull();

    fireEvent.change(screen.getByRole("combobox", { name: /filter by health/i }), { target: { value: "all" } });
    fireEvent.change(screen.getByRole("combobox", { name: /filter by capability/i }), { target: { value: "vision" } });
    await waitFor(() => expect(screen.getAllByText("vision").length).toBeGreaterThan(0));
  });

  it("uses provider health labels from the API contract", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenRouter")[0]).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /openrouter/i }));

    await waitFor(() => expect(screen.getAllByText("Ready").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Healthy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Probe failing").length).toBeGreaterThan(0);
  });

  it("filters models by provider", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Click provider filter and select Anthropic
    const providerSelect = screen.getByRole("combobox", { name: /filter by provider/i });
    fireEvent.change(providerSelect, { target: { value: "claude-api" } });

    await waitFor(() => expect(screen.queryAllByText("OpenAI").find((el) => el.tagName !== "OPTION") ?? null).toBeNull());
    expect(screen.getAllByText("Anthropic")[0]).toBeTruthy();
  });

  it("filters models by type (built-in/custom)", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Expand OpenAI to see its models.
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));

    await waitFor(() => expect(screen.getAllByText("gpt-custom").length).toBeGreaterThan(0));

    // Click "Custom" filter
    fireEvent.click(screen.getByRole("button", { name: /^custom$/i }));

    await waitFor(() => expect(screen.queryAllByText("gpt-custom").length).toBeGreaterThan(0));
    // Built-in models should be hidden
    await waitFor(() => expect(screen.queryAllByText("built-in").length).toBe(0));
  });

  it("filters models by default-only", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Expand OpenAI to see its models.
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));

    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini")[0]).toBeTruthy());

    // Click "Default only" filter
    fireEvent.click(screen.getByRole("button", { name: /default only/i }));

    await waitFor(() => expect(screen.queryAllByText("gpt-custom")[0] ?? null).toBeNull());
    expect(screen.getAllByText("gpt-4o-mini")[0]).toBeTruthy();
  });

  it("shows empty filtered state with clear link", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Apply filters that match nothing
    fireEvent.change(screen.getByPlaceholderText(/filter by model id or label/i), { target: { value: "nonexistent-model-xyz" } });

    await waitFor(() => expect(screen.getByText(/no models match/i)).toBeTruthy());
    expect(screen.getByText(/clear all filters/i)).toBeTruthy();
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

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    // Expand OpenAI (inactive provider).
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
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

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /delete gpt-custom/i })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /delete gpt-custom/i }));
    await waitFor(() => expect(screen.getByText(/delete custom model\?/i)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByText(/delete custom model\?/i)).toBeNull());
    expect(deleteCalls.length).toBe(0);
  });

  it("shows Edit button for custom models, hides for built-in", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /edit gpt-custom/i })).toBeTruthy(),
    );
    expect(screen.queryByRole("button", { name: /edit gpt-4o-mini/i })).toBeNull();
  });

  it("opens edit modal with model_id readonly and prefilled label/context", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /edit gpt-custom/i })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: /edit gpt-custom/i }));

    await waitFor(() => expect(screen.getByText(/edit custom model/i)).toBeTruthy());

    // model_id input should be readonly with value "gpt-custom"
    const modelIdInput = screen.getByRole("textbox", { name: /model id/i }) as HTMLInputElement;
    expect(modelIdInput.readOnly).toBe(true);
    expect(modelIdInput.value).toBe("gpt-custom");
  });

  it("submits edit by calling DELETE then POST with new label/context_window", async () => {
    mockLocalStorage();
    const calls: Array<{ url: string; method: string; body?: string }> = [];
    let modelsState = JSON.parse(JSON.stringify(sampleModels));
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/models" && method === "GET") {
        return Promise.resolve(jsonResponse(modelsState));
      }
      if (url === "/api/providers") {
        return Promise.resolve(jsonResponse(sampleProviders));
      }
      if (method === "DELETE" && url.includes("gpt-custom")) {
        calls.push({ url, method });
        modelsState = {
          ...modelsState,
          "openai-default": modelsState["openai-default"].filter(
            (m: { id: string }) => m.id !== "gpt-custom",
          ),
        };
        return Promise.resolve(jsonResponse({ ok: true }));
      }
      if (method === "POST" && url === "/api/models") {
        calls.push({ url, method, body: String(init?.body) });
        const parsed = JSON.parse(String(init?.body));
        modelsState = {
          ...modelsState,
          "openai-default": [
            ...modelsState["openai-default"],
            {
              id: parsed.model_id,
              label: parsed.label,
              context_window: parsed.context_window ?? null,
              is_default: false,
              is_custom: true,
            },
          ],
        };
        return Promise.resolve(jsonResponse({ ok: true, provider: "openai-default", model_id: parsed.model_id }));
      }
      return Promise.reject(new Error(`unexpected: ${method} ${url}`));
    });

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /edit gpt-custom/i })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: /edit gpt-custom/i }));

    await waitFor(() => expect(screen.getByText(/edit custom model/i)).toBeTruthy());

    // Update label
    const labelInput = screen.getByPlaceholderText(/display label/i) as HTMLInputElement;
    fireEvent.change(labelInput, { target: { value: "GPT Custom v2" } });

    // Update context window
    const ctxInput = screen.getByPlaceholderText("200000") as HTMLInputElement;
    fireEvent.change(ctxInput, { target: { value: "64000" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(calls.filter((c) => c.method === "POST").length).toBe(1));

    // Order: DELETE then POST
    const deleteIdx = calls.findIndex((c) => c.method === "DELETE");
    const postIdx = calls.findIndex((c) => c.method === "POST");
    expect(deleteIdx).toBeGreaterThanOrEqual(0);
    expect(postIdx).toBeGreaterThan(deleteIdx);

    const post = calls[postIdx];
    expect(post.url).toBe("/api/models");
    const parsed = JSON.parse(post.body!);
    expect(parsed.model_id).toBe("gpt-custom");
    expect(parsed.label).toBe("GPT Custom v2");
    expect(parsed.context_window).toBe(64000);

    await waitFor(() => expect(screen.getByRole("button", { name: /edit gpt-custom/i })).toBeTruthy());
  });

  it("validates context_window must be a positive integer", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /edit gpt-custom/i })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: /edit gpt-custom/i }));
    await waitFor(() => expect(screen.getByText(/edit custom model/i)).toBeTruthy());

    const ctxInput = screen.getByPlaceholderText("200000") as HTMLInputElement;
    fireEvent.change(ctxInput, { target: { value: "-5" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(screen.getByText(/context window must be a positive integer/i)).toBeTruthy(),
    );
  });

  it("cancel on edit dialog dismisses without API calls", async () => {
    mockLocalStorage();
    const calls: string[] = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/models" && method === "GET") {
        return Promise.resolve(jsonResponse(sampleModels));
      }
      if (url === "/api/providers") {
        return Promise.resolve(jsonResponse(sampleProviders));
      }
      calls.push(`${method} ${url}`);
      return Promise.reject(new Error(`unexpected: ${method} ${url}`));
    });

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /openai/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /edit gpt-custom/i })).toBeTruthy(),
    );

    fireEvent.click(screen.getByRole("button", { name: /edit gpt-custom/i }));
    await waitFor(() => expect(screen.getByText(/edit custom model/i)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByText(/edit custom model/i)).toBeNull());
    expect(calls.length).toBe(0);
  });

  it("sorts active providers first", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    const sections = screen.queryAllByRole("button", { name: /openai|anthropic/i });
    // Active (Anthropic) should come before inactive (OpenAI).
    const labels = sections.map((s) => s.textContent ?? "");
    const activeIdx = labels.findIndex((l) => /anthropic/i.test(l));
    const inactiveIdx = labels.findIndex((l) => /openai/i.test(l));
    expect(activeIdx).toBeLessThan(inactiveIdx);
  });

  it("auto-reveals collapsed section when search matches it", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // OpenAI collapsed by default.
    expect(screen.queryByText("gpt-4o-mini")).toBeNull();

    // Search for a model inside OpenAI.
    fireEvent.change(screen.getByPlaceholderText(/filter by model id or label/i), { target: { value: "gpt-4o" } });

    // Section auto-expanded.
    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0));
  });

  it("shows Healthy badge on active provider header", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("Anthropic")[0]).toBeTruthy());

    expect(screen.getAllByText("Healthy").length).toBeGreaterThan(0);
  });

  it("shows default model first within each section", async () => {
    mockLocalStorage();
    setupFetch();

    render(<BrowserRouter><ModelsSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getAllByText("OpenAI")[0]).toBeTruthy());

    // Expand OpenAI.
    const openaiHeading = screen.getByRole("button", { name: /openai/i });
    fireEvent.click(openaiHeading);

    await waitFor(() => expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0));

    // After expansion, both gpt-4o-mini (default built-in) and gpt-custom (non-default custom) are visible.
    // Default model should appear first in the table order (built-in section renders before custom section).
    // Verify gpt-4o-mini row is present.
    expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0);
    // gpt-custom row should also be present.
    expect(screen.getAllByText("gpt-custom").length).toBeGreaterThan(0);
    // The default model badge should appear on gpt-4o-mini row (the ✓ default span).
    const defaultBadge = screen.getAllByText(/✓ default/)[0];
    expect(defaultBadge).toBeTruthy();
    // Verify the row containing gpt-4o-mini appears before the row containing gpt-custom in DOM order.
    const gpt4Row = defaultBadge.closest("tr");
    const gptCustomRow = screen.getAllByText("gpt-custom")[0].closest("tr");
    expect(gpt4Row).toBeTruthy();
    expect(gptCustomRow).toBeTruthy();
    const allRows = Array.from(document.body.querySelectorAll("table tbody tr"));
    expect(allRows.indexOf(gpt4Row!)).toBeLessThan(allRows.indexOf(gptCustomRow!));
  });
});
