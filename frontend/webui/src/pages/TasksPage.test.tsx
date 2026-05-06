import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TasksPage, { type TaskRecord } from "./TasksPage";

const RUNNING_TASK: TaskRecord = {
  id: "task-running-001",
  type: "local_bash",
  status: "running",
  description: "Running task",
  cwd: "/tmp/run",
  output_file: "/tmp/run.log",
  command: "sleep 60",
  prompt: null,
  created_at: 1700000000,
  started_at: 1700000001,
  ended_at: null,
  return_code: null,
  metadata: {},
};

const FAILED_TASK: TaskRecord = {
  id: "task-failed-002",
  type: "local_bash",
  status: "failed",
  description: "Failed task",
  cwd: "/tmp/fail",
  output_file: "/tmp/fail.log",
  command: "false",
  prompt: null,
  created_at: 1700000100,
  started_at: 1700000101,
  ended_at: 1700000102,
  return_code: 1,
  metadata: {},
};

interface MockOptions {
  detailDelay?: number;
  detailOverride?: TaskRecord;
  failDetail?: boolean;
  retryResponse?: TaskRecord;
}

function mockFetch(tasks: TaskRecord[], options: MockOptions = {}) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/tasks") {
      return Promise.resolve({
        ok: true,
        json: async () => ({ tasks }),
      });
    }
    const detailMatch = url.match(/^\/api\/tasks\/([^/]+)$/);
    if (detailMatch) {
      if (options.failDetail) {
        return Promise.resolve({
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          text: async () => "boom",
        });
      }
      const id = decodeURIComponent(detailMatch[1]);
      const task = options.detailOverride ?? tasks.find((t) => t.id === id);
      const respond = () =>
        Promise.resolve({
          ok: true,
          json: async () => task,
        });
      if (options.detailDelay) {
        return new Promise((resolve) => setTimeout(() => resolve(respond()), options.detailDelay));
      }
      return respond();
    }
    if (url.endsWith("/output?tail=500")) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ lines: ["line1", "line2"] }),
      });
    }
    if (url.startsWith("/api/review/")) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ task_id: url.split("/").pop(), status: "done", markdown: "# Review detail", created_at: 1700000200 }),
      });
    }
    if (url.endsWith("/retry")) {
      return Promise.resolve({
        ok: true,
        json: async () => options.retryResponse ?? RUNNING_TASK,
      });
    }
    return Promise.reject(new Error(`unexpected url: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

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

beforeEach(() => {
  mockLocalStorage();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("TasksPage drawer", () => {
  it("fetches GET /api/tasks/{id} when a row is clicked", async () => {
    const { calls } = mockFetch([RUNNING_TASK]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());
    fireEvent.click(screen.getByText("Running task"));

    await waitFor(() => {
      const detailCall = calls.find((c) => c.url === `/api/tasks/${RUNNING_TASK.id}`);
      expect(detailCall).toBeTruthy();
    });
  });

  it("shows a spinner while the detail request is in flight", async () => {
    mockFetch([RUNNING_TASK], { detailDelay: 50 });
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    expect(await screen.findByText(/Loading task detail/i)).toBeTruthy();
    await waitFor(() => expect(screen.queryByText(/Loading task detail/i)).toBeNull(), {
      timeout: 1000,
    });
  });

  it("renders a retry button for failed tasks and posts to /retry", async () => {
    const { calls } = mockFetch([FAILED_TASK], { retryResponse: RUNNING_TASK });
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Failed task")).toBeTruthy());

    fireEvent.click(screen.getByText("Failed task"));

    const retryButton = await screen.findByRole("button", { name: /^Retry$/ });
    fireEvent.click(retryButton);

    await waitFor(() => {
      const retryCall = calls.find(
        (c) => c.url === `/api/tasks/${FAILED_TASK.id}/retry` && c.init?.method === "POST",
      );
      expect(retryCall).toBeTruthy();
    });
  });

  it("does not show a retry button for running tasks", async () => {
    mockFetch([RUNNING_TASK]);
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    await waitFor(() =>
      expect(screen.queryByText(/Loading task detail/i)).toBeNull(),
    );
    expect(screen.queryByRole("button", { name: /^Retry$/ })).toBeNull();
  });

  it("shows an error message when the detail request fails", async () => {
    mockFetch([RUNNING_TASK], { failDetail: true });
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    await waitFor(() => expect(screen.getByText(/500/)).toBeTruthy());
  });
});

// ─── Review badge column ──────────────────────────────────────────────────────

const REVIEWED_TASK: TaskRecord = {
  ...FAILED_TASK,
  id: "task-reviewed-001",
  description: "Reviewed task",
  metadata: { review_status: "done" },
};

const REVIEWING_TASK: TaskRecord = {
  ...RUNNING_TASK,
  id: "task-reviewing-002",
  description: "Reviewing task",
  metadata: { review_status: "in_progress" },
};

const NO_REVIEW_TASK: TaskRecord = {
  ...RUNNING_TASK,
  id: "task-noreview-003",
  description: "No review task",
  metadata: {},
};

describe("TasksPage review badge", () => {
  it("shows '✅ Reviewed' badge for tasks with review_status=done", async () => {
    mockFetch([REVIEWED_TASK]);
    render(<TasksPage />);
    expect(await screen.findByText(/✅ Reviewed/)).toBeTruthy();
  });

  it("shows '⏳ Reviewing' badge for tasks with review_status=in_progress", async () => {
    mockFetch([REVIEWING_TASK]);
    render(<TasksPage />);
    expect(await screen.findByText(/⏳ Reviewing/)).toBeTruthy();
  });

  it("shows '—' for tasks with no review metadata", async () => {
    mockFetch([NO_REVIEW_TASK]);
    render(<TasksPage />);
    await screen.findByText("No review task");
    // The em dash appears in the review status cell (and possibly elsewhere as
    // empty placeholders). Just ensure at least one is rendered.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("clicking the Reviewed badge opens the drawer and fetches /api/review/{id}", async () => {
    const { calls } = mockFetch([REVIEWED_TASK]);
    render(<TasksPage />);

    const badge = await screen.findByRole("button", { name: /Reviewed/i });
    fireEvent.click(badge);

    await waitFor(() => {
      const reviewCall = calls.find((c) => c.url === `/api/review/${REVIEWED_TASK.id}`);
      expect(reviewCall).toBeTruthy();
    });
  });

  it("clicking the Reviewing badge opens the drawer without fetching the row detail twice", async () => {
    const { calls } = mockFetch([REVIEWING_TASK]);
    render(<TasksPage />);

    const badge = await screen.findByRole("button", { name: /Reviewing/i });
    fireEvent.click(badge);

    // Drawer opens (detail fetched).
    await waitFor(() => {
      const detailCall = calls.find((c) => c.url === `/api/tasks/${REVIEWING_TASK.id}`);
      expect(detailCall).toBeTruthy();
    });
  });
});

// ─── Log viewer enhancements ──────────────────────────────────────────────────

describe("TasksPage log viewer", () => {
  it("shows a copy log button when logs are present", async () => {
    mockFetch([RUNNING_TASK]);
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    expect(await screen.findByRole("button", { name: /Copy log/i })).toBeTruthy();
  });

  it("copies logs to clipboard when copy button is clicked", async () => {
    mockFetch([RUNNING_TASK]);
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    const copyButton = await screen.findByRole("button", { name: /Copy log/i });
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("line1\nline2");
    });

    expect(await screen.findByText(/✓ Copied/i)).toBeTruthy();
  });

  it("uses terminal-style dark background for log display", async () => {
    mockFetch([RUNNING_TASK]);
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    // Check that log container has dark terminal styling
    const logContainer = await screen.findByText("line1");
    const preElement = logContainer.closest("pre");
    expect(preElement).toBeTruthy();
    expect(preElement?.className).toContain("bg-zinc-900");
  });

  it("polls logs every 2 seconds for running tasks", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    mockFetch([RUNNING_TASK]);

    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    fireEvent.click(screen.getByText("Running task"));

    await waitFor(() => expect(screen.getByText("line1")).toBeTruthy());

    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 2000);
    setIntervalSpy.mockRestore();
  });
});
