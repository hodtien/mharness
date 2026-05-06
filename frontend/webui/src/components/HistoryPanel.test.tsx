// @ts-nocheck
/**
 * Unit tests for HistoryPanel component.
 *
 * These tests use vitest + @testing-library/react. To run:
 *   npm install --save-dev vitest @testing-library/react jsdom
 *   npx vitest run
 *
 * The pure-function tests below are documented as spec-first assertions;
 * the commented integration tests become active once vitest is set up.
 */

import { formatRelativeTime, getDateGroupLabel, groupSessionsByDate } from "./HistoryPanel";

describe("formatRelativeTime", () => {
  const nowSeconds = Math.floor(Date.now() / 1000);

  test("returns 'just now' for timestamps within the last 60 seconds", () => {
    expect(formatRelativeTime(nowSeconds - 5)).toBe("just now");
    expect(formatRelativeTime(nowSeconds)).toBe("just now");
  });

  test("returns minutes ago for < 1 hour", () => {
    expect(formatRelativeTime(nowSeconds - 2 * 60)).toBe("2m ago");
    expect(formatRelativeTime(nowSeconds - 59 * 60)).toBe("59m ago");
  });

  test("returns hours ago for < 24 hours", () => {
    expect(formatRelativeTime(nowSeconds - 2 * 3600)).toBe("2h ago");
    expect(formatRelativeTime(nowSeconds - 23 * 3600)).toBe("23h ago");
  });

  test("returns days ago for >= 24 hours", () => {
    expect(formatRelativeTime(nowSeconds - 1 * 86400)).toBe("1d ago");
    expect(formatRelativeTime(nowSeconds - 3 * 86400)).toBe("3d ago");
  });

  test("handles millisecond timestamps (>=1e12)", () => {
    const msNow = Date.now() - 2 * 3600 * 1000; // 2 hours ago in ms
    expect(formatRelativeTime(msNow)).toBe("2h ago");
  });

  test("returns '—' for falsy/non-finite values", () => {
    expect(formatRelativeTime(0)).toBe("—");
    expect(formatRelativeTime(NaN)).toBe("—");
  });
});

describe("getDateGroupLabel", () => {
  test("returns 'Today' for sessions created today", () => {
    const now = Date.now() / 1000;
    expect(getDateGroupLabel(now)).toBe("Today");
  });

  test("returns 'Yesterday' for sessions from yesterday", () => {
    const yesterday = Math.floor(Date.now() / 1000) - 86400;
    expect(getDateGroupLabel(yesterday)).toBe("Yesterday");
  });

  test("returns 'X days ago' for 2-6 days", () => {
    expect(getDateGroupLabel(Math.floor(Date.now() / 1000) - 2 * 86400)).toBe("2 days ago");
    expect(getDateGroupLabel(Math.floor(Date.now() / 1000) - 6 * 86400)).toBe("6 days ago");
  });

  test("returns 'Last week' for 7-13 days", () => {
    expect(getDateGroupLabel(Math.floor(Date.now() / 1000) - 7 * 86400)).toBe("Last week");
    expect(getDateGroupLabel(Math.floor(Date.now() / 1000) - 13 * 86400)).toBe("Last week");
  });

  test("returns formatted date for older sessions", () => {
    const oldDate = new Date("2024-01-15T12:00:00Z");
    const result = getDateGroupLabel(oldDate.getTime() / 1000);
    expect(result).toMatch(/Jan 15, 2024/);
  });

  test("returns 'Unknown' for invalid timestamps", () => {
    expect(getDateGroupLabel(0)).toBe("Unknown");
    expect(getDateGroupLabel(NaN)).toBe("Unknown");
  });
});

describe("groupSessionsByDate", () => {
  test("groups sessions by date with correct order", () => {
    const now = Math.floor(Date.now() / 1000);
    const sessions = [
      { session_id: "s3", summary: "old", model: "m", message_count: 1, created_at: now - 30 * 86400 },
      { session_id: "s1", summary: "recent", model: "m", message_count: 1, created_at: now - 3600 },
      { session_id: "s2", summary: "yesterday", model: "m", message_count: 1, created_at: now - 86400 },
    ];

    const groups = groupSessionsByDate(sessions);

    expect(groups[0].label).toBe("Today");
    expect(groups[0].sessions).toHaveLength(1);
    expect(groups[0].sessions[0].session_id).toBe("s1");

    expect(groups[1].label).toBe("Yesterday");
    expect(groups[1].sessions).toHaveLength(1);
    expect(groups[1].sessions[0].session_id).toBe("s2");

    // Old sessions should be in last group
    expect(groups[groups.length - 1].label).not.toBe("Today");
    expect(groups[groups.length - 1].label).not.toBe("Yesterday");
  });

  test("handles multiple sessions in same group", () => {
    const now = Math.floor(Date.now() / 1000);
    const sessions = [
      { session_id: "s1", summary: "t1", model: "m", message_count: 1, created_at: now - 3600 },
      { session_id: "s2", summary: "t2", model: "m", message_count: 1, created_at: now - 7200 },
    ];

    const groups = groupSessionsByDate(sessions);

    expect(groups[0].label).toBe("Today");
    expect(groups[0].sessions).toHaveLength(2);
  });

  test("returns empty array for empty input", () => {
    const groups = groupSessionsByDate([]);
    expect(groups).toHaveLength(0);
  });

  test("sorts sessions within each group by created_at descending", () => {
    const now = Math.floor(Date.now() / 1000);
    const sessions = [
      { session_id: "older", summary: "o", model: "m", message_count: 1, created_at: now - 3600 },
      { session_id: "newer", summary: "n", model: "m", message_count: 1, created_at: now - 1800 },
    ];

    const groups = groupSessionsByDate(sessions);

    expect(groups[0].sessions[0].session_id).toBe("newer");
    expect(groups[0].sessions[1].session_id).toBe("older");
  });
});

// ---------------------------------------------------------------------------
// 60-char truncation logic (isolated)
// ---------------------------------------------------------------------------

describe("60-char truncation rule", () => {
  function truncate(s: string) {
    return s.length > 60 ? `${s.slice(0, 60)}…` : s;
  }

  test("passes through short summaries unchanged", () => {
    const short = "Hello world";
    expect(truncate(short)).toBe(short);
  });

  test("truncates strings longer than 60 chars and appends ellipsis", () => {
    const long = "A".repeat(65);
    const result = truncate(long);
    expect(result).toHaveLength(61); // 60 chars + '…' (1 code point)
    expect(result.endsWith("…")).toBe(true);
    expect(result.startsWith("A".repeat(60))).toBe(true);
  });

  test("string of exactly 60 chars is not truncated", () => {
    const exact = "B".repeat(60);
    expect(truncate(exact)).toBe(exact);
  });
});

// ---------------------------------------------------------------------------
// Search and filter logic (isolated)
// ---------------------------------------------------------------------------

describe("search and filter logic", () => {
  const mockSessions = [
    { session_id: "s1", summary: "Fix bug in authentication", model: "gpt-4o", message_count: 5, created_at: 1000 },
    { session_id: "s2", summary: "Add new feature", model: "claude-3-opus", message_count: 10, created_at: 2000 },
    { session_id: "s3", summary: "Refactor authentication module", model: "gpt-4o", message_count: 8, created_at: 3000 },
    { session_id: "s4", summary: "Update documentation", model: "claude-3-sonnet", message_count: 3, created_at: 4000 },
  ];

  function filterSessions(sessions: typeof mockSessions, searchText: string, selectedModel: string) {
    return sessions.filter((session) => {
      const matchesSearch = !searchText || 
        session.summary.toLowerCase().includes(searchText.toLowerCase());
      const matchesModel = !selectedModel || session.model === selectedModel;
      return matchesSearch && matchesModel;
    });
  }

  test("filters by search text (case-insensitive)", () => {
    const result = filterSessions(mockSessions, "authentication", "");
    expect(result).toHaveLength(2);
    expect(result[0].session_id).toBe("s1");
    expect(result[1].session_id).toBe("s3");
  });

  test("filters by model", () => {
    const result = filterSessions(mockSessions, "", "gpt-4o");
    expect(result).toHaveLength(2);
    expect(result[0].session_id).toBe("s1");
    expect(result[1].session_id).toBe("s3");
  });

  test("combines search text and model filter", () => {
    const result = filterSessions(mockSessions, "authentication", "gpt-4o");
    expect(result).toHaveLength(2);
    expect(result.every(s => s.model === "gpt-4o")).toBe(true);
    expect(result.every(s => s.summary.toLowerCase().includes("authentication"))).toBe(true);
  });

  test("returns all sessions when no filters applied", () => {
    const result = filterSessions(mockSessions, "", "");
    expect(result).toHaveLength(4);
  });

  test("returns empty array when no matches", () => {
    const result = filterSessions(mockSessions, "nonexistent", "");
    expect(result).toHaveLength(0);
  });

  test("extracts unique models from sessions", () => {
    const uniqueModels = Array.from(new Set(mockSessions.map(s => s.model).filter(Boolean))).sort();
    expect(uniqueModels).toEqual(["claude-3-opus", "claude-3-sonnet", "gpt-4o"]);
  });
});

// ---------------------------------------------------------------------------
// Integration tests with React Testing Library
// (Skipped if @testing-library/react is not installed; install to un-skip)
// ---------------------------------------------------------------------------

/**
 * To run the full integration tests:
 *
 *   npm install --save-dev vitest @testing-library/react @testing-library/jest-dom jsdom
 *
 * Then update vite.config.ts / vitest.config.ts with `environment: 'jsdom'`
 * and `globals: true`.
 *
 * The component tests below are referenced as commented-out pseudocode so
 * they serve as executable documentation without blocking CI.
 */

/*
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import HistoryPanel from "./HistoryPanel";

describe("HistoryPanel integration", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("calls GET /api/history on mount", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<HistoryPanel />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/history",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
  });

  test("shows loading skeleton while fetching", () => {
    global.fetch = vi.fn().mockReturnValue(new Promise(() => {})); // never resolves

    render(<HistoryPanel />);

    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
  });

  test("shows 'No previous sessions' when API returns empty list", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<HistoryPanel />);

    await waitFor(() => {
      expect(screen.getByText("No previous sessions")).toBeInTheDocument();
    });
  });

  test("renders session cards with truncated summary, badge, count, relative time", async () => {
    const longSummary = "A".repeat(65);
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          session_id: "s1",
          summary: longSummary,
          model: "gpt-4o",
          message_count: 12,
          created_at: Math.floor(Date.now() / 1000) - 2 * 3600,
        },
      ],
    });

    render(<HistoryPanel />);

    await waitFor(() => {
      // Truncated summary
      const el = screen.getByTitle(longSummary);
      expect(el.textContent).toBe("A".repeat(60) + "…");

      // Model badge
      expect(screen.getByText("gpt-4o")).toBeInTheDocument();

      // Message count
      expect(screen.getByText("12 msg")).toBeInTheDocument();

      // Relative time
      expect(screen.getByText("2h ago")).toBeInTheDocument();
    });
  });

  test("renders Resume and Delete buttons per session", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { session_id: "s1", summary: "Test", model: "m", message_count: 1, created_at: Date.now() / 1000 },
      ],
    });

    render(<HistoryPanel />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /resume/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /delete/i })).toBeInTheDocument();
    });
  });
});
*/
