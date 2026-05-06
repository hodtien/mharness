/**
 * Shared error banner with optional retry action.
 */
interface ErrorBannerProps {
  /** Error message to display */
  message: string;
  /** Optional retry handler */
  onRetry?: () => void;
  /** Optional label for retry button, defaults to "Retry" */
  retryLabel?: string;
  /** Additional CSS classes */
  className?: string;
}

export default function ErrorBanner({
  message,
  onRetry,
  retryLabel = "Retry",
  className = "",
}: ErrorBannerProps) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-center justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 ${className}`}
    >
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className="text-base">⚠️</span>
        <span>{message}</span>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-red-500/40 bg-red-500/20 px-3 py-1 text-xs font-medium text-red-200 transition hover:bg-red-500/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}