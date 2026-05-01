import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import HistoryPage from "./HistoryPage";
import type { HistorySession } from "./HistoryPanel";

function mockApiFetchWithSessions(sessions: HistorySession[]) {
  let callCount = 0;
  const fetchMock = vi.fn((url: string) => {
    if (url === "/api/history") {
      return Promise.resolve({
        ok: true,
        json: async () => ({ sessions }),
      });
    }
    if (url === "/api/sessions" && callCount === 0) {
      callCount++;
      return Promise.resolve({
        ok: true,
        json: async () => ({ session_id: "new-session-123" }),
      });
    }
    return Promise.reject(new Error("unexpected url"));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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

describe("HistoryPage", () => {
  it("renders HistoryPanel", async () => {
    mockLocalStorage();
    mockApiFetchWithSessions([]);

    render(
      <BrowserRouter>
        <HistoryPage onResume={vi.fn()} />
      </BrowserRouter>,
    );

    expect(screen.getByRole("region", { name: /history/i })).toBeTruthy();
  });

  it("calls POST /api/sessions with resume_id on Resume click", async () => {
    mockLocalStorage();
    const fetchMock = mockApiFetchWithSessions([
      {
        session_id: "old-session-456",
        summary: "Fix bug in auth",
        model: "claude-sonnet",
        message_count: 12,
        created_at: Date.now() / 1000,
      },
    ]);

    const onResume = vi.fn();
    render(
      <BrowserRouter>
        <HistoryPage onResume={onResume} />
      </BrowserRouter>,
    );

    const resumeBtn = await screen.findByRole("button", { name: /^Resume$/i });
    fireEvent.click(resumeBtn);

    await waitFor(() => {
      expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/sessions");
      expect(fetchMock.mock.calls.at(-1)?.[1]?.method).toBe("POST");
      const body = JSON.parse(fetchMock.mock.calls.at(-1)?.[1]?.body ?? "{}");
      expect(body).toEqual({ resume_id: "old-session-456" });
    });
  });

  it("calls onResume and navigates to /chat on Resume click", async () => {
    mockLocalStorage();
    mockApiFetchWithSessions([
      {
        session_id: "old-session-456",
        summary: "Fix bug in auth",
        model: "claude-sonnet",
        message_count: 12,
        created_at: Date.now() / 1000,
      },
    ]);

    const onResume = vi.fn();
    render(
      <BrowserRouter>
        <HistoryPage onResume={onResume} />
      </BrowserRouter>,
    );

    const resumeBtn = await screen.findByRole("button", { name: /^Resume$/i });
    fireEvent.click(resumeBtn);

    await waitFor(() => {
      expect(onResume).toHaveBeenCalledWith("new-session-123", "old-session-456");
      expect(window.location.pathname).toBe("/chat");
    });
  });
});
