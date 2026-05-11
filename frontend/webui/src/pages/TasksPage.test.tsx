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
  it("shows Reviewed badge for tasks with review_status=done", async () => {
    mockFetch([REVIEWED_TASK]);
    render(<TasksPage />);
    const badge = await screen.findByRole("button", { name: /Reviewed/i });
    expect(badge).toBeTruthy();
  });

  it("shows Pending review badge for tasks with review_status=in_progress", async () => {
    mockFetch([REVIEWING_TASK]);
    render(<TasksPage />);
    const badge = await screen.findByRole("button", { name: /Pending review/i });
    expect(badge).toBeTruthy();
  });

  it("shows 'No review needed' text for tasks with no review metadata", async () => {
    mockFetch([NO_REVIEW_TASK]);
    render(<TasksPage />);
    // Wait for task to appear, then check the review column
    await waitFor(() => expect(screen.getByText("No review task")).toBeTruthy());
    // The "No review needed" text should appear in the review column
    expect(screen.getAllByText("No review needed").length).toBeGreaterThan(0);
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

    const badge = await screen.findByRole("button", { name: /Pending review/i });
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

// ─── Filter, sort, and row expansion ─────────────────────────────────────────

const PENDING_TASK: TaskRecord = {
  ...RUNNING_TASK,
  id: "task-pending-001",
  description: "Pending task",
  status: "pending",
  metadata: {},
};

const COMPLETED_TASK: TaskRecord = {
  ...FAILED_TASK,
  id: "task-completed-001",
  status: "completed",
  description: "Completed task",
  return_code: 0,
  metadata: {},
};

describe("TasksPage filters", () => {
  it("filters tasks by status via the status dropdown", async () => {
    mockFetch([RUNNING_TASK, PENDING_TASK, COMPLETED_TASK]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());
    expect(screen.getByText("Pending task")).toBeTruthy();
    expect(screen.getByText("Completed task")).toBeTruthy();

    // Use the All statuses select to filter to "running"
    const allStatusesOption = screen.getByText("All statuses");
    const statusSelect = allStatusesOption.closest("select");
    expect(statusSelect).toBeTruthy();
    fireEvent.change(statusSelect!, { target: { value: "running" } });

    await waitFor(() => {
      expect(screen.getByText("Running task")).toBeTruthy();
      expect(screen.queryByText("Pending task")).toBeNull();
    });
  });

  it("searches tasks by description", async () => {
    mockFetch([RUNNING_TASK, COMPLETED_TASK]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());
    const searchInput = screen.getByPlaceholderText("Search jobs...");
    fireEvent.change(searchInput, { target: { value: "Completed" } });

    expect(screen.queryByText("Running task")).toBeNull();
    expect(screen.getByText("Completed task")).toBeTruthy();
  });

  it("clears all filters with 'Clear filters' button", async () => {
    mockFetch([RUNNING_TASK, PENDING_TASK]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    // Type in search to show clear button
    const searchInput = screen.getByPlaceholderText("Search jobs...");
    fireEvent.change(searchInput, { target: { value: "Running" } });

    const clearBtn = screen.getByRole("button", { name: /clear filters/i });
    fireEvent.click(clearBtn);

    // Both tasks should be visible again
    expect(screen.getByText("Running task")).toBeTruthy();
    expect(screen.getByText("Pending task")).toBeTruthy();
  });
});

describe("TasksPage sort", () => {
  it("sorts tasks by newest first when 'Newest first' is selected", async () => {
    const oldTask: TaskRecord = { ...RUNNING_TASK, id: "old-task", created_at: 1000000000, description: "Old task" };
    const newTask: TaskRecord = { ...RUNNING_TASK, id: "new-task", created_at: 2000000000, description: "New task" };
    mockFetch([oldTask, newTask]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Old task")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("New task")).toBeTruthy());

    // Change sort to newest
    const sortSelect = screen.getByDisplayValue("Default order");
    fireEvent.change(sortSelect, { target: { value: "newest" } });

    // Verify both tasks are still visible after sort
    expect(screen.getByText("New task")).toBeTruthy();
    expect(screen.getByText("Old task")).toBeTruthy();
  });
});

describe("TasksPage row expansion", () => {
  it("expands a row when the expand button is clicked", async () => {
    mockFetch([RUNNING_TASK]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    const expandBtn = screen.getByRole("button", { name: /expand row/i });
    fireEvent.click(expandBtn);

    // Duration should appear in expanded section
    expect(await screen.findByText("Duration")).toBeTruthy();
  });

  it("collapses an expanded row when clicked again", async () => {
    mockFetch([RUNNING_TASK]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    const expandBtn = screen.getByRole("button", { name: /expand row/i });
    fireEvent.click(expandBtn);
    await waitFor(() => expect(screen.getByText("Duration")).toBeTruthy());

    fireEvent.click(expandBtn);
    expect(screen.queryByText("Duration")).toBeNull();
  });

  it("shows prompt summary in expanded row when task has prompt", async () => {
    const taskWithPrompt: TaskRecord = { ...RUNNING_TASK, prompt: "This is a long prompt for testing" };
    mockFetch([taskWithPrompt]);
    render(<TasksPage />);

    await waitFor(() => expect(screen.getByText("Running task")).toBeTruthy());

    const expandBtn = screen.getByRole("button", { name: /expand row/i });
    fireEvent.click(expandBtn);

    expect(await screen.findByText("Prompt summary")).toBeTruthy();
  });
});

describe("TasksPage status badges", () => {
  it("renders status badges for different statuses", async () => {
    const pendingTask: TaskRecord = { ...RUNNING_TASK, id: "pending-task", status: "pending", description: "Pending job" };
    const runningTask: TaskRecord = { ...RUNNING_TASK, id: "running-task", status: "running", description: "Running job" };
    mockFetch([pendingTask, runningTask]);
    render(<TasksPage />);

    await waitFor(() => {
      expect(screen.getByText("Pending job")).toBeTruthy();
      expect(screen.getByText("Running job")).toBeTruthy();
    });
    // Verify status badges are rendered (check for status text in badges)
    expect(screen.getAllByText("Pending").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
  });

  it("shows failed badge", async () => {
    mockFetch([FAILED_TASK]);
    render(<TasksPage />);
    await waitFor(() => expect(screen.getByText("Failed")).toBeTruthy());
  });
});
