import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { useSession, type DisplayItem } from "../store/session";
import ToolCard from "./ToolCard";

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

  if (role === "tool" || role === "tool_result") {
    return (
      <ToolCard
        role={role}
        tool_name={item.tool_name}
        is_error={item.is_error}
        text={text}
        tool_input={item.tool_input}
      />
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