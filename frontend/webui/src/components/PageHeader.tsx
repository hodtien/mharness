import type { ReactNode } from "react";

/** Metadata item displayed in the bottom row of a page header. */
export interface PageHeaderMetaItem {
  label: string;
  value: string;
  /** Optional accent color class (defaults to neutral). */
  accent?: "cyan" | "amber" | "red" | "emerald" | "none";
}

export interface PageHeaderProps {
  /** Page title (required — shown as <h1>). */
  title: string;
  /** One-line description of the page's purpose. */
  description?: string;
  /** Primary action(s) shown top-right. */
  primaryAction?: ReactNode;
  /** Secondary action(s) shown below primary. */
  secondaryAction?: ReactNode;
  /** Key-value metadata row (e.g. project name, job count, last sync time). */
  metadata?: PageHeaderMetaItem[];
}

/**
 * Standardised page header component.
 *
 * Layout:
 * ```
 * ┌─────────────────────────────────────────────────┐
 * │  [breadcrumb]                                  │
 * │  Title              [ primaryAction ]          │
 * │  description        [ secondaryAction ]       │
 * ├─────────────────────────────────────────────────┤
 * │  meta label · value · label · value …          │
 * └─────────────────────────────────────────────────┘
 * ```
 */
export default function PageHeader({
  title,
  description,
  primaryAction,
  secondaryAction,
  metadata,
}: PageHeaderProps) {
  return (
    <div className="border-b border-[var(--border)] bg-[var(--panel)] px-4 pt-3 pb-2">
      {/* Top row: title + actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold leading-tight text-[var(--text)]">{title}</h1>
          {description && (
            <p className="mt-0.5 text-sm text-[var(--text-dim)]">{description}</p>
          )}
        </div>
        {(primaryAction || secondaryAction) && (
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            {primaryAction && <div>{primaryAction}</div>}
            {secondaryAction && <div>{secondaryAction}</div>}
          </div>
        )}
      </div>

      {/* Metadata row */}
      {metadata && metadata.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-[var(--text-dim)]">
          {metadata.map((item, idx) => {
            const accentMap: Record<string, string> = {
              cyan: "text-cyan-300",
              amber: "text-amber-300",
              red: "text-red-300",
              emerald: "text-emerald-300",
            };
            const valueClass = item.accent && item.accent !== "none"
              ? accentMap[item.accent] ?? "text-[var(--text)]"
              : "text-[var(--text)]";
            return (
              <span key={idx} className="contents">
                {idx > 0 && <span className="opacity-40" aria-hidden>·</span>}
                <span className="whitespace-nowrap">
                  <span className="opacity-60">{item.label}</span>
                  <span className="mx-1 opacity-40">·</span>
                  <span className={valueClass}>{item.value}</span>
                </span>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
