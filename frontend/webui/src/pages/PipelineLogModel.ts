// ─── Stream event (protocol) ──────────────────────────────────────────────────

export interface StreamEvent {
  ts: number;
  kind: string;
  payload: Record<string, unknown>;
  index?: number;
}

// ─── Semantic tags ────────────────────────────────────────────────────────────

export type LogTag = "#agent" | "#tool" | "#error" | "#phase" | "#checkpoint";

// ─── LogFilter uses tag labels ────────────────────────────────────────────────

export type LogFilter = "all" | "#agent" | "#tool" | "#error";

export const LOG_FILTERS: { id: LogFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "#agent", label: "#agent" },
  { id: "#tool", label: "#tool" },
  { id: "#error", label: "#error" },
];

// ─── Semantic event card ──────────────────────────────────────────────────────

export type LogStepType = "agent" | "tool" | "phase" | "error" | "checkpoint" | "event";

export interface LogDetailPayload {
  label: string;
  value: string;
}

export interface LogStep {
  id: string;
  type: LogStepType;
  phase: string;
  title: string;
  summary: string;
  timestamp: number;
  isError: boolean;
  tags: LogTag[];
  details: LogDetailPayload[];
  rawEvents: StreamEvent[];
  searchText: string;
}

// ─── Phase group (for backwards-compatible layout) ────────────────────────────

export interface LogPhaseGroup {
  id: string;
  phase: string;
  label: string;
  firstTimestamp: number;
  lastTimestamp: number;
  steps: LogStep[];
  hasErrors: boolean;
  searchText: string;
}

// ─── Tag matching ─────────────────────────────────────────────────────────────

export function stepMatchesFilter(step: LogStep, filter: LogFilter): boolean {
  if (filter === "all") return true;
  return step.tags.includes(filter as LogTag);
}

// ─── Flat chronological stream (newest-first) ─────────────────────────────────
// The primary data structure for the operator-first feed.

export function eventsToLogSteps(events: StreamEvent[]): LogStep[] {
  const steps: LogStep[] = [];
  const pendingTools = new Map<string, LogStep[]>();
  let textBuffer: { event: StreamEvent; index: number; text: string; phase: string } | null = null;

  const flushText = () => {
    if (!textBuffer) return;
    steps.push(createLogStep({
      id: `${textBuffer.index}-agent-${textBuffer.phase}`,
      type: "agent",
      phase: textBuffer.phase,
      title: "Agent message",
      summary: summarizeText(textBuffer.text) || "Agent output",
      timestamp: textBuffer.event.ts,
      isError: false,
      tags: ["#agent"],
      details: [{ label: "Output", value: textBuffer.text }],
      rawEvents: [textBuffer.event],
    }));
    textBuffer = null;
  };

  for (const [position, event] of events.entries()) {
    const index = event.index ?? position;
    const phase = getEventPhase(event);

    if (event.kind === "text_delta") {
      const text = String(event.payload?.text ?? "");
      if (textBuffer && textBuffer.phase === phase) {
        // Mutate directly since textBuffer is non-null here
        textBuffer.text += text;
      } else {
        flushText();
        textBuffer = { event, index, text, phase };
      }
      continue;
    }

    flushText();

    if (event.kind === "tool_call") {
      const step = toolCallToStep(event, phase, index);
      const key = getToolKey(event, phase);
      if (key) pendingTools.set(key, [...(pendingTools.get(key) ?? []), step]);
      steps.push(step);
      continue;
    }

    if (event.kind === "tool_result") {
      const key = getToolKey(event, phase);
      const pendingQueue = key ? (pendingTools.get(key) ?? []) : [];
      const pending = pendingQueue[0];
      if (key && pending) {
        const stepIndex = steps.findIndex((s) => s.id === pending.id);
        const pairedStep = pairToolResult(pending, event);
        if (stepIndex >= 0) steps.splice(stepIndex, 1, pairedStep);
        const nextQueue = pendingQueue.slice(1);
        if (nextQueue.length > 0) {
          pendingTools.set(key, nextQueue);
        } else {
          pendingTools.delete(key);
        }
      } else {
        steps.push(toolResultToStep(event, phase, index));
      }
      continue;
    }

    steps.push(eventToLogStep(event, phase, index));
  }

  flushText();
  // Newest-first ordering
  return steps.slice().reverse();
}

// ─── Filter flat step list ────────────────────────────────────────────────────

export function filterLogSteps(steps: LogStep[], filter: LogFilter, normalizedQuery: string): LogStep[] {
  return steps.filter((step) => {
    const matchesFilter = stepMatchesFilter(step, filter);
    return matchesFilter && (!normalizedQuery || step.searchText.includes(normalizedQuery));
  });
}

// ─── Phase-grouped view (used by phase accordion for backwards compat) ────────

export function eventsToLogPhaseGroups(events: StreamEvent[]): LogPhaseGroup[] {
  // Get chronological steps first (not reversed), then group by phase
  const steps = eventsToLogSteps(events).slice().reverse(); // reverse back to oldest-first for grouping
  return groupLogStepsByPhase(steps);
}

export function filterLogPhaseGroups(phases: LogPhaseGroup[], activeFilter: LogFilter, normalizedQuery: string): LogPhaseGroup[] {
  return phases
    .map((phase) => {
      const filteredSteps = phase.steps.filter((step) => {
        return stepMatchesFilter(step, activeFilter) && (!normalizedQuery || step.searchText.includes(normalizedQuery));
      });
      return { ...phase, steps: filteredSteps };
    })
    .filter((phase) => phase.steps.length > 0 || (activeFilter === "#error" && phase.hasErrors));
}

export function getSelectedLogStep(steps: LogStep[], selectedStepId: string | null): LogStep | null {
  return steps.find((s) => s.id === selectedStepId) ?? steps[0] ?? null;
}

// ─── Private helpers ──────────────────────────────────────────────────────────

function createLogStep(input: Omit<LogStep, "searchText">): LogStep {
  const raw = input.rawEvents.map((ev) => `${ev.kind}\n${JSON.stringify(ev.payload, null, 2)}`).join("\n\n");
  const detailText = input.details.map((d) => d.value).join("\n");
  return {
    ...input,
    searchText: `${input.phase} ${input.title} ${input.summary} ${input.tags.join(" ")} ${detailText} ${raw}`.toLowerCase(),
  };
}

function eventToLogStep(event: StreamEvent, phase: string, index: number): LogStep {
  const { kind, payload } = event;
  const rawPayload = JSON.stringify(payload, null, 2);

  if (kind === "phase_start") {
    const attempt = typeof payload?.attempt === "number" ? ` · attempt ${payload.attempt}` : "";
    const phaseLabel = String(payload?.phase ?? phase);
    return createLogStep({
      id: getEventId(event, index),
      type: "phase",
      phase,
      title: `Phase: ${phaseLabel}${attempt}`,
      summary: "Phase started",
      timestamp: event.ts,
      isError: false,
      tags: ["#phase"],
      details: [{ label: "Payload", value: rawPayload }],
      rawEvents: [event],
    });
  }

  if (kind === "phase_end") {
    const ok = payload?.ok !== false;
    const phaseLabel = String(payload?.phase ?? phase);
    return createLogStep({
      id: getEventId(event, index),
      type: "phase",
      phase,
      title: `Phase: ${phaseLabel} ended`,
      summary: ok ? "Phase completed" : "Phase failed",
      timestamp: event.ts,
      isError: !ok,
      tags: ok ? ["#phase"] : ["#phase", "#error"],
      details: [{ label: "Payload", value: rawPayload }],
      rawEvents: [event],
    });
  }

  if (kind === "error") {
    return createLogStep({
      id: getEventId(event, index),
      type: "error",
      phase,
      title: "Error",
      summary: String(payload?.message ?? "Unknown error"),
      timestamp: event.ts,
      isError: true,
      tags: ["#error"],
      details: [{ label: "Payload", value: rawPayload }],
      rawEvents: [event],
    });
  }

  if (kind === "checkpoint_saved" || kind === "resume_started") {
    return createLogStep({
      id: getEventId(event, index),
      type: "checkpoint",
      phase,
      title: kind === "checkpoint_saved" ? "Checkpoint saved" : "Resume started",
      summary: `Phase: ${phase}`,
      timestamp: event.ts,
      isError: false,
      tags: ["#checkpoint"],
      details: [{ label: "Payload", value: rawPayload }],
      rawEvents: [event],
    });
  }

  return createLogStep({
    id: getEventId(event, index),
    type: "event",
    phase,
    title: kind,
    summary: `Phase: ${phase}`,
    timestamp: event.ts,
    isError: false,
    tags: [],
    details: [{ label: "Payload", value: rawPayload }],
    rawEvents: [event],
  });
}

function toolCallToStep(event: StreamEvent, phase: string, index: number): LogStep {
  const name = String(event.payload?.name ?? "tool");
  const inputSummary = String(event.payload?.input_summary ?? "");
  // Build a human-readable summary from the tool input if available
  const inputObj = event.payload?.input;
  const toolSummary = inputSummary || summarizeToolInput(name, inputObj) || "Tool called";
  return createLogStep({
    id: `${getEventId(event, index)}-tool`,
    type: "tool",
    phase,
    title: `🔧 ${name}`,
    summary: toolSummary,
    timestamp: event.ts,
    isError: false,
    tags: ["#tool"],
    details: [{ label: "Input", value: formatToolInput(inputObj) }],
    rawEvents: [event],
  });
}

function toolResultToStep(event: StreamEvent, phase: string, index: number): LogStep {
  const name = String(event.payload?.name ?? "tool");
  const isError = event.payload?.is_error === true;
  const resultSummary = String(event.payload?.summary ?? (isError ? "Tool failed" : "Tool returned"));
  return createLogStep({
    id: `${getEventId(event, index)}-tool-result`,
    type: "tool",
    phase,
    title: `🔧 ${name}`,
    summary: resultSummary,
    timestamp: event.ts,
    isError,
    tags: isError ? ["#tool", "#error"] : ["#tool"],
    details: [{ label: "Output", value: formatToolOutput(event.payload?.output ?? event.payload?.content) }],
    rawEvents: [event],
  });
}

function pairToolResult(step: LogStep, event: StreamEvent): LogStep {
  const isError = event.payload?.is_error === true;
  const resultSummary = String(event.payload?.summary ?? step.summary);
  const outputVal = formatToolOutput(event.payload?.output ?? event.payload?.content);
  return createLogStep({
    ...step,
    summary: resultSummary,
    isError,
    tags: isError ? ["#tool", "#error"] : ["#tool"],
    details: [...step.details, { label: "Output", value: outputVal }],
    rawEvents: [...step.rawEvents, event],
  });
}

function groupLogStepsByPhase(steps: LogStep[]): LogPhaseGroup[] {
  const groups = new Map<string, LogStep[]>();
  for (const step of steps) {
    groups.set(step.phase, [...(groups.get(step.phase) ?? []), step]);
  }
  return Array.from(groups.entries()).map(([phase, phaseSteps]) => {
    const firstTimestamp = phaseSteps[0]?.timestamp ?? 0;
    const lastTimestamp = phaseSteps[phaseSteps.length - 1]?.timestamp ?? firstTimestamp;
    const hasErrors = phaseSteps.some((s) => s.isError);
    const searchText = phaseSteps.map((s) => s.searchText).join(" ");
    return {
      id: `phase-${phase}`,
      phase,
      label: phase === "default" ? "General" : phase,
      firstTimestamp,
      lastTimestamp,
      steps: phaseSteps,
      hasErrors,
      searchText,
    };
  });
}

function getEventPhase(event: StreamEvent): string {
  return typeof event.payload?.phase === "string" && event.payload.phase.trim() ? event.payload.phase : "default";
}

function getEventId(event: StreamEvent, index: number): string {
  return `${index}-${event.ts}-${event.kind}`;
}

function getToolKey(event: StreamEvent, phase: string): string | null {
  const payload = event.payload ?? {};
  const explicitId = payload.call_id ?? payload.tool_call_id ?? payload.id ?? payload.invocation_id;
  if (typeof explicitId === "string" || typeof explicitId === "number") return `${phase}:${explicitId}`;
  return null;
}

export function summarizeText(text: string): string {
  return text.trim().replace(/\s+/g, " ").slice(0, 180);
}

/**
 * Produce a one-line human summary for a tool call input,
 * choosing the most operator-readable field.
 */
function summarizeToolInput(toolName: string, input: unknown): string {
  if (!input || typeof input !== "object") return "";
  const obj = input as Record<string, unknown>;
  // Common short-circuit fields
  const candidates = ["command", "query", "path", "url", "file_path", "pattern", "message", "prompt", "content", "text"];
  for (const key of candidates) {
    if (typeof obj[key] === "string" && obj[key]) {
      const val = String(obj[key]).replace(/\s+/g, " ").trim().slice(0, 120);
      return `${toolName}: ${val}`;
    }
  }
  const keys = Object.keys(obj);
  if (keys.length > 0) {
    const firstVal = obj[keys[0]];
    if (typeof firstVal === "string") return `${toolName}: ${String(firstVal).slice(0, 120)}`;
  }
  return "";
}

function formatToolInput(input: unknown): string {
  if (input === undefined || input === null) return "(no input)";
  if (typeof input === "string") return input;
  return JSON.stringify(input, null, 2);
}

function formatToolOutput(output: unknown): string {
  if (output === undefined || output === null) return "(no output)";
  if (typeof output === "string") {
    // Avoid dumping huge stdout — truncate at 2000 chars
    if (output.length > 2000) return output.slice(0, 2000) + "\n…(truncated)";
    return output;
  }
  if (Array.isArray(output)) {
    // Anthropic-style content blocks
    const texts: string[] = [];
    for (const block of output) {
      if (block && typeof block === "object" && "text" in block) {
        const t = String((block as Record<string, unknown>).text ?? "");
        if (t.length > 2000) texts.push(t.slice(0, 2000) + "\n…(truncated)");
        else texts.push(t);
      }
    }
    if (texts.length > 0) return texts.join("\n\n");
  }
  return JSON.stringify(output, null, 2);
}
