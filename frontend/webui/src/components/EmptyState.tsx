/**
 * Shared empty state component for when content is empty.
 */
interface EmptyStateProps {
  /** Primary message */
  message: string;
  /** Optional descriptive text below the message */
  description?: string;
  /** Emoji or icon character (defaults to folder icon) */
  icon?: string;
  /** Optional action button */
  action?: {
    label: string;
    onClick: () => void;
  };
  /** Additional CSS classes */
  className?: string;
}

export default function EmptyState({
  message,
  description,
  icon = "📂",
  action,
  className = "",
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={`flex flex-col items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--panel)] p-8 text-center ${className}`}
    >
      <span aria-hidden="true" className="mb-3 text-4xl">{icon}</span>
      <p className="text-sm font-medium text-[var(--text)]">{message}</p>
      {description && (
        <p className="mt-1 text-xs text-[var(--text-dim)]">{description}</p>
      )}
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-4 rounded-lg border border-[var(--accent)]/40 bg-[var(--accent)]/20 px-4 py-2 text-sm font-medium text-[var(--accent)] transition hover:bg-[var(--accent)]/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}