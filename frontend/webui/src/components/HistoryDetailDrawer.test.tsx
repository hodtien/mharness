import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import HistoryDetailDrawer from "./HistoryDetailDrawer";
import type { HistorySession } from "./HistoryPanel";

const SESSION: HistorySession = {
  session_id: "sess-abc",
  summary: "Fix authentication bug",
  model: "claude-sonnet",
  message_count: 4,
  created_at: Date.now() / 1000 - 3600,
};

const DETAIL_RESPONSE = {
  session_id: "sess-abc",
  model: "claude-sonnet",
  cwd: "/home/user/project",
  messages: [
    {
      role: "user",
      content: [{ type: "text", text: "Hello, can you help me?" }],
    },
    {
      role: "assistant",
      content: [{ type: "text", text: "Of course! What do you need?" }],
    },
    {
      role: "user",
      content: [{ type: "text", text: "Fix the auth bug" }],
    },
    {
      role: "assistant",
      content: [{ type: "text", text: "Sure, let me look at that." }],
    },
  ],
};

function mockFetch(detailResponse: object | null = DETAIL_RESPONSE) {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    if (url === `/api/history/${SESSION.session_id}`) {
      if (detailResponse === null) {
        return Promise.resolve({
          ok: false,
          status: 404,
          statusText: "Not Found",
          text: async () => "Not Found",
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => detailResponse,
      });
    }
    if (url === "/api/sessions") {
      return Promise.resolve({
        ok: true,
        json: async () => ({ session_id: "new-sess-xyz" }),
      });
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockLocalStorage() {
  let store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  });
}

function renderDrawer(session: HistorySession | null, onClose = vi.fn(), onResume = vi.fn()) {
  return render(
    <BrowserRouter>
      <HistoryDetailDrawer session={session} onClose={onClose} onResume={onResume} />
    </BrowserRouter>,
  );
}

describe("HistoryDetailDrawer", () => {
  beforeEach(() => {
    mockLocalStorage();
  });

  it("renders nothing when session is null", () => {
    mockFetch();
    const { container } = renderDrawer(null);
    expect(container.firstChild).toBeNull();
  });

  it("renders drawer with session summary when session is provided", async () => {
    mockFetch();
    renderDrawer(SESSION);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Fix authentication bug")).toBeTruthy();
  });

  it("fetches GET /api/history/{id} on open", async () => {
    const fetchMock = mockFetch();
    renderDrawer(SESSION);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes(`/api/history/${SESSION.session_id}`),
      );
      expect(call).toBeTruthy();
    });
  });

  it("shows loading state initially", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    renderDrawer(SESSION);
    expect(screen.getByRole("status", { name: /loading/i })).toBeTruthy();
  });

  it("renders user messages with distinct styling", async () => {
    mockFetch();
    renderDrawer(SESSION);
    await waitFor(() => {
      expect(screen.getByText("Hello, can you help me?")).toBeTruthy();
    });
    const userMsgs = screen.getAllByTestId("msg-user");
    expect(userMsgs.length).toBeGreaterThan(0);
  });

  it("renders assistant messages with distinct styling", async () => {
    mockFetch();
    renderDrawer(SESSION);
    await waitFor(() => {
      expect(screen.getByText("Of course! What do you need?")).toBeTruthy();
    });
    const assistantMsgs = screen.getAllByTestId("msg-assistant");
    expect(assistantMsgs.length).toBeGreaterThan(0);
  });

  it("shows error state when API fails", async () => {
    mockFetch(null);
    renderDrawer(SESSION);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
  });

  it("closes drawer on backdrop click", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const onClose = vi.fn();
    renderDrawer(SESSION, onClose);
    const backdrop = screen.getByTestId("drawer-backdrop");
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes drawer on Escape key", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const onClose = vi.fn();
    renderDrawer(SESSION, onClose);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes drawer on X button click", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const onClose = vi.fn();
    renderDrawer(SESSION, onClose);
    const closeBtn = screen.getByRole("button", { name: /close/i });
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls POST /api/sessions with resume_id on Resume click", async () => {
    const fetchMock = mockFetch();
    const onResume = vi.fn();
    renderDrawer(SESSION, vi.fn(), onResume);

    await waitFor(() => {
      expect(screen.getByText("Of course! What do you need?")).toBeTruthy();
    });

    const resumeBtn = screen.getByRole("button", { name: /resume session/i });
    fireEvent.click(resumeBtn);

    await waitFor(() => {
      const sessionCall = fetchMock.mock.calls.find((c) => c[0] === "/api/sessions");
      expect(sessionCall).toBeTruthy();
      const [, init] = sessionCall as [string, RequestInit | undefined];
      expect(init?.method).toBe("POST");
      const body = JSON.parse(String(init?.body ?? "{}"));
      expect(body).toEqual({ resume_id: SESSION.session_id });
    });
  });

  it("calls onResume with new session id and resume id after Resume click", async () => {
    mockFetch();
    const onResume = vi.fn();
    renderDrawer(SESSION, vi.fn(), onResume);

    await waitFor(() => {
      expect(screen.getByText("Of course! What do you need?")).toBeTruthy();
    });

    const resumeBtn = screen.getByRole("button", { name: /resume session/i });
    fireEvent.click(resumeBtn);

    await waitFor(() => {
      expect(onResume).toHaveBeenCalledWith("new-sess-xyz", SESSION.session_id);
    });
  });
});
