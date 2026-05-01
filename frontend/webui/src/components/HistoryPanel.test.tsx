import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import HistoryPanel, { formatRelativeTime, type HistorySession } from "./HistoryPanel";

function setupLocalStorageMock() {
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

function mockApiFetchWithSessions(sessions: HistorySession[]) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ sessions }),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("HistoryPanel", () => {
  it("renders 'No previous sessions' when empty", async () => {
    setupLocalStorageMock();
    mockApiFetchWithSessions([]);

    render(<HistoryPanel />);

    expect(await screen.findByText("No previous sessions")).toBeTruthy();
  });

  it("calls /api/history on mount", async () => {
    setupLocalStorageMock();
    const fetchMock = mockApiFetchWithSessions([]);

    render(<HistoryPanel />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe("/api/history");
  });

  it("truncates summaries to 60 chars", async () => {
    setupLocalStorageMock();
    mockApiFetchWithSessions([
      {
        session_id: "session-1",
        summary: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
        model: "test-model",
        message_count: 1,
        created_at: Date.now() / 1000,
      },
    ]);

    render(<HistoryPanel />);

    expect(
      await screen.findByText(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ12345678…",
      ),
    ).toBeTruthy();
  });

  it("formats relative time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-01T12:00:00Z"));

    expect(formatRelativeTime(Date.now() / 1000 - 30)).toBe("just now");
    expect(formatRelativeTime(Date.now() / 1000 - 5 * 60)).toBe("5m ago");
    expect(formatRelativeTime(Date.now() / 1000 - 2 * 60 * 60)).toBe("2h ago");
    expect(formatRelativeTime(Date.now() - 24 * 60 * 60 * 1000)).toBe("1d ago");

    vi.useRealTimers();
  });
});
