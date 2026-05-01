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
      expect(screen.getByText("OpenAI")).toBeTruthy();
    });
    expect(screen.getByText("Anthropic")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.getByText("gpt-4o-mini")).toBeTruthy();
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
        return Promise.resolve(jsonResponse({ ok: true, models: ["gpt-4o-mini", "gpt-4o"] }));
      }
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    render(<BrowserRouter><ProviderSettingsPage /></BrowserRouter>);

    await waitFor(() => expect(screen.getByText("OpenAI")).toBeTruthy());

    fireEvent.click(screen.getByText("OpenAI"));

    await waitFor(() => expect(screen.getByPlaceholderText("Enter API key")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("Enter API key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: /verify/i }));

    await waitFor(() => {
      expect(screen.getByText("Verification succeeded.")).toBeTruthy();
    });
    expect(screen.getByText("gpt-4o")).toBeTruthy();
    expect(calls.some((c) => c.url === "/api/providers/openai-default/credentials" && c.init?.method === "POST")).toBe(true);
    expect(calls.some((c) => c.url === "/api/providers/openai-default/verify" && c.init?.method === "POST")).toBe(true);
  });
});
