import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import PipelinePage from "./PipelinePage";

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
    headers: { get: () => null },
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

const sampleCards = [
  {
    id: "card-queued-1",
    title: "Add login form",
    status: "queued",
    source_kind: "manual_idea",
    score: 75,
    labels: ["frontend"],
    created_at: Date.now() / 1000 - 3600,
    updated_at: Date.now() / 1000 - 1800,
  },
  {
    id: "card-running-1",
    title: "Fix auth bug",
    status: "running",
    source_kind: "github_issue",
    score: 100,
    labels: [],
    created_at: Date.now() / 1000 - 7200,
    updated_at: Date.now() / 1000 - 600,
  },
  {
    id: "card-pr-1",
    title: "Refactor api client",
    status: "pr_open",
    source_kind: "github_pr",
    score: 50,
    labels: [],
    created_at: Date.now() / 1000 - 600,
    updated_at: Date.now() / 1000 - 300,
  },
  {
    id: "card-done-1",
    title: "Add docs",
    status: "completed",
    source_kind: "manual_idea",
    score: 30,
    labels: [],
    created_at: Date.now() / 1000 - 86400,
    updated_at: Date.now() / 1000 - 86400,
  },
];

describe("PipelinePage", () => {
  beforeEach(() => {
    mockLocalStorage();
  });

  it("renders 4 kanban columns and cards by status group", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: [] }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    // Wait for cards
    await screen.findByText("Add login form");

    expect(screen.getByText("Queue")).toBeTruthy();
    expect(screen.getByText("In Progress")).toBeTruthy();
    expect(screen.getByText("Review")).toBeTruthy();
    expect(screen.getByText("Done")).toBeTruthy();

    expect(screen.getByText("Add login form")).toBeTruthy();
    expect(screen.getByText("Fix auth bug")).toBeTruthy();
    expect(screen.getByText("Refactor api client")).toBeTruthy();
    expect(screen.getByText("Add docs")).toBeTruthy();
  });

  it("opens drawer on card click and shows action buttons", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: [] }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    const cardTitle = await screen.findByText("Add login form");
    fireEvent.click(cardTitle);

    expect(await screen.findByRole("dialog", { name: /card detail/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Accept$/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Reject$/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Retry$/i })).toBeTruthy();
  });

  it("calls POST action endpoint when Accept is clicked", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url === "/api/pipeline/cards/card-queued-1/action" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ ...sampleCards[0], status: "accepted" }));
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    const cardTitle = await screen.findByText("Add login form");
    fireEvent.click(cardTitle);

    const acceptBtn = await screen.findByRole("button", { name: /^Accept$/i });
    fireEvent.click(acceptBtn);

    await waitFor(() => {
      const actionCalls = fetchMock.mock.calls.filter((c) =>
        String(c[0]).endsWith("/action"),
      );
      expect(actionCalls.length).toBe(1);
      expect(actionCalls[0][1]?.method).toBe("POST");
      const body = JSON.parse(String(actionCalls[0][1]?.body ?? "{}"));
      expect(body).toEqual({ action: "accept" });
    });
  });

  it("opens the New idea modal and submits POST /api/pipeline/cards", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url === "/api/pipeline/cards" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          id: "card-new-1",
          title: "New thing",
          status: "queued",
          source_kind: "manual_idea",
          score: 0,
          labels: ["a", "b"],
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
        }));
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    await screen.findByText("Add login form");

    fireEvent.click(screen.getByRole("button", { name: /\+ New idea/i }));

    expect(await screen.findByRole("dialog", { name: /new idea/i })).toBeTruthy();

    const titleInput = screen.getByPlaceholderText(/what needs to be done/i);
    fireEvent.change(titleInput, { target: { value: "New thing" } });

    const bodyInput = screen.getByPlaceholderText(/optional details/i);
    fireEvent.change(bodyInput, { target: { value: "details" } });

    const labelsInput = screen.getByPlaceholderText(/frontend, bug/i);
    fireEvent.change(labelsInput, { target: { value: "a, b , " } });

    fireEvent.click(screen.getByRole("button", { name: /^Submit$/i }));

    await waitFor(() => {
      const postCalls = fetchMock.mock.calls.filter(
        (c) => c[0] === "/api/pipeline/cards" && (c[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(postCalls.length).toBe(1);
      const body = JSON.parse(String((postCalls[0][1] as RequestInit).body ?? "{}"));
      expect(body).toEqual({ title: "New thing", body: "details", labels: ["a", "b"] });
    });
  });

  it("loads policy YAML and saves via PATCH /api/pipeline/policy", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: [], updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url === "/api/pipeline/policy" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ yaml_content: "intake: {}\n", parsed: {} }));
      }
      if (url === "/api/pipeline/policy" && init?.method === "PATCH") {
        return Promise.resolve(jsonResponse({ yaml_content: "intake: {}\nfoo: bar\n", parsed: {} }));
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Policy$/i }));

    const textarea = await screen.findByDisplayValue(/intake: {}/);
    fireEvent.change(textarea, { target: { value: "intake: {}\nfoo: bar\n" } });

    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => {
      const patchCalls = fetchMock.mock.calls.filter(
        (c) => c[0] === "/api/pipeline/policy" && (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCalls.length).toBe(1);
      const body = JSON.parse(String((patchCalls[0][1] as RequestInit).body ?? "{}"));
      expect(body.yaml_content).toBe("intake: {}\nfoo: bar\n");
    });
  });

  it("shows validation error when policy PATCH returns 400", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: [], updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url === "/api/pipeline/policy" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ yaml_content: "bad: [", parsed: null }));
      }
      if (url === "/api/pipeline/policy" && init?.method === "PATCH") {
        return Promise.resolve({
          ok: false,
          status: 400,
          statusText: "Bad Request",
          headers: { get: () => null },
          json: async () => ({ detail: { error: "invalid_yaml", message: "bad yaml syntax" } }),
          text: async () => "{}",
        });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Policy$/i }));
    await screen.findByDisplayValue(/bad:/);

    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await screen.findByText(/400 Bad Request/i);
  });

  it("starts polling when cards include an active status and stops when all terminal", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const activeCards = [
      { id: "card-1", title: "Running task", status: "running", source_kind: "manual_idea", score: 80, labels: [], created_at: 1, updated_at: 1 },
    ];
    const terminalCards = [
      { id: "card-2", title: "Done task", status: "completed", source_kind: "manual_idea", score: 60, labels: [], created_at: 1, updated_at: 1 },
    ];

    let cardCallCount = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/pipeline/cards") {
        cardCallCount++;
        return Promise.resolve(jsonResponse({ cards: cardCallCount < 4 ? activeCards : terminalCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    const cardCalls = () => fetchMock.mock.calls.filter((c) => c[0] === "/api/pipeline/cards");
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    await screen.findByText("Running task");

    // First auto-poll
    await vi.advanceTimersByTimeAsync(5000);
    expect(cardCalls().length).toBe(2);

    // Second auto-poll after another 5s
    await vi.advanceTimersByTimeAsync(5000);
    expect(cardCalls().length).toBe(3);

    // Third poll brings terminal card → polling should stop
    await vi.advanceTimersByTimeAsync(5000);
    expect(cardCalls().length).toBe(4);

    // No more fetch calls after polling stops
    await vi.advanceTimersByTimeAsync(5000);
    await vi.advanceTimersByTimeAsync(5000);
    expect(cardCalls().length).toBe(4);

    vi.useRealTimers();
  });

  it("shows 'Last updated Xs ago' indicator when board is active", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const cards = [
      { id: "card-1", title: "Running task", status: "running", source_kind: "manual_idea", score: 80, labels: [], created_at: 1, updated_at: 1 },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: [] }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    await screen.findByText("Running task");

    expect(screen.getByText(/Last updated \d+s ago/)).toBeTruthy();

    await vi.advanceTimersByTimeAsync(3000);

    expect(screen.getByText(/Last updated \d+s ago/)).toBeTruthy();

    vi.useRealTimers();
  });

  it("does not poll when all cards are terminal", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const terminalCards = [
      { id: "card-1", title: "Done task", status: "completed", source_kind: "manual_idea", score: 60, labels: [], created_at: 1, updated_at: 1 },
      { id: "card-2", title: "Merged task", status: "merged", source_kind: "github_issue", score: 90, labels: [], created_at: 1, updated_at: 1 },
    ];

    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/pipeline/cards") {
        return Promise.resolve(jsonResponse({ cards: terminalCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    await screen.findByText("Done task");
    // Indicator shows after initial load even with terminal-only cards
    expect(screen.getByText(/Last updated/)).toBeTruthy();

    await vi.advanceTimersByTimeAsync(20000);

    // No extra fetch calls beyond initial load
    expect(fetchMock.mock.calls.filter((c) => c[0] === "/api/pipeline/cards").length).toBe(1);

    vi.useRealTimers();
  });
});
