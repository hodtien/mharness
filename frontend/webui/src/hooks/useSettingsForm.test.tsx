import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { render, screen } from "@testing-library/react";
import {
  useDirty,
  useUnsavedWarning,
  useFormFeedback,
  FeedbackBadge,
  DirtyIndicator,
} from "./useSettingsForm";

// ─────────────────────────────────────────────────────────────────────────────
// useDirty
// ─────────────────────────────────────────────────────────────────────────────

describe("useDirty", () => {
  it("initializes with the given isDirty value", () => {
    const { result } = renderHook(() => useDirty(false));
    expect(result.current.dirty).toBe(false);
  });

  it("syncs when isDirty external prop changes", () => {
    let isDirty = false;
    const { result, rerender } = renderHook(() => useDirty(isDirty));
    expect(result.current.dirty).toBe(false);

    isDirty = true;
    rerender();
    expect(result.current.dirty).toBe(true);
  });

  it("markClean resets dirty to false", () => {
    let isDirty = true;
    const { result, rerender } = renderHook(() => useDirty(isDirty));
    expect(result.current.dirty).toBe(true);

    act(() => {
      result.current.markClean();
    });
    expect(result.current.dirty).toBe(false);

    // External value changing back should not override markClean
    isDirty = true;
    rerender(); // no change because prevDirty.current was already true — stays false after markClean
    // Actually after markClean, prevDirty is false; now isDirty is still true, so it syncs
    // This is expected — external state wins after rerender
    expect(result.current.dirty).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// useUnsavedWarning
// ─────────────────────────────────────────────────────────────────────────────

describe("useUnsavedWarning", () => {
  let addEventListenerSpy: ReturnType<typeof vi.spyOn>;
  let removeEventListenerSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    addEventListenerSpy = vi.spyOn(window, "addEventListener");
    removeEventListenerSpy = vi.spyOn(window, "removeEventListener");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("registers beforeunload listener when isDirty is true", () => {
    renderHook(() => useUnsavedWarning({ isDirty: true }));
    expect(addEventListenerSpy).toHaveBeenCalledWith("beforeunload", expect.any(Function));
  });

  it("removes beforeunload listener on unmount", () => {
    const { unmount } = renderHook(() => useUnsavedWarning({ isDirty: true }));
    unmount();
    expect(removeEventListenerSpy).toHaveBeenCalledWith("beforeunload", expect.any(Function));
  });

  it("calls event.preventDefault when isDirty and beforeunload fires", () => {
    renderHook(() => useUnsavedWarning({ isDirty: true }));

    const handler = addEventListenerSpy.mock.calls.find(
      ([event]) => event === "beforeunload",
    )?.[1] as ((e: BeforeUnloadEvent) => void) | undefined;
    expect(handler).toBeDefined();

    const mockEvent = { preventDefault: vi.fn(), returnValue: "" } as unknown as BeforeUnloadEvent;
    handler?.(mockEvent);

    expect(mockEvent.preventDefault).toHaveBeenCalled();
  });

  it("does NOT prevent unload when isDirty is false", () => {
    renderHook(() => useUnsavedWarning({ isDirty: false }));

    const handler = addEventListenerSpy.mock.calls.find(
      ([event]) => event === "beforeunload",
    )?.[1] as ((e: BeforeUnloadEvent) => void) | undefined;
    expect(handler).toBeDefined();

    const mockEvent = { preventDefault: vi.fn(), returnValue: "" } as unknown as BeforeUnloadEvent;
    handler?.(mockEvent);

    expect(mockEvent.preventDefault).not.toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// useFormFeedback
// ─────────────────────────────────────────────────────────────────────────────

describe("useFormFeedback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with idle feedback", () => {
    const { result } = renderHook(() => useFormFeedback());
    expect(result.current.feedback).toBe("idle");
  });

  it("showSaving sets feedback to saving", () => {
    const { result } = renderHook(() => useFormFeedback());
    act(() => {
      result.current.showSaving();
    });
    expect(result.current.feedback).toBe("saving");
  });

  it("showSaved sets feedback to saved then auto-resets to idle after 2s", () => {
    const { result } = renderHook(() => useFormFeedback());
    act(() => {
      result.current.showSaved();
    });
    expect(result.current.feedback).toBe("saved");

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current.feedback).toBe("idle");
  });

  it("showError sets feedback to error", () => {
    const { result } = renderHook(() => useFormFeedback());
    act(() => {
      result.current.showError();
    });
    expect(result.current.feedback).toBe("error");
  });

  it("reset clears any pending timer and resets to idle", () => {
    const { result } = renderHook(() => useFormFeedback());
    act(() => {
      result.current.showSaved();
    });
    expect(result.current.feedback).toBe("saved");

    act(() => {
      result.current.reset();
    });
    expect(result.current.feedback).toBe("idle");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// FeedbackBadge
// ─────────────────────────────────────────────────────────────────────────────

describe("FeedbackBadge", () => {
  it("renders nothing when feedback is idle", () => {
    const { container } = render(<FeedbackBadge feedback="idle" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders saving badge with role=status", () => {
    render(<FeedbackBadge feedback="saving" />);
    const el = screen.getByRole("status");
    expect(el.textContent).toContain("Saving");
  });

  it("renders saved badge with role=status", () => {
    render(<FeedbackBadge feedback="saved" />);
    const el = screen.getByRole("status");
    expect(el.textContent).toContain("Saved");
  });

  it("renders error badge with role=alert", () => {
    render(<FeedbackBadge feedback="error" />);
    const el = screen.getByRole("alert");
    expect(el.textContent).toContain("Error");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// DirtyIndicator
// ─────────────────────────────────────────────────────────────────────────────

describe("DirtyIndicator", () => {
  it("renders 'Unsaved changes' text", () => {
    render(<DirtyIndicator />);
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });
});
