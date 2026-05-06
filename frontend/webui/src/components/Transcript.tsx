import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { useSession, type DisplayItem } from "../store/session";

interface TranscriptProps {
  hideWelcome?: boolean;
}

export default function Transcript({ hideWelcome = false }: TranscriptProps) {
  const transcript = useSession((s) => s.transcript);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [transcript.length, transcript[transcript.length - 1]?.text]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto px-3 py-3 sm:px-5 sm:py-4"
    >
      <div className="mx-auto flex max-w-4xl flex-col gap-3">
        {transcript.length === 0 && !hideWelcome && (
          <div className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-4 py-3 text-sm text-[var(--text-dim)]">
            Waiting for backend… Send your first message below.
          </div>
        )}
        {transcript.map((item) => (
          <Bubble key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}

function Bubble({ item }: { item: DisplayItem }) {
  const { role, text } = item;
  const tone = roleStyle(role);

  if (role === "tool") {
    return (
      <div className="rounded-lg border border-amber-400/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
        <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-amber-300/80">
          tool · {item.tool_name || "?"}
        </div>
        <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed">
          {prettyToolInput(item.tool_input) || text}
        </pre>
      </div>
    );
  }

  if (role === "tool_result") {
    return (
      <div
        className={`rounded-lg border px-3 py-2 text-xs ${
          item.is_error
            ? "border-rose-500/40 bg-rose-500/5 text-rose-200"
            : "border-emerald-500/30 bg-emerald-500/5 text-emerald-200"
        }`}
      >
        <div className="mb-1 font-mono text-[11px] uppercase tracking-wider opacity-70">
          {item.is_error ? "tool error" : "tool result"} · {item.tool_name || "?"}
        </div>
        <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed">
          {truncate(text, 4000)}
        </pre>
      </div>
    );
  }

  if (role === "system" || role === "log") {
    return (
      <div className="self-center rounded-md bg-[var(--panel)] px-3 py-1 text-[11px] text-[var(--text-dim)]">
        {text}
      </div>
    );
  }

  // user / assistant
  return (
    <div className={`flex ${role === "user" ? "justify-end" : "justify-start"}`}>
      <div
        className={`md max-w-[88%] rounded-2xl border px-4 py-2 text-sm leading-relaxed sm:max-w-[80%] ${tone}`}
      >
        {role === "assistant" ? (
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
            {text || (item.pending ? "▍" : "")}
          </ReactMarkdown>
        ) : (
          <div className="whitespace-pre-wrap break-words">{text}</div>
        )}
      </div>
    </div>
  );
}

function roleStyle(role: DisplayItem["role"]): string {
  switch (role) {
    case "user":
      return "border-sky-500/40 bg-sky-500/10 text-sky-100";
    case "assistant":
      return "border-[var(--border)] bg-[var(--panel)] text-[var(--assistant)]";
    default:
      return "border-[var(--border)] bg-[var(--panel)] text-[var(--text-dim)]";
  }
}

function prettyToolInput(input: Record<string, unknown> | null | undefined): string {
  if (!input) return "";
  try {
    return JSON.stringify(input, null, 2);
  } catch {
    return String(input);
  }
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n) + `\n… [+${s.length - n} chars truncated]`;
}
