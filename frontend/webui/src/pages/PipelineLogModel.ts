export interface StreamEvent {
  ts: number;
  kind: string;
  payload: Record<string, unknown>;
  index?: number;
}

export type LogFilter = "all" | "agent" | "tools" | "phases" | "errors";

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
  details: LogDetailPayload[];
  rawEvents: StreamEvent[];
  searchText: string;
}

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

export const LOG_FILTERS: { id: LogFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "agent", label: "Agent" },
  { id: "tools", label: "Tools" },
  { id: "phases", label: "Phases" },
  { id: "errors", label: "Errors" },
];

export function eventsToLogPhaseGroups(events: StreamEvent[]): LogPhaseGroup[] {
  const steps: LogStep[] = [];
  const pendingTools = new Map<string, LogStep[]>();
  let textBuffer: { event: StreamEvent; index: number; text: string; phase: string } | null = null;

  const flushText = () => {
    if (!textBuffer) return;
    steps.push(createLogStep({
      id: `${textBuffer.index}-agent-${textBuffer.phase}`,
      type: "agent",
      phase: textBuffer.phase,
      title: `Agent · ${textBuffer.phase}`,
      summary: summarizeText(textBuffer.text) || "Agent output",
      timestamp: textBuffer.event.ts,
      isError: false,
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
        textBuffer = {
          event: textBuffer.event,
          index: textBuffer.index,
          phase: textBuffer.phase,
          text: textBuffer.text + text,
        };
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
        const stepIndex = steps.findIndex((step) => step.id === pending.id);
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
  return groupLogStepsByPhase(steps);
}

export function filterLogPhaseGroups(phases: LogPhaseGroup[], activeFilter: LogFilter, normalizedQuery: string): LogPhaseGroup[] {
  return phases
    .map((phase) => {
      const steps = phase.steps.filter((step) => {
        const matchesFilter =
          activeFilter === "all" ||
          (activeFilter === "agent" && step.type === "agent") ||
          (activeFilter === "tools" && step.type === "tool") ||
          (activeFilter === "phases" && step.type === "phase") ||
          (activeFilter === "errors" && step.isError);
        return matchesFilter && (!normalizedQuery || step.searchText.includes(normalizedQuery));
      });
      return { ...phase, steps };
    })
    .filter((phase) => phase.steps.length > 0 || (activeFilter === "errors" && phase.hasErrors));
}

export function getSelectedLogStep(phases: LogPhaseGroup[], selectedStepId: string | null): LogStep | null {
  const steps = phases.flatMap((phase) => phase.steps);
  return steps.find((step) => step.id === selectedStepId) ?? steps[0] ?? null;
}

function createLogStep(input: Omit<LogStep, "searchText">): LogStep {
  const raw = input.rawEvents.map((event) => `${event.kind}\n${JSON.stringify(event.payload, null, 2)}`).join("\n\n");
  const detailText = input.details.map((detail) => detail.value).join("\n");
  return {
    ...input,
    searchText: `${input.phase} ${input.title} ${input.summary} ${detailText} ${raw}`.toLowerCase(),
  };
}

function eventToLogStep(event: StreamEvent, phase: string, index: number): LogStep {
  const { kind, payload } = event;
  const rawPayload = JSON.stringify(payload, null, 2);
  if (kind === "phase_start") {
    const attempt = typeof payload?.attempt === "number" ? ` · attempt ${payload.attempt}` : "";
    return createLogStep({
      id: getEventId(event, index),
      type: "phase",
      phase,
      title: `${String(payload?.phase ?? "phase")}${attempt}`,
      summary: "Phase started",
      timestamp: event.ts,
      isError: false,
      details: [{ label: "Payload", value: rawPayload }],
      rawEvents: [event],
    });
  }
  if (kind === "phase_end") {
    const ok = payload?.ok !== false;
    return createLogStep({
      id: getEventId(event, index),
      type: "phase",
      phase,
      title: `${String(payload?.phase ?? "phase")} ended`,
      summary: ok ? "Phase completed" : "Phase failed",
      timestamp: event.ts,
      isError: !ok,
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
    details: [{ label: "Payload", value: rawPayload }],
    rawEvents: [event],
  });
}

function toolCallToStep(event: StreamEvent, phase: string, index: number): LogStep {
  const name = String(event.payload?.name ?? "tool");
  const input = JSON.stringify(event.payload, null, 2);
  return createLogStep({
    id: `${getEventId(event, index)}-tool`,
    type: "tool",
    phase,
    title: `Tool · ${name}`,
    summary: String(event.payload?.input_summary ?? "Tool called"),
    timestamp: event.ts,
    isError: false,
    details: [{ label: "Input", value: input }],
    rawEvents: [event],
  });
}

function toolResultToStep(event: StreamEvent, phase: string, index: number): LogStep {
  const name = String(event.payload?.name ?? "tool");
  const output = JSON.stringify(event.payload, null, 2);
  const isError = event.payload?.is_error === true;
  return createLogStep({
    id: `${getEventId(event, index)}-tool-result`,
    type: "tool",
    phase,
    title: `Tool result · ${name}`,
    summary: String(event.payload?.summary ?? (isError ? "Tool failed" : "Tool returned")),
    timestamp: event.ts,
    isError,
    details: [{ label: "Output", value: output }],
    rawEvents: [event],
  });
}

function pairToolResult(step: LogStep, event: StreamEvent): LogStep {
  const output = JSON.stringify(event.payload, null, 2);
  const isError = event.payload?.is_error === true;
  return createLogStep({
    ...step,
    summary: String(event.payload?.summary ?? step.summary),
    isError,
    details: [...step.details, { label: "Output", value: output }],
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
    const hasErrors = phaseSteps.some((step) => step.isError);
    const searchText = phaseSteps.map((step) => step.searchText).join(" ");
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

function summarizeText(text: string): string {
  return text.trim().replace(/\s+/g, " ").slice(0, 180);
}
