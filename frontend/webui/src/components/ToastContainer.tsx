/**
 * Toast container — mount once in App.tsx.
 * Renders all active toasts from the toast store.
 */
import { useToastStore } from "../store/toast";

const KIND_STYLES = {
  success: "border-emerald-400/40 bg-emerald-500/20 text-emerald-100",
  error: "border-red-400/40 bg-red-500/20 text-red-200",
  info: "border-cyan-400/40 bg-cyan-500/20 text-cyan-100",
};

export default function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const removeToast = useToastStore((s) => s.removeToast);

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      aria-label="Notifications"
      className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-sm shadow-xl ${KIND_STYLES[t.kind]}`}
        >
          <span aria-hidden="true">
            {t.kind === "success" ? "✅" : t.kind === "error" ? "❌" : "ℹ️"}
          </span>
          <span className="flex-1">{t.message}</span>
          <button
            type="button"
            onClick={() => removeToast(t.id)}
            aria-label="Dismiss"
            className="ml-2 shrink-0 rounded px-1 text-xs opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:ring-1"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}