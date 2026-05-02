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
