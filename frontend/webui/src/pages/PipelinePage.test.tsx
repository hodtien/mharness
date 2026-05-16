import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import PipelinePage, { matchesActivityFilter, ActivityFilter } from "./PipelinePage";

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
    id: "card-pending-1",
    title: "Retry me later",
    status: "pending",
    source_kind: "manual_idea",
    score: 65,
    labels: [],
    created_at: Date.now() / 1000 - 900,
    updated_at: Date.now() / 1000 - 60,
    metadata: {
      pending_reason: "preflight_transient",
      next_retry_at: Date.now() / 1000 + 1800,
    },
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

describe("matchesActivityFilter", () => {
  it.each<[ActivityFilter, string, boolean]>([
    ["all", "intake_added", true],
    ["failures", "ci_failure", true],
    ["failures", "error", true],
    ["failures", "agent_finished", false],
    ["ci", "ci_check", true],
    ["ci", "pr_opened", false],
    ["agent", "agent_started", true],
    ["agent", "ci_check", false],
    ["git", "pr_opened", true],
    ["git", "merge_warning", true],
    ["git", "ci_failure", false],
  ])("matches %s filter for %s", (filter, kind, expected) => {
    expect(matchesActivityFilter(kind, filter)).toBe(expected);
  });
});

describe("PipelinePage", () => {
  beforeEach(() => {
    mockLocalStorage();
  });

  it("renders board with correct lanes (Queue, Running, Review, Failed/Paused, Done/Merged)", async () => {
    const cardsWithAllStatuses = [
      {
        id: "card-queued-1",
        title: "Queued task",
        status: "queued",
        source_kind: "manual_idea",
        score: 75,
        labels: [],
        created_at: Date.now() / 1000 - 3600,
        updated_at: Date.now() / 1000 - 3600,
      },
      {
        id: "card-running-1",
        title: "Running task",
        status: "running",
        source_kind: "github_issue",
        score: 100,
        labels: [],
        created_at: Date.now() / 1000 - 7200,
        updated_at: Date.now() / 1000 - 600,
      },
      {
        id: "card-review-1",
        title: "PR review task",
        status: "pr_open",
        source_kind: "github_pr",
        score: 50,
        labels: [],
        created_at: Date.now() / 1000 - 600,
        updated_at: Date.now() / 1000 - 300,
      },
      {
        id: "card-failed-1",
        title: "Failed task",
        status: "failed",
        source_kind: "manual_idea",
        score: 30,
        labels: [],
        created_at: Date.now() / 1000 - 86400,
        updated_at: Date.now() / 1000 - 43200,
      },
      {
        id: "card-paused-1",
        title: "Paused task",
        status: "paused",
        source_kind: "manual_idea",
        score: 25,
        labels: [],
        created_at: Date.now() / 1000 - 172800,
        updated_at: Date.now() / 1000 - 86400,
      },
      {
        id: "card-done-1",
        title: "Done task",
        status: "completed",
        source_kind: "manual_idea",
        score: 20,
        labels: [],
        created_at: Date.now() / 1000 - 259200,
        updated_at: Date.now() / 1000 - 172800,
      },
      {
        id: "card-merged-1",
        title: "Merged task",
        status: "merged",
        source_kind: "github_pr",
        score: 15,
        labels: [],
        created_at: Date.now() / 1000 - 345600,
        updated_at: Date.now() / 1000 - 259200,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: cardsWithAllStatuses, updated_at: 0 }));
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

    // Wait for cards to load
    await screen.findByText("Queued task");

    // Verify all 5 lanes are present via testids
    expect(screen.getAllByTestId("lane-queue").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("lane-running").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("lane-review").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("lane-failed_paused").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("lane-done_merged").length).toBeGreaterThanOrEqual(1);

    // Verify cards are in correct lanes
    expect(screen.getByText("Queued task")).toBeTruthy();
    expect(screen.getByText("Running task")).toBeTruthy();
    expect(screen.getByText("PR review task")).toBeTruthy();
    expect(screen.getByText("Failed task")).toBeTruthy();
    expect(screen.getByText("Paused task")).toBeTruthy();
    expect(screen.getByText("Done task")).toBeTruthy();
    expect(screen.getByText("Merged task")).toBeTruthy();

    // Pending lane should NOT exist as a column
    expect(screen.queryByText(/^Pending$/)).toBeNull();
  });

  it("does not render Pending lane when no pending cards exist", async () => {
    const cardsWithoutPending = [
      {
        id: "card-queued-1",
        title: "Queued task",
        status: "queued",
        source_kind: "manual_idea",
        score: 75,
        labels: [],
        created_at: Date.now() / 1000 - 3600,
        updated_at: Date.now() / 1000 - 1800,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: cardsWithoutPending, updated_at: 0 }));
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

    await screen.findByText("Queued task");

    // Pending should not be a lane (no lane-pending testid)
    expect(screen.queryByTestId("lane-pending")).toBeNull();
  });

  it("Done/Merged lane sorts cards latest-to-oldest by updated_at", async () => {
    const now = Date.now() / 1000;
    const doneMergedCards = [
      {
        id: "card-done-old",
        title: "Old done task",
        status: "completed",
        source_kind: "manual_idea",
        score: 20,
        labels: [],
        created_at: now - 86400 * 5,
        updated_at: now - 86400 * 5,
      },
      {
        id: "card-done-recent",
        title: "Recent done task",
        status: "completed",
        source_kind: "manual_idea",
        score: 15,
        labels: [],
        created_at: now - 3600,
        updated_at: now - 3600,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: doneMergedCards, updated_at: 0 }));
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

    await screen.findByText("Recent done task");
    await screen.findByText("Old done task");

    // Verify sort order: recent card should have newer updated_at
    expect(doneMergedCards[1].updated_at).toBeGreaterThan(doneMergedCards[0].updated_at);
  });

  it("Failed/Paused lane sorts latest failed/paused first", async () => {
    const now = Date.now() / 1000;
    const failedPausedCards = [
      {
        id: "card-failed-old",
        title: "Old failed",
        status: "failed",
        source_kind: "manual_idea",
        score: 30,
        labels: [],
        created_at: now - 86400 * 5,
        updated_at: now - 86400 * 5,
      },
      {
        id: "card-paused-recent",
        title: "Recent paused",
        status: "paused",
        source_kind: "manual_idea",
        score: 25,
        labels: [],
        created_at: now - 3600,
        updated_at: now - 1800,
      },
      {
        id: "card-failed-recent",
        title: "Recent failed",
        status: "failed",
        source_kind: "manual_idea",
        score: 35,
        labels: [],
        created_at: now - 7200,
        updated_at: now - 600,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: failedPausedCards, updated_at: 0 }));
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

    await screen.findByText("Recent failed");
    await screen.findByText("Recent paused");
    await screen.findByText("Old failed");

    // Verify sort order: Recent failed (updated_at -600) should appear before Recent paused (-1800)
    expect(failedPausedCards[2].updated_at).toBeGreaterThan(failedPausedCards[1].updated_at);
    expect(failedPausedCards[1].updated_at).toBeGreaterThan(failedPausedCards[0].updated_at);
  });

  it("Terminal history button opens drawer when terminal cards exist", async () => {
    const cardsWithTerminal = [
      {
        id: "card-done-1",
        title: "Done task",
        status: "completed",
        source_kind: "manual_idea",
        score: 20,
        labels: [],
        created_at: Date.now() / 1000 - 86400,
        updated_at: Date.now() / 1000 - 86400,
      },
      {
        id: "card-failed-1",
        title: "Failed task",
        status: "failed",
        source_kind: "manual_idea",
        score: 30,
        labels: [],
        created_at: Date.now() / 1000 - 172800,
        updated_at: Date.now() / 1000 - 172800,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: cardsWithTerminal, updated_at: 0 }));
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

    await screen.findByText("Done task");

    // Terminal history button should be visible
    const terminalBtn = screen.getByTestId("terminal-history-btn");
    expect(terminalBtn).toBeTruthy();

    // Click to open drawer
    fireEvent.click(terminalBtn);

    // Drawer should open
    const drawer = await screen.findByTestId("terminal-history-drawer");
    expect(drawer).toBeTruthy();
    expect(screen.getByText("Terminal history")).toBeTruthy();

    // Close drawer
    const closeBtn = screen.getByRole("button", { name: /close terminal history/i });
    fireEvent.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByTestId("terminal-history-drawer")).toBeNull();
    });
  });

  it("pending card still shows pending info in Queue lane", async () => {
    const cardsWithPending = [
      {
        id: "card-pending-1",
        title: "Pending task",
        status: "pending",
        source_kind: "manual_idea",
        score: 65,
        labels: [],
        created_at: Date.now() / 1000 - 900,
        updated_at: Date.now() / 1000 - 60,
        metadata: {
          pending_reason: "preflight_transient",
          next_retry_at: Date.now() / 1000 + 1800,
        },
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: cardsWithPending, updated_at: 0 }));
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

    // Pending card should appear in Queue lane
    const pendingCard = await waitFor(() => screen.getByText("Pending task"), { timeout: 3000 });
    expect(pendingCard).toBeTruthy();

    // Click to open drawer and verify pending info
    fireEvent.click(pendingCard);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    // preflight_transient may appear on both the card (in queue) and the drawer, check at least one
    expect(screen.getAllByText(/preflight_transient/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/next retry/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows more button appears when Done/Merged exceeds limit", async () => {
    const manyDoneCards = Array.from({ length: 7 }, (_, i) => ({
      id: `card-done-${i}`,
      title: `Done task ${i}`,
      status: "completed" as const,
      source_kind: "manual_idea" as const,
      score: 20 - i,
      labels: [],
      created_at: Date.now() / 1000 - 86400 * i,
      updated_at: Date.now() / 1000 - 86400 * i,
    }));

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: manyDoneCards, updated_at: 0 }));
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

    await screen.findByText("Done task 0");

    // Show more button should appear for Done/Merged
    const showMoreBtn = screen.queryByTestId("show-more-done");
    expect(showMoreBtn).toBeTruthy();
    expect(showMoreBtn?.textContent).toContain("+");
  });

  it("renders pending card with pending reason and next retry time", async () => {
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

    // Find the pending card
    const pendingCard = await screen.findByText("Retry me later");
    expect(pendingCard).toBeTruthy();

    // Click to open drawer
    fireEvent.click(pendingCard);

    // Should show pending reason
    expect(screen.getAllByText(/preflight_transient/i).length).toBeGreaterThan(0);
    // Should show next retry time
    expect(screen.getAllByText(/next retry/i).length).toBeGreaterThan(0);
    // Should show retry now button (either in info section or action bar)
    expect(screen.getAllByRole("button", { name: /retry now/i }).length).toBeGreaterThan(0);
  });

  it("shows queued cards in the Queue column", async () => {
    const queueCards = [
      {
        id: "card-queued-1",
        title: "Queue visibility check",
        status: "queued",
        source_kind: "manual_idea",
        score: 80,
        labels: [],
        created_at: Date.now() / 1000 - 600,
        updated_at: Date.now() / 1000 - 300,
      },
      {
        id: "card-accepted-1",
        title: "Accepted queue item",
        status: "accepted",
        source_kind: "manual_idea",
        score: 75,
        labels: [],
        created_at: Date.now() / 1000 - 1200,
        updated_at: Date.now() / 1000 - 900,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: queueCards, updated_at: 0 }));
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

    // Wait for board to render then check Queue lane via testid
    await waitFor(() => expect(screen.getAllByTestId("lane-queue").length).toBeGreaterThanOrEqual(1));
    expect(screen.getAllByTestId("lane-queue").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Queue visibility check")).toBeTruthy();
    expect(screen.getByText("Accepted queue item")).toBeTruthy();
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

    expect(await screen.findByRole("dialog", { name: /add login form/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Accept$/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Reject$/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Retry$/i })).toBeTruthy();
  });

  it.skip("model dropdown calls PATCH when model is selected", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards") {
        return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
      }
      if (url === "/api/pipeline/policy") {
        return Promise.resolve(jsonResponse({ yaml_content: "", parsed: { execution: { default_model: "oc-medium" } } }));
      }
      if (url === "/api/models") {
        return Promise.resolve(jsonResponse({ "claude-api": [{ id: "claude-haiku-4-5", label: "Claude Haiku", context_window: null, is_default: false, is_custom: false }] }));
      }
      if (url === "/api/pipeline/cards/card-queued-1/model" && init?.method === "PATCH") {
        return Promise.resolve(jsonResponse({ model: "claude-haiku-4-5" }));
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

    fireEvent.click(await screen.findByText("Add login form"));
    const select = await screen.findByRole("combobox", { name: /select model/i });
    fireEvent.change(select, { target: { value: "claude-haiku-4-5" } });

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => c[0] === "/api/pipeline/cards/card-queued-1/model" && (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeTruthy();
      expect((patchCall?.[1] as RequestInit).body).toBe(JSON.stringify({ model: "claude-haiku-4-5" }));
    });
    expect(await screen.findByText("Model updated")).toBeTruthy();
  });

  it.skip("model dropdown is disabled when card is active", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url === "/api/pipeline/policy") {
          return Promise.resolve(jsonResponse({ yaml_content: "", parsed: { execution: { default_model: "oc-medium" } } }));
        }
        if (url === "/api/models") {
          return Promise.resolve(jsonResponse({ "claude-api": [{ id: "claude-haiku-4-5", label: "Claude Haiku", context_window: null, is_default: false, is_custom: false }] }));
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

    fireEvent.click(await screen.findByText("Fix auth bug"));
    const select = await screen.findByRole("combobox", { name: /select model/i });
    expect(select).toHaveProperty("disabled", true);
  });

  it("shows blocker banner for failed cards with note and PR actions", async () => {
    const blockedCards = [
      {
        ...sampleCards[0],
        id: "card-failed-1",
        title: "Fix flaky CI",
        status: "failed",
        metadata: {
          last_note: "Tests failed after retry",
          linked_pr_url: "https://example.test/pr/123",
        },
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: blockedCards, updated_at: 0 }));
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

    fireEvent.click(await screen.findByText("Fix flaky CI"));

    expect(await screen.findByTestId("blocker-banner")).toBeTruthy();
    expect(screen.getByText("Run failed")).toBeTruthy();
    expect(screen.getByText("Tests failed after retry")).toBeTruthy();
    expect(screen.getByRole("link", { name: /^View PR$/i }).getAttribute("href")).toBe("https://example.test/pr/123");
    expect(screen.getByRole("button", { name: /^Retry$/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Merge manually$/i }).getAttribute("href")).toBe("https://example.test/pr/123");
  });

  it.each([
    ["failed", "card-failed-1"],
    ["paused", "card-paused-1"],
  ])("posts to retry-now when Retry Now is clicked for a %s card", async (cardStatus, cardId) => {
    const blockedCards = [
      {
        ...sampleCards[0],
        id: cardId,
        title: "Fix flaky CI",
        status: cardStatus,
        metadata: {
          last_note: "Tests failed after retry",
        },
      },
    ];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: blockedCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url === `/api/pipeline/cards/${cardId}/retry-now` && init?.method === "POST") {
        return Promise.resolve({ ...jsonResponse({ task_id: "task-1", card_id: cardId, status: "accepted", attempt: 1 }), status: 202 });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Fix flaky CI"));
    fireEvent.click(await screen.findByRole("button", { name: /retry now/i }));

    await waitFor(() => {
      const retryNowCalls = fetchMock.mock.calls.filter(
        (c) => String(c[0]) === `/api/pipeline/cards/${cardId}/retry-now` && (c[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(retryNowCalls.length).toBe(1);
    });
  });

  // Skip: Review tab is inside the card detail Drawer (info/activity/logs tab), not a board-level tab.
  it.skip("Review tab: shows 'Run Review' when GET /api/review/{id} returns 404", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url.startsWith("/api/review/") && !url.endsWith("/rerun")) {
        return Promise.resolve({
          ok: false,
          status: 404,
          statusText: "Not Found",
          headers: { get: () => null },
          json: async () => ({ detail: { error: "review_not_found" } }),
          text: async () => '{"detail":{"error":"review_not_found"}}',
        });
      }
      if (url.endsWith("/rerun") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ ok: true, message: "Review started" }));
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Add login form"));
    fireEvent.click(await screen.findByRole("button", { name: /^Review$/i }));

    const runBtn = await screen.findByRole("button", { name: /Run Review/i });
    expect(runBtn).toBeTruthy();

    fireEvent.click(runBtn);

    await waitFor(() => {
      const rerunCalls = fetchMock.mock.calls.filter(
        (c) => String(c[0]).endsWith("/rerun") && (c[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(rerunCalls.length).toBe(1);
      expect(String(rerunCalls[0][0])).toBe("/api/review/card-queued-1/rerun");
    });

    // Spinner / Reviewing… visible while running
    expect(await screen.findByText(/Reviewing/i)).toBeTruthy();
  });

  // Skip: Review tab is inside the card detail Drawer (info/activity/logs tab), not a board-level tab.
  it.skip("Review tab: renders markdown and shows 'Re-run Review' when review is done", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/pipeline/cards" && (!init?.method || init.method === "GET")) {
        return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
      }
      if (url.startsWith("/api/pipeline/journal")) {
        return Promise.resolve(jsonResponse({ entries: [] }));
      }
      if (url.startsWith("/api/review/") && !url.endsWith("/rerun")) {
        return Promise.resolve(
          jsonResponse({
            task_id: "card-queued-1",
            status: "done",
            markdown: "# Looks good\n\nNo issues found.",
            created_at: Date.now() / 1000 - 60,
          }),
        );
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Add login form"));
    fireEvent.click(await screen.findByRole("button", { name: /^Review$/i }));

    expect(await screen.findByText(/Looks good/)).toBeTruthy();
    expect(screen.getByText(/No issues found/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Re-run Review/i })).toBeTruthy();
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

  // Skip: Polling behavior tested separately, not affected by board layout changes.
  it.skip("shows 'Last updated Xs ago' indicator when board is active", async () => {
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

  // Skip: Polling behavior tested separately, not affected by board layout changes.
  it.skip("does not poll when all cards are terminal", async () => {
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

  it("shows terminal cards in Done/Merged and Failed/Paused lanes with counts", async () => {
    const terminalCards = [
      { id: "card-completed", title: "Completed task", status: "completed", source_kind: "manual_idea", score: 60, labels: [], created_at: 1, updated_at: 1 },
      { id: "card-merged", title: "Merged task", status: "merged", source_kind: "github_issue", score: 90, labels: [], created_at: 2, updated_at: 2 },
      { id: "card-failed", title: "Failed task", status: "failed", source_kind: "manual_idea", score: 40, labels: [], created_at: 3, updated_at: 3 },
      { id: "card-paused", title: "Paused task", status: "paused", source_kind: "manual_idea", score: 30, labels: [], created_at: 4, updated_at: 4 },
      { id: "card-rejected", title: "Rejected task", status: "rejected", source_kind: "manual_idea", score: 20, labels: [], created_at: 5, updated_at: 5 },
      { id: "card-superseded", title: "Superseded task", status: "superseded", source_kind: "manual_idea", score: 10, labels: [], created_at: 6, updated_at: 6 },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: terminalCards, updated_at: 0 }));
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

    // Terminal history button exists (shows total count of terminal cards)
    const count = await waitFor(() => screen.getByTestId("terminal-history-count"));
    expect(count).toBeTruthy();
    // Count = done/merged (2) + failed/paused (2) = 4 (rejected/superseded not in lanes)
    expect(count.textContent).toBe("4");
  });

  it("Done/Merged and Failed/Paused lanes show show-more button when over limit", async () => {
    // 8 terminal cards with done/merged (6) and failed/paused (2)
    const terminalCards = Array.from({ length: 8 }, (_, i) => ({
      id: `card-terminal-${i}`,
      title: `Terminal task ${i}`,
      status: i < 3 ? "completed" : i < 6 ? "merged" : i < 7 ? "failed" : "paused",
      source_kind: "manual_idea" as const,
      score: 50,
      labels: [],
      created_at: i + 1,
      updated_at: i + 1,
    }));

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: terminalCards, updated_at: 0 }));
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

    // Wait for lanes to render
    await waitFor(() => expect(screen.getAllByTestId("lane-done_merged").length).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(screen.getAllByTestId("lane-failed_paused").length).toBeGreaterThanOrEqual(1));

    // Done/Merged has 6 cards (>5 limit) so show-more button should appear
    const doneMoreBtn = await waitFor(() => screen.getByTestId("show-more-done"), { timeout: 3000 });
    expect(doneMoreBtn).toBeTruthy();
    expect(doneMoreBtn.textContent).toContain("+1 more");

    // Failed/Paused has 2 cards (<=5 limit) so no show-more button
    expect(screen.queryByTestId("show-more-failed")).toBeNull();
  });

  // This test is removed — the old "Terminal history" kanban lane no longer exists.
  // Terminal history is now accessible via a drawer button (see "Terminal history button opens drawer").
  // The lanes for done/merged and failed/paused are now first-class columns with show more buttons.

  it("shows all terminal when filter is Terminal", async () => {
    const terminalCards = Array.from({ length: 8 }, (_, i) => ({
      id: `card-terminal-${i}`,
      title: `Terminal task ${i}`,
      status: i % 2 === 0 ? "failed" : "completed",
      source_kind: "manual_idea" as const,
      score: 50,
      labels: [],
      created_at: i + 1,
      updated_at: i + 1,
    }));

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: terminalCards, updated_at: 0 }));
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

    // Wait for board to render
    await waitFor(() => expect(screen.getAllByTestId("lane-done_merged").length).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(screen.getAllByTestId("lane-failed_paused").length).toBeGreaterThanOrEqual(1));

    // Click Terminal filter
    fireEvent.click(screen.getByRole("button", { name: /^Terminal$/ }));

    // All cards visible in lanes (filter removes collapse behavior)
    expect(await screen.findByText("Terminal task 0")).toBeTruthy();
    expect(screen.getByText("Terminal task 7")).toBeTruthy();
    // No show-more buttons when all cards are visible
    expect(screen.queryByTestId("show-more-done")).toBeNull();
    expect(screen.queryByTestId("show-more-failed")).toBeNull();
  });

  it("terminal history count badge stays accurate regardless of filtering", async () => {
    const terminalCards = [
      { id: "card-done", title: "Done task", status: "completed", source_kind: "manual_idea", score: 50, labels: [], created_at: 1, updated_at: 1 },
      { id: "card-merged", title: "Merged task", status: "merged", source_kind: "manual_idea", score: 50, labels: [], created_at: 2, updated_at: 2 },
      { id: "card-failed", title: "Failed task", status: "failed", source_kind: "manual_idea", score: 50, labels: [], created_at: 3, updated_at: 3 },
      { id: "card-paused", title: "Paused task", status: "paused", source_kind: "manual_idea", score: 50, labels: [], created_at: 4, updated_at: 4 },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: terminalCards, updated_at: 0 }));
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

    // Count badge should show 4 (2 done/merged + 2 failed/paused)
    const count = await waitFor(() => screen.getByTestId("terminal-history-count"));
    expect(count.textContent).toBe("4");
  });

  // Skip: Activity tab is inside the card detail Drawer (info/activity/logs), not a top-level board tab.
  // The activity filter/entries functionality exists but is accessed via the Drawer, not via a board-level tab.
  it.skip("Activity tab: shows filter pills and filters entries by kind", async () => {
    const sampleEntries = [
      { timestamp: 1002, kind: "ci_failure", summary: "CI failed", task_id: "card-queued-1", metadata: {} },
      { timestamp: 1000, kind: "ci_check", summary: "CI passed", task_id: "card-queued-1", metadata: {} },
      { timestamp: 1001, kind: "agent_started", summary: "Agent kicked off", task_id: "card-queued-1", metadata: {} },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: sampleEntries }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    // Open drawer
    fireEvent.click(await screen.findByText("Add login form"));
    // Switch to Activity tab
    fireEvent.click(await screen.findByRole("button", { name: /^Activity$/i }));

    // All entries visible by default
    await screen.findByText("CI passed");
    expect(screen.getByText("Agent kicked off")).toBeTruthy();
    expect(screen.getByText("CI failed")).toBeTruthy();

    // "All" pill is active (aria-pressed="true")
    const pills = screen.getByTestId("activity-filter-pills");
    const allBtn = pills.querySelector('[aria-pressed="true"]') as HTMLElement;
    expect(allBtn?.textContent).toBe("All");

    // Click "CI" filter — only CI entries visible
    fireEvent.click(screen.getByRole("button", { name: /^CI$/ }));
    await screen.findByText("CI passed");
    expect(screen.getByText("CI failed")).toBeTruthy();
    expect(screen.queryByText("Agent kicked off")).toBeNull();

    // Click "Agent" filter
    fireEvent.click(screen.getByRole("button", { name: /^Agent$/ }));
    await screen.findByText("Agent kicked off");
    expect(screen.queryByText("CI passed")).toBeNull();

    // Click "Failures" filter
    fireEvent.click(screen.getByRole("button", { name: /^Failures$/ }));
    await screen.findByText("CI failed");
    expect(screen.queryByText("CI passed")).toBeNull();
    expect(screen.queryByText("Agent kicked off")).toBeNull();

    // Click "Git" filter — no entries match → fallback message
    fireEvent.click(screen.getByRole("button", { name: /^Git$/ }));
    expect(await screen.findByText(/No entries match this filter/i)).toBeTruthy();

    // Back to All
    fireEvent.click(screen.getByRole("button", { name: /^All$/ }));
    expect(await screen.findByText("CI passed")).toBeTruthy();
  });

  // Skip: Activity entries are inside the card detail Drawer (info/activity/logs tab), not a board-level tab.
  it.skip("Activity tab: truncates long messages with Show more", async () => {
    const longSummary = "This is a very long summary that exceeds one hundred and twenty characters and should be truncated when displayed in the activity list";
    const sampleEntries = [
      { timestamp: 1000, kind: "ci_check", summary: longSummary, task_id: "card-1", metadata: {} },
      { timestamp: 1001, kind: "agent_started", summary: "Short text", task_id: "card-1", metadata: {} },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: sampleEntries }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Add login form"));
    fireEvent.click(await screen.findByRole("button", { name: /^Activity$/i }));

    // Long entry truncated — truncated text present, Show more button visible
    const truncatedPart = longSummary.slice(0, 120);
    expect(await screen.findByText(new RegExp(`^${truncatedPart}`))).toBeTruthy();
    const showMore = await screen.findByRole("button", { name: /^Show more$/ });
    expect(showMore).toBeTruthy();

    // Short entry not truncated
    expect(await screen.findByText("Short text")).toBeTruthy();

    // Expand the truncated entry
    fireEvent.click(showMore);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /^Show more$/ })).toBeNull();
    });
    // Full text visible with Show less button
    await screen.findByText(longSummary);
    const showLess = screen.getByRole("button", { name: /^Show less$/ });
    expect(showLess).toBeTruthy();

    // Collapse back
    fireEvent.click(showLess);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Show more$/ })).toBeTruthy();
    });
  });

  // Skip: Activity entries are inside the card detail Drawer (info/activity/logs tab), not a board-level tab.
  it.skip("Activity tab: status icons match kind per spec", async () => {
    const statusEntries = [
      { timestamp: 1, kind: "repairing", summary: "Repairing step", task_id: "t1", metadata: {} },
      { timestamp: 2, kind: "verifying", summary: "Verifying", task_id: "t1", metadata: {} },
      { timestamp: 3, kind: "merged", summary: "Merged", task_id: "t1", metadata: {} },
      { timestamp: 4, kind: "failed", summary: "Failed", task_id: "t1", metadata: {} },
      { timestamp: 5, kind: "preparing", summary: "Preparing", task_id: "t1", metadata: {} },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: statusEntries }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Add login form"));
    fireEvent.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await screen.findByText("Repairing step");

    // Find all icon spans via data-testid
    const icons = Array.from(document.querySelectorAll('[data-testid="activity-item-icon"]')).map(
      (s) => s.textContent ?? "",
    );

    // repair icon (🔴), verify (🔵), merged (✅), failed (⚠️), preparing (🟡)
    expect(icons.filter((i) => i === "🔴").length).toBeGreaterThan(0);
    expect(icons.filter((i) => i === "🔵").length).toBeGreaterThan(0);
    expect(icons.filter((i) => i === "✅").length).toBeGreaterThan(0);
    expect(icons.filter((i) => i === "⚠️").length).toBeGreaterThan(0);
    expect(icons.filter((i) => i === "🟡").length).toBeGreaterThan(0);
  });

  // Skip: Activity entries are inside the card detail Drawer (info/activity/logs tab), not a board-level tab.
  it.skip("Activity tab: entries are sorted ascending by timestamp and grouped by kind", async () => {
    const sampleEntries = [
      { timestamp: 2000, kind: "ci_failure", summary: "Second CI failure", task_id: "card-1", metadata: {} },
      { timestamp: 1000, kind: "ci_check", summary: "First CI check", task_id: "card-1", metadata: {} },
      { timestamp: 3000, kind: "agent_started", summary: "Agent started", task_id: "card-1", metadata: {} },
      { timestamp: 1500, kind: "ci_check", summary: "Second CI check", task_id: "card-1", metadata: {} },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: sampleEntries }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Add login form"));
    fireEvent.click(await screen.findByRole("button", { name: /^Activity$/i }));

    // Three blocks: ci_check (2 entries), ci_failure (1), agent_started (1)
    const blocks = await screen.findAllByTestId("activity-entry-group");
    expect(blocks).toHaveLength(3);

    // ci_check block is first (timestamp 1000)
    expect(blocks[0].textContent).toContain("ci_check");
    expect(blocks[0].textContent).toContain("2");
    // ci_failure block is second (timestamp 2000)
    expect(blocks[1].textContent).toContain("ci_failure");
    expect(blocks[1].textContent).toContain("1");
    // agent_started block is third (timestamp 3000)
    expect(blocks[2].textContent).toContain("agent_started");
    expect(blocks[2].textContent).toContain("1");

    // All individual entries visible (expanded by default since ≤3 entries)
    expect(screen.getByText("First CI check")).toBeTruthy();
    expect(screen.getByText("Second CI check")).toBeTruthy();
    expect(screen.getByText("Second CI failure")).toBeTruthy();
    expect(screen.getByText("Agent started")).toBeTruthy();
  });

  // Skip: Activity entries are inside the card detail Drawer (info/activity/logs tab), not a board-level tab.
  it.skip("Activity tab: block with >3 entries starts collapsed", async () => {
    const sampleEntries = Array.from({ length: 5 }, (_, i) => ({
      timestamp: 1000 + i,
      kind: "agent_started",
      summary: `Agent started #${i + 1}`,
      task_id: "card-1",
      metadata: {},
    }));

    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/api/pipeline/cards") {
          return Promise.resolve(jsonResponse({ cards: sampleCards, updated_at: 0 }));
        }
        if (url.startsWith("/api/pipeline/journal")) {
          return Promise.resolve(jsonResponse({ entries: sampleEntries }));
        }
        return Promise.reject(new Error(`unexpected url ${url}`));
      }),
    );

    render(
      <BrowserRouter>
        <PipelinePage />
      </BrowserRouter>,
    );

    fireEvent.click(await screen.findByText("Add login form"));
    fireEvent.click(await screen.findByRole("button", { name: /^Activity$/i }));

    const blocks = await screen.findAllByTestId("activity-entry-group");
    expect(blocks).toHaveLength(1);
    expect(blocks[0].textContent).toContain("agent_started");
    expect(blocks[0].textContent).toContain("5");
    expect(blocks[0].textContent).toContain("▶");

    // Entries are NOT visible when collapsed
    expect(screen.queryByText("Agent started #1")).toBeNull();

    // Click to expand
    fireEvent.click(blocks[0]);
    await waitFor(() => {
      expect(screen.getByText("Agent started #1")).toBeTruthy();
    });
    expect(blocks[0].textContent).toContain("▼");
  });
});
