/**
 * Skeleton loader for the session-card layout used in HistoryPanel.
 * Mirrors the visual structure of the real card so the loading placeholder
 * feels like real content is loading in.
 */
export default function HistoryCardSkeleton() {
  return (
    <div className="animate-pulse rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3">
      <div className="flex items-start justify-between gap-3">
        {/* Left side: summary + metadata */}
        <div className="min-w-0 flex-1 space-y-2">
          {/* Summary line */}
          <div className="h-4 w-4/5 rounded bg-[var(--panel)]" />
          {/* Metadata row: badge + msg count + time */}
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            <div className="h-5 w-14 rounded bg-[var(--panel)]" />
            <div className="h-3 w-12 rounded bg-[var(--panel)]" />
            <div className="h-3 w-10 rounded bg-[var(--panel)]" />
          </div>
        </div>
        {/* Right side: View / Resume / Delete buttons */}
        <div className="flex shrink-0 gap-2">
          <div className="h-6 w-10 rounded-md bg-[var(--panel)]" />
          <div className="h-6 w-12 rounded-md bg-[var(--panel)]" />
          <div className="h-6 w-12 rounded-md bg-[var(--panel)]" />
        </div>
      </div>
    </div>
  );
}
