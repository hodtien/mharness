import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within, cleanup } from "@testing-library/react";
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

const LONG_SYSTEM_PROMPT = `${"System prompt details. ".repeat(30)}Final expanded instructions.`;

const sampleAgents = [
  {
    name: "gan-generator",
    description: "Generates implementation changes for autopilot.",
    model: "gpt-4o-mini",
    effort: "medium",
    permission_mode: "default",
    tools_count: 3,
    has_system_prompt: true,
    source_file: "agents/gan-generator.md",
  },
  {
    name: "code-reviewer",
    description: "Reviews autopilot changes before completion.",
    model: "claude-3-5-sonnet",
    effort: "high",
    permission_mode: "plan",
    tools_count: 2,
    has_system_prompt: true,
    source_file: "agents/code-reviewer.md",
  },
  {
    name: "Default Chat Agent",
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
    model: "missing-model",
    effort: "high",
    permission_mode: "plan",
    tools_count: 4,
    has_system_prompt: true,
    source_file: "agents/researcher.md",
  },
];

const sampleAgentDetails = {
  "Default Chat Agent": {
    name: "Default Chat Agent",
    description: "Full generic helper agent description shown in the details modal.",
    system_prompt: LONG_SYSTEM_PROMPT,
    tools: ["read_file", "grep", "bash"],
    model: "gpt-4o-mini",
    effort: "medium",
    permission_mode: "default",
    source_file: "/agents/Default Chat Agent.md",
    has_system_prompt: true,
  },
  researcher: {
    name: "researcher",
    description: LONG_DESC,
    system_prompt: "Research carefully.",
    tools: ["web_search", "web_fetch", "read_file", "grep"],
    model: "missing-model",
    effort: "high",
    permission_mode: "plan",
    source_file: "agents/researcher.md",
    has_system_prompt: true,
  },
};

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
    if (url.startsWith("/api/agents/") && (!init?.method || init.method === "GET")) {
      const name = decodeURIComponent(url.slice("/api/agents/".length));
      return Promise.resolve(jsonResponse(sampleAgentDetails[name as keyof typeof sampleAgentDetails]));
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

async function renderAgentsPage() {
  render(
    <BrowserRouter>
      <AgentsSettingsPage />
    </BrowserRouter>,
  );

  await waitFor(() => expect(screen.getAllByText("Default Chat Agent")[0]).toBeTruthy());
}

describe("AgentsSettingsPage", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders loading skeleton then agent cards with badges", async () => {
    mockLocalStorage();
    setupFetch();

    render(
      <BrowserRouter>
        <AgentsSettingsPage />
      </BrowserRouter>,
    );

    // Loading state shows skeleton, not text
    expect(screen.getByLabelText("Loading content")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("Default Chat Agent")[0]).toBeTruthy());
    expect(screen.getByText("researcher")).toBeTruthy();
    // model badge value rendered (multiple agents may share the same model)
    expect(screen.getAllByText("gpt-4o-mini").length).toBeGreaterThan(0);
    // long description should be truncated with ellipsis
    const truncated = screen.getByText(/^R+\u2026$/);
    expect(truncated.textContent?.length).toBe(120);
  });


  it("shows routing defaults and broken-model warnings", async () => {
    mockLocalStorage();
    setupFetch();

    await renderAgentsPage();

    expect(screen.getByText("Default routing by use case")).toBeTruthy();
    expect(screen.getAllByText("Code Agent").length).toBeGreaterThan(0);
    expect(screen.getAllByText("gan-generator").length).toBeGreaterThan(0);
    expect(screen.getAllByText("code-reviewer").length).toBeGreaterThan(0);
    expect(screen.getByText("Fast Agent")).toBeTruthy();
    expect(screen.getByText(/header model selection temporarily overrides/i)).toBeTruthy();
    expect(screen.getByText(/Selected model\/provider is unavailable: missing-model/i)).toBeTruthy();
  });

  it("shows View details button on agent cards", async () => {
    mockLocalStorage();
    setupFetch();

    await renderAgentsPage();

    expect(screen.getAllByRole("button", { name: /view details/i })).toHaveLength(sampleAgents.length);
    // help microcopy from page header
    expect(screen.getByText(/Agents are task profiles/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /clone/i }).length).toBeGreaterThan(0);
    expect(screen.getByText(/header model picker is only a temporary override/i)).toBeTruthy();
  });

  it("opens the details modal when clicking View details", async () => {
    mockLocalStorage();
    setupFetch();

    await renderAgentsPage();
    // gan-generator is pinned first; click on Default Chat Agent's View details
    const viewDetailButtons = screen.getAllByRole("button", { name: /view details/i });
    const chatDetailBtn = viewDetailButtons.find((btn) => {
      const card = btn.closest(".rounded-xl");
      return card?.textContent?.includes("Default Chat Agent");
    });
    fireEvent.click(chatDetailBtn!);

    await waitFor(() => expect(screen.getByText("Full generic helper agent description shown in the details modal.")).toBeTruthy());
    expect(screen.getAllByText("Default Chat Agent").length).toBeGreaterThan(1);
    expect(screen.getByRole("button", { name: "✕" })).toBeTruthy();
  });

  it("shows agent name, description, model metadata, and tools in the details modal", async () => {
    mockLocalStorage();
    setupFetch();

    await renderAgentsPage();
    const viewDetailButtons = screen.getAllByRole("button", { name: /view details/i });
    const chatDetailBtn = viewDetailButtons.find((btn) => btn.closest(".rounded-xl")?.textContent?.includes("Default Chat Agent"));
    fireEvent.click(chatDetailBtn!);

    await waitFor(() => expect(screen.getByText("Full generic helper agent description shown in the details modal.")).toBeTruthy());
    const modal = screen.getByText("Full generic helper agent description shown in the details modal.").closest(".space-y-5");
    expect(modal).toBeTruthy();
    const modalContent = within(modal as HTMLElement);
    expect(screen.getAllByText("Default Chat Agent").length).toBeGreaterThan(1);
    expect(modalContent.getByText("gpt-4o-mini")).toBeTruthy();
    expect(modalContent.getByText("medium")).toBeTruthy();
    expect(modalContent.getByText("default")).toBeTruthy();
    expect(modalContent.getByText("/agents/Default Chat Agent.md")).toBeTruthy();
    expect(modalContent.getByText("read_file")).toBeTruthy();
    expect(modalContent.getByText("grep")).toBeTruthy();
    expect(modalContent.getByText("bash")).toBeTruthy();
  });

  it("opens detail modal and expands system prompt via expand button", async () => {
    mockLocalStorage();
    setupFetch();

    await renderAgentsPage();
    // Click View details to open Default Chat Agent's detail modal
    const viewDetailButtons = screen.getAllByRole("button", { name: /view details/i });
    const chatDetailBtn = viewDetailButtons.find((btn) => btn.closest(".rounded-xl")?.textContent?.includes("Default Chat Agent"));
    fireEvent.click(chatDetailBtn!);

    // In detail modal, expand button appears when system prompt exists
    await waitFor(() => expect(screen.getByRole("button", { name: /^expand$/i })).toBeTruthy());
    // Full system prompt text not yet visible
    expect(screen.queryByText(/Final expanded instructions/)).toBeNull();

    // Click the expand button to open the system prompt full-screen modal
    fireEvent.click(screen.getByRole("button", { name: /^expand$/i }));

    // Full content is now visible
    expect(screen.getByText(/Final expanded instructions/)).toBeTruthy();
    // A System Prompt heading should appear in the expanded modal
    expect(screen.getByText(/System Prompt — Default Chat Agent/)).toBeTruthy();
  });

  it("opens inline editor when clicking Edit and saves changes", async () => {
    mockLocalStorage();
    const calls = setupFetch();

    render(
      <BrowserRouter>
        <AgentsSettingsPage />
      </BrowserRouter>,
    );

    await waitFor(() => expect(screen.getAllByText("Default Chat Agent")[0]).toBeTruthy());

    // Click the Edit button for "Default Chat Agent" (the first unpinned agent, index 1 in order)
    const editButtons = screen.getAllByRole("button", { name: /edit/i });
    // gan-generator is first (pinned), Default Chat Agent is second
    const chatEditIdx = editButtons.findIndex((btn) => {
      const card = btn.closest(".rounded-xl");
      return card?.textContent?.includes("Default Chat Agent");
    });
    fireEvent.click(editButtons[chatEditIdx]);

    // Editor should appear
    await waitFor(() => expect(screen.getByTestId("editor-Default Chat Agent")).toBeTruthy());

    // Change effort to "high"
    fireEvent.change(screen.getByTestId("editor-Default Chat Agent").querySelectorAll("select")[1], { target: { value: "high" } });

    // Save
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(calls.some((call) => call.init?.method === "PATCH")).toBe(true));

    // PATCH was issued
    const patch = calls.find((c) => c.init?.method === "PATCH");
    expect(patch).toBeTruthy();
    expect(patch?.url).toBe("/api/agents/Default%20Chat%20Agent");
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

    await waitFor(() => expect(screen.getAllByText("Default Chat Agent")[0]).toBeTruthy());

    fireEvent.click(screen.getAllByRole("button", { name: /edit/i }).find((btn) => btn.closest(".rounded-xl")?.textContent?.includes("Default Chat Agent"))!);
    await waitFor(() => expect(screen.getByTestId("editor-Default Chat Agent")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    // Error feedback badge appears with the API error details visible in the form
    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toBeTruthy();
      // Verify the badge contains meaningful error info (status code or message)
      const text = alert.textContent ?? "";
      expect(text).toMatch(/400|Invalid effort/i);
    });
  });
});
