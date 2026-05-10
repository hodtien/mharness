/**
 * Cross-cutting form validation and UX hooks for settings pages.
 *
 * Provides:
 * - useDirty: track when a form has unsaved changes
 * - useUnsavedWarning: warns the user before leaving a page with unsaved changes
 * - useFormFeedback: consistent save/saved/error feedback state
 * - FeedbackBadge: inline badge component for feedback state
 * - DirtyIndicator: inline badge for unsaved changes indicator
 */

import { useCallback, useEffect, useRef, useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// useDirty
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Track whether a form has been modified from its initial state.
 *
 * @param isDirty - true when the form has unsaved changes
 * @returns dirty state and a "mark clean" helper to call after successful save
 */
export function useDirty(isDirty: boolean) {
  const [dirty, setDirty] = useState(isDirty);

  // Sync with external isDirty signal (e.g. draftChanged from form state)
  const prevDirty = useRef(isDirty);
  useEffect(() => {
    if (isDirty !== prevDirty.current) {
      setDirty(isDirty);
      prevDirty.current = isDirty;
    }
  }, [isDirty]);

  const markClean = useCallback(() => {
    setDirty(false);
    prevDirty.current = false;
  }, []);

  return { dirty, markClean };
}

// ─────────────────────────────────────────────────────────────────────────────
// useUnsavedWarning
// ─────────────────────────────────────────────────────────────────────────────

interface UseUnsavedWarningOptions {
  /** Whether the current page/form has unsaved changes. */
  isDirty: boolean;
  /** Optional custom message. Defaults to a generic warning. */
  message?: string;
}

/**
 * Warns the user via the browser's beforeunload API when they try to leave
 * a page that has unsaved changes.
 */
export function useUnsavedWarning({ isDirty, message }: UseUnsavedWarningOptions) {
  const BLOCK_MESSAGE = message ?? "You have unsaved changes. Are you sure you want to leave?";

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!isDirty) return;
      e.preventDefault();
      // Most browsers still require the string to be assigned
      e.returnValue = BLOCK_MESSAGE; // eslint-disable-line no-param-reassign
      return BLOCK_MESSAGE;
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty, BLOCK_MESSAGE]);
}

// ─────────────────────────────────────────────────────────────────────────────
// useFormFeedback
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Manages consistent "saved" / "saving" / "error" feedback state for a form.
 *
 * @returns feedback state, setters, and helper methods
 */
export function useFormFeedback() {
  const [feedback, setFeedback] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | undefined>(undefined);
  const savedTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (savedTimer.current !== null) {
        window.clearTimeout(savedTimer.current);
      }
    },
    [],
  );

  const showSaved = useCallback(() => {
    setFeedback("saved");
    setErrorMessage(undefined);
    if (savedTimer.current !== null) window.clearTimeout(savedTimer.current);
    savedTimer.current = window.setTimeout(() => {
      setFeedback("idle");
      savedTimer.current = null;
    }, 2000);
  }, []);

  const showSaving = useCallback(() => {
    if (savedTimer.current !== null) window.clearTimeout(savedTimer.current);
    setFeedback("saving");
    setErrorMessage(undefined);
  }, []);

  const showError = useCallback((message?: string) => {
    if (savedTimer.current !== null) window.clearTimeout(savedTimer.current);
    setFeedback("error");
    setErrorMessage(message);
  }, []);

  const reset = useCallback(() => {
    if (savedTimer.current !== null) window.clearTimeout(savedTimer.current);
    setFeedback("idle");
    setErrorMessage(undefined);
  }, []);

  return { feedback, errorMessage, setFeedback, showSaved, showSaving, showError, reset };
}

// ─────────────────────────────────────────────────────────────────────────────
// FeedbackBadge
// ─────────────────────────────────────────────────────────────────────────────

/** Compact inline badge that reflects the current feedback state. */
export function FeedbackBadge({
  feedback,
  errorMessage,
}: {
  feedback: "idle" | "saving" | "saved" | "error";
  errorMessage?: string;
}) {
  if (feedback === "idle") return null;

  if (feedback === "saving") {
    return (
      <span
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-1.5 rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2.5 py-0.5 text-xs text-cyan-300"
      >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
        Saving…
      </span>
    );
  }

  if (feedback === "saved") {
    return (
      <span
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs text-emerald-300"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Saved
      </span>
    );
  }

  return (
    <span
      role="alert"
      aria-live="assertive"
      className="inline-flex items-center gap-1.5 rounded-full border border-red-400/30 bg-red-500/10 px-2.5 py-0.5 text-xs text-red-300"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
      {errorMessage ?? "Error"}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DirtyIndicator
// ─────────────────────────────────────────────────────────────────────────────

/** Small inline indicator shown when a form has unsaved changes. */
export function DirtyIndicator() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-400/30 bg-amber-500/10 px-2.5 py-0.5 text-xs text-amber-300">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
      Unsaved changes
    </span>
  );
}
