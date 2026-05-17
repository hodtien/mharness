import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ProviderSettingsPage from "./ProviderSettingsPage";

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
  return { ok: true, status: 200, statusText: "OK", json: () => Promise.resolve(data), headers: { get: () => null } };
}

const sampleProviders = {
  providers: [
    {
      id: "openai-default",
      label: "OpenAI",
      provider: "openai",
      api_format: "openai",
      default_model: "gpt-4o-mini",
      base_url: "https://api.openai.com/v1",
      has_credentials: false,
      is_active: false,
      health_label: "Probe failing",
      reachable: false,
      probed: true,
    },
    {
      id: "anthropic-default",
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

describe("ProviderSettingsPage", () => {
  it("renders provider grid with status badges", async () => {
    mockLocalStorage();
    vi.stubGlobal("fetch", (url: string) => {
      if (url === "/api/providers") return Promise.resolve(jsonResponse(sampleProviders));
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    render(<BrowserRouter><ProviderSettingsPage /></BrowserRouter>);

    await waitFor(() => {
      expect(screen.getAllByText("OpenAI").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("Anthropic").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Healthy").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Probe failing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0);
    expect(screen.getByText(/active route is usable for new sessions/i)).toBeTruthy();
    expect(screen.getByText(/latency and .*last verified/i)).toBeTruthy();
  });

  it("renders Verify all button when providers with credentials exist", async () => {
    mockLocalStorage();
    vi.stubGlobal("fetch", (url: string) => {
      if (url === "/api/providers") return Promise.resolve(jsonResponse(sampleProviders));
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    render(<BrowserRouter><ProviderSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("OpenAI")).toBeTruthy());
    expect(screen.getByRole("button", { name: /verify all/i })).toBeTruthy();
  });

  it("opens modal on card click and verifies provider", async () => {
    mockLocalStorage();
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === "/api/providers") return Promise.resolve(jsonResponse(sampleProviders));
      if (url === "/api/providers/openai-default/credentials") {
        return Promise.resolve(jsonResponse({ ok: true, api_key_suffix: "abcd" }));
      }
      if (url === "/api/providers/openai-default/verify") {
        return Promise.resolve(jsonResponse({ ok: true, models: ["gpt-4o-mini", "gpt-4o"], latency_ms: 150 }));
      }
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    render(<BrowserRouter><ProviderSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("OpenAI")).toBeTruthy());

    fireEvent.click(screen.getByText("OpenAI"));

    await waitFor(() => expect(screen.getByPlaceholderText("Enter API key")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("Enter API key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: /^Verify$/ }));

    await waitFor(() => {
      expect(screen.getByText("Verification succeeded.")).toBeTruthy();
    });
    expect(screen.getByText("gpt-4o")).toBeTruthy();
    expect(calls.some((c) => c.url === "/api/providers/openai-default/credentials" && c.init?.method === "POST")).toBe(true);
    expect(calls.some((c) => c.url === "/api/providers/openai-default/verify" && c.init?.method === "POST")).toBe(true);
  });

  it("disables modal and cards while batch verifying", async () => {
    mockLocalStorage();
    let resolveVerify: (value: unknown) => void;
    const verifyPromise = new Promise((r) => { resolveVerify = r; });
    vi.stubGlobal("fetch", (url: string) => {
      if (url === "/api/providers") return Promise.resolve(jsonResponse(sampleProviders));
      if (url.includes("/verify")) return verifyPromise;
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    render(<BrowserRouter><ProviderSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("OpenAI")).toBeTruthy());

    // Click verify all
    fireEvent.click(screen.getByRole("button", { name: /verify all/i }));

    // While verifying, "Verify all" button should be disabled
    await waitFor(() => expect(screen.getByRole("button", { name: /verifying…/i })).toBeTruthy());

    // Cards should be disabled (pointer-events-none + opacity-60)
    const cards = screen.getAllByRole("button");
    // First two buttons are cards, third is verify all
    expect(cards[0]).toHaveProperty("disabled", true);

    // Modal should NOT be open during batch verify
    expect(screen.queryByPlaceholderText("Enter API key")).toBeNull();

    // Resolve verify and wait for completion
    resolveVerify!(jsonResponse({ ok: true, models: [] }));
    await waitFor(() => expect(screen.getByRole("button", { name: /verify all/i })).toBeTruthy());
  });
});
