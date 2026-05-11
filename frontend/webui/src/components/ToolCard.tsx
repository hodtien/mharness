import { useState, useMemo } from "react";

export type ContentSize = "small" | "medium" | "large";

/** Auto-collapse threshold: ~3 lines of terminal output */
const SMALL_THRESHOLD = 200;
/** Show preview threshold: ~20 lines */
const MEDIUM_THRESHOLD = 1500;

export function getContentSize(text: string): ContentSize {
  if (text.length <= SMALL_THRESHOLD) return "small";
  if (text.length <= MEDIUM_THRESHOLD) return "medium";
  return "large";
}

interface ToolCardProps {
  role: "tool" | "tool_result";
  tool_name?: string | null;
  is_error?: boolean | null;
  text: string;
  tool_input?: Record<string, unknown> | null;
  duration_ms?: number;
}

export default function ToolCard({ role, tool_name, is_error, text, tool_input, duration_ms }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);

  const size = useMemo(() => getContentSize(text), [text]);
  const semanticSummary = useMemo(() => buildSemanticSummary(text, tool_name, is_error), [text, tool_name, is_error]);
  const toggleExpanded = () => setExpanded((v) => !v);
  const isAutoExpanded = size === "small" || role === "tool";

  // Tool result error styling
  const borderColor = role === "tool_result" && is_error
    ? "border-rose-500/40"
    : role === "tool"
    ? "border-amber-400/30"
    : "border-emerald-500/30";

  const bgColor = role === "tool_result" && is_error
    ? "bg-rose-500/5"
    : role === "tool"
    ? "bg-amber-500/5"
    : "bg-emerald-500/5";

  const textColor = role === "tool_result" && is_error
    ? "text-rose-200"
    : role === "tool"
    ? "text-amber-200"
    : "text-emerald-200";

  return (
    <div
      className={`rounded-lg border ${borderColor} ${bgColor} ${textColor} overflow-hidden`}
    >
      {/* Header - always visible, clickable to expand */}
      <button
        type="button"
        onClick={toggleExpanded}
        className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-white/5 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2 min-w-0">
          {/* Status indicator */}
          <span className={`shrink-0 w-2 h-2 rounded-full ${role === "tool" ? "bg-amber-400" : is_error ? "bg-rose-400" : "bg-emerald-400"}`} />
          
          {/* Tool name */}
          <span className="font-mono text-[11px] uppercase tracking-wider opacity-80 truncate">
            {role === "tool" ? "tool" : is_error ? "error" : "result"} · {tool_name || "?"}
          </span>

          {/* Duration badge */}
          {duration_ms !== undefined && (
            <span className="shrink-0 text-[10px] opacity-60 font-mono">
              {formatDuration(duration_ms)}
            </span>
          )}
        </div>

        {/* Expand/collapse icon */}
        <span className="shrink-0 ml-2 text-xs opacity-50">
          {(expanded || isAutoExpanded) ? "▼" : "▶"}
        </span>
      </button>

      {/* Collapsed summary (shown when not expanded and size is medium/large) */}
      {!expanded && !isAutoExpanded && size === "large" && (
        <div className="px-3 pb-2">
          <span className="text-[11px] opacity-70 line-clamp-1">{semanticSummary}</span>
          <span className="text-[10px] opacity-50 ml-2">[{text.length} chars]</span>
        </div>
      )}

      {/* Content area - shown when expanded */}
      {(expanded || isAutoExpanded) && (
        <div className="px-3 pb-2 pt-0">
          {/* Tool input section (for tool role) */}
          {role === "tool" && tool_input && (
            <div className="mb-2">
              <div className="text-[10px] uppercase tracking-wider opacity-60 mb-1">Input</div>
              <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed max-h-48 overflow-y-auto">
                {prettyToolInput(tool_input)}
              </pre>
            </div>
          )}

          {/* Tool result / text content */}
          <div>
            {role === "tool_result" && (
              <div className="text-[10px] uppercase tracking-wider opacity-60 mb-1">Output</div>
            )}
            <pre className={`whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed ${size === "large" ? "max-h-64 overflow-y-auto" : ""}`}>
              {size === "large" && text.length > 2000 ? text.slice(0, 2000) + "\n… [+ " + (text.length - 2000) + " chars truncated]" : text}
            </pre>
          </div>

          {/* Large content collapse hint */}
          {size === "large" && text.length > 2000 && (
            <button
              type="button"
              onClick={toggleExpanded}
              className="mt-1 text-[10px] opacity-50 hover:opacity-80 transition-opacity"
            >
              Click to collapse
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function buildSemanticSummary(text: string, tool_name?: string | null, is_error?: boolean | null): string {
  if (is_error) {
    return "Tool execution failed";
  }
  
  // Try to extract meaningful summary from text
  const firstLine = text.split("\n")[0].trim();
  if (firstLine.length > 0 && firstLine.length < 100) {
    return firstLine;
  }
  
  // Default summaries based on tool patterns
  if (tool_name) {
    const name = tool_name.toLowerCase();
    if (name.includes("bash") || name.includes("shell")) {
      return "Executed shell command";
    }
    if (name.includes("read") || name.includes("file")) {
      return "Read file content";
    }
    if (name.includes("write") || name.includes("edit")) {
      return "Modified file";
    }
    if (name.includes("search") || name.includes("grep")) {
      return "Searched files";
    }
    if (name.includes("git")) {
      return "Git operation";
    }
    return `Used ${tool_name}`;
  }
  
  return "Tool executed";
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function prettyToolInput(input: Record<string, unknown>): string {
  try {
    return JSON.stringify(input, null, 2);
  } catch {
    return String(input);
  }
}