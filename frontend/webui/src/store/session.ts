import { create } from "zustand";
import type { AppStatePayload, BackendEvent, TaskSnapshot, TranscriptItem } from "../api/types";

export interface DisplayItem extends TranscriptItem {
  id: string;
  pending?: boolean; // true while assistant is streaming
}

interface PermissionRequest {
  request_id: string;
  tool_name: string;
  reason: string;
}

interface QuestionRequest {
  request_id: string;
  question: string;
}

export interface SelectOption {
  value: string;
  label?: string;
  description?: string;
  active?: boolean;
}

interface SelectRequest {
  title: string;
  command: string;
  options: SelectOption[];
}

interface SessionStore {
  connectionStatus: "connecting" | "open" | "closed";
  appState: AppStatePayload | null;
  transcript: DisplayItem[];
  tasks: TaskSnapshot[];
  busy: boolean;
  errorBanner: string | null;
  pendingPermission: PermissionRequest | null;
  pendingQuestion: QuestionRequest | null;
  pendingSelect: SelectRequest | null;
  // setters
  setStatus: (s: "connecting" | "open" | "closed", detail?: string) => void;
  ingest: (evt: BackendEvent) => void;
  appendUser: (text: string) => void;
  setError: (msg: string | null) => void;
  reset: () => void;
}

const newId = () => Math.random().toString(36).slice(2, 10);

export const useSession = create<SessionStore>((set, get) => ({
  connectionStatus: "connecting",
  appState: null,
  transcript: [],
  tasks: [],
  busy: false,
  errorBanner: null,
  pendingPermission: null,
  pendingQuestion: null,
  pendingSelect: null,

  setStatus: (s, detail) =>
    set((state) => ({
      connectionStatus: s,
      errorBanner:
        s === "closed" && detail
          ? `Connection closed (${detail})`
          : s === "open"
            ? null
            : state.errorBanner,
    })),

  appendUser: (text) =>
    set((state) => ({
      transcript: [...state.transcript, { id: newId(), role: "user", text }],
      busy: true,
    })),

  setError: (msg) => set({ errorBanner: msg }),

  reset: () =>
    set({
      transcript: [],
      tasks: [],
      busy: false,
      errorBanner: null,
      pendingPermission: null,
      pendingQuestion: null,
      pendingSelect: null,
    }),

  ingest: (evt) => {
    const state = get();
    switch (evt.type) {
      case "ready": {
        set({
          appState: evt.state || null,
          tasks: evt.tasks || [],
          transcript: [
            {
              id: newId(),
              role: "system",
              text: `Connected • model=${evt.state?.model || "?"} • cwd=${evt.state?.cwd || "."}`,
            },
          ],
        });
        break;
      }
      case "state_snapshot": {
        set({ appState: evt.state || state.appState });
        break;
      }
      case "tasks_snapshot": {
        set({ tasks: evt.tasks || [] });
        break;
      }
      case "transcript_item": {
        if (!evt.item) return;
        const item: DisplayItem = { ...evt.item, id: newId() };
        set({ transcript: [...state.transcript, item] });
        break;
      }
      case "assistant_delta": {
        // Stream into the trailing pending assistant bubble (create one if missing).
        const last = state.transcript[state.transcript.length - 1];
        if (last && last.role === "assistant" && last.pending) {
          const updated = [...state.transcript];
          updated[updated.length - 1] = {
            ...last,
            text: last.text + (evt.message || ""),
          };
          set({ transcript: updated });
        } else {
          set({
            transcript: [
              ...state.transcript,
              {
                id: newId(),
                role: "assistant",
                text: evt.message || "",
                pending: true,
              },
            ],
          });
        }
        break;
      }
      case "assistant_complete": {
        // Finalize the last pending assistant bubble.
        const last = state.transcript[state.transcript.length - 1];
        const finalText = evt.message || evt.item?.text || (last?.text ?? "");
        if (last && last.role === "assistant" && last.pending) {
          const updated = [...state.transcript];
          updated[updated.length - 1] = { ...last, text: finalText, pending: false };
          set({ transcript: updated });
        } else if (finalText) {
          set({
            transcript: [
              ...state.transcript,
              { id: newId(), role: "assistant", text: finalText },
            ],
          });
        }
        break;
      }
      case "tool_started": {
        const text =
          (evt.tool_name || "tool") +
          (evt.tool_input ? " " + JSON.stringify(evt.tool_input) : "");
        set({
          transcript: [
            ...state.transcript,
            {
              id: newId(),
              role: "tool",
              text,
              tool_name: evt.tool_name || null,
              tool_input: evt.tool_input || null,
            },
          ],
        });
        break;
      }
      case "tool_completed": {
        set({
          transcript: [
            ...state.transcript,
            {
              id: newId(),
              role: "tool_result",
              text: evt.output || "",
              tool_name: evt.tool_name || null,
              is_error: evt.is_error,
            },
          ],
        });
        break;
      }
      case "line_complete": {
        set({ busy: false });
        break;
      }
      case "modal_request": {
        const m = evt.modal || {};
        if (m.kind === "permission" && m.request_id) {
          set({
            pendingPermission: {
              request_id: m.request_id,
              tool_name: m.tool_name || "(tool)",
              reason: m.reason || "",
            },
          });
        } else if (m.kind === "question" && m.request_id) {
          set({
            pendingQuestion: {
              request_id: m.request_id,
              question: m.question || "",
            },
          });
        }
        break;
      }
      case "select_request": {
        const m = evt.modal || {};
        if (m.kind === "select" && m.command) {
          set({
            pendingSelect: {
              title: m.title || m.command,
              command: m.command,
              options: evt.select_options || [],
            },
          });
        }
        break;
      }
      case "clear_transcript": {
        set({ transcript: [] });
        break;
      }
      case "error": {
        set({
          errorBanner: evt.message || "Unknown error",
          busy: false,
        });
        break;
      }
      case "shutdown": {
        set({ busy: false, connectionStatus: "closed" });
        break;
      }
      default:
        break;
    }
  },
}));

export function clearPermission() {
  useSession.setState({ pendingPermission: null });
}
export function clearQuestion() {
  useSession.setState({ pendingQuestion: null });
}
export function clearSelect() {
  useSession.setState({ pendingSelect: null });
}
