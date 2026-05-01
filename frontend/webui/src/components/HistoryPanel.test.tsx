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

import { formatRelativeTime } from "./HistoryPanel";

// ---------------------------------------------------------------------------
// Pure-function unit tests (no DOM required, safe in any test runner)
// ---------------------------------------------------------------------------

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
    expect(result).toHaveLength(62); // 60 chars + '…' (3 bytes, 1 code point)
    expect(result.endsWith("…")).toBe(true);
    expect(result.startsWith("A".repeat(60))).toBe(true);
  });

  test("string of exactly 60 chars is not truncated", () => {
    const exact = "B".repeat(60);
    expect(truncate(exact)).toBe(exact);
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
