/**
 * Shared skeleton component with pulse animation for content loading states.
 * Mirrors the visual structure of real content so loading feels smooth.
 */
interface LoadingSkeletonProps {
  /** Number of skeleton rows to show */
  rows?: number;
  /** Optional custom class for the container */
  className?: string;
}

export default function LoadingSkeleton({ rows = 3, className = "" }: LoadingSkeletonProps) {
  return (
    <div className={`animate-pulse space-y-3 ${className}`} aria-busy="true" aria-label="Loading content">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-start justify-between gap-3">
          <div className="flex-1 space-y-2">
            <div className="h-4 w-4/5 rounded bg-[var(--panel)]" />
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <div className="h-3 w-14 rounded bg-[var(--panel)]" />
              <div className="h-3 w-12 rounded bg-[var(--panel)]" />
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <div className="h-6 w-12 rounded-md bg-[var(--panel)]" />
            <div className="h-6 w-12 rounded-md bg-[var(--panel)]" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Compact skeleton for inline or small areas */
export function SkeletonLine({ width = "w-full" }: { width?: string }) {
  return <div className={`h-4 rounded bg-[var(--panel)] animate-pulse ${width}`} />;
}

/** Box skeleton for card-like content */
export function SkeletonBox({ height = "h-20" }: { height?: string }) {
  return <div className={`rounded-lg border border-[var(--border)] ${height} bg-[var(--panel)] animate-pulse`} />;
}