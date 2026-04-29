import { useEffect } from "react";
import { useSession, clearSelect } from "../store/session";

interface Props {
  onSelect: (command: string, value: string) => void;
}

export default function SelectModal({ onSelect }: Props) {
  const req = useSession((s) => s.pendingSelect);

  // Dismiss on Escape key.
  useEffect(() => {
    if (!req) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") clearSelect();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [req]);

  if (!req) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center"
      onClick={() => clearSelect()}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 text-xs uppercase tracking-wider text-[var(--accent)]">
          /{req.command}
        </div>
        <div className="mb-4 text-base font-semibold">{req.title}</div>

        <ul className="max-h-80 overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--panel-2)]">
          {req.options.length === 0 ? (
            <li className="px-3 py-3 text-sm text-[var(--text-dim)]">
              (no options)
            </li>
          ) : (
            req.options.map((opt) => {
              const isActive = !!opt.active;
              return (
                <li key={opt.value}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(req.command, opt.value);
                    }}
                    className={
                      "flex w-full items-start gap-3 border-b border-[var(--border)] px-3 py-2 text-left text-sm last:border-b-0 transition-colors " +
                      (isActive
                        ? "bg-[var(--accent-strong)]/15 text-[var(--text)]"
                        : "hover:bg-[var(--panel)] text-[var(--text)]")
                    }
                  >
                    <span
                      aria-hidden
                      className={
                        "mt-0.5 inline-block w-3 shrink-0 text-center text-xs " +
                        (isActive
                          ? "text-[var(--accent)]"
                          : "text-transparent")
                      }
                    >
                      ●
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block font-medium">
                        {opt.label || opt.value}
                      </span>
                      {opt.description ? (
                        <span className="mt-0.5 block text-xs text-[var(--text-dim)]">
                          {opt.description}
                        </span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => clearSelect()}
            className="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm hover:bg-[var(--panel)]"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
