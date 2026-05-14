import { useState } from "react";

interface PathDisplayProps {
  /** Full path to display and copy */
  path: string;
  /** Max display length before truncation (default 40) */
  maxLen?: number;
  /** aria-label for the copy button */
  copyLabel?: string;
}

/**
 * Displays a path with truncation, tooltip, and copy-to-clipboard.
 *
 * Pattern:
 * - Monospace truncation with native `title` tooltip for full reveal
 * - Explicit copy button with accessible label
 * - Responsive wrap on narrow viewports
 */
export function PathDisplay({
  path,
  maxLen = 40,
  copyLabel,
}: PathDisplayProps) {
  const [copied, setCopied] = useState(false);

  const displayPath =
    path.length > maxLen
      ? path.slice(0, maxLen - 1) + "…"
      : path;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(path);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard unavailable — silently ignore
    }
  };

  return (
    <div className="flex min-w-0 items-center gap-2">
      <code
        className="min-w-0 flex-1 truncate font-mono text-xs text-[var(--text)]"
        title={path}
        aria-label={copyLabel ? `${copyLabel}: ${path}` : path}
      >
        {displayPath}
      </code>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={copyLabel ?? `Copy path: ${path}`}
        className="shrink-0 rounded border border-[var(--border)] bg-[var(--panel-2)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-dim)] transition hover:border-[var(--accent)]/40 hover:text-[var(--text)] focus:outline-none focus:ring-1 focus:ring-[var(--border)]"
      >
        {copied ? "✓" : "⎘"}
      </button>
    </div>
  );
}