import { useState, useRef, useEffect } from "react";
import { useSession } from "../store/session";

interface Props {
  onSend: (text: string) => void;
}

export default function InputBar({ onSend }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const busy = useSession((s) => s.busy);
  const status = useSession((s) => s.connectionStatus);

  // Auto-grow textarea up to 6 lines
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(el.scrollHeight, 6 * 24 + 16);
    el.style.height = next + "px";
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || busy || status !== "open") return;
    onSend(text);
    setValue("");
  };

  return (
    <div className="border-t border-[var(--border)] bg-[var(--panel)] px-3 py-2 sm:px-5 sm:py-3">
      <div className="mx-auto flex max-w-4xl items-end gap-2">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter newline. On mobile, prefer button.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder={
            status !== "open"
              ? "Connecting…"
              : busy
                ? "Waiting for response (press Stop to interrupt)…"
                : "Ask anything. Slash commands work too: /help"
          }
          disabled={status !== "open"}
          className="min-h-[40px] flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--panel-2)] px-3 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-dim)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)] disabled:opacity-60"
        />
        <button
          onClick={submit}
          disabled={!value.trim() || busy || status !== "open"}
          className="rounded-xl bg-[var(--accent-strong)] px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
