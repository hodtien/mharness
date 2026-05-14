// TypeScript counterpart of src/openharness/ui/protocol.py.
// Hand-maintained but small enough to keep in sync. Run `oh webui` and check
// the network tab if anything diverges.

export type Role = "system" | "user" | "assistant" | "tool" | "tool_result" | "log";

export interface TranscriptItem {
  role: Role;
  text: string;
  tool_name?: string | null;
  tool_input?: Record<string, unknown> | null;
  is_error?: boolean | null;
}

export interface TaskSnapshot {
  id: string;
  type: string;
  status: string;
  description: string;
  metadata: Record<string, string>;
}

export interface AppStatePayload {
  model?: string;
  cwd?: string;
  provider?: string;
  active_profile?: string;
  auth_status?: string;
  base_url?: string;
  permission_mode?: string;
  theme?: string;
  vim_enabled?: boolean;
  voice_enabled?: boolean;
  voice_available?: boolean;
  voice_reason?: string;
  fast_mode?: boolean;
  effort?: string;
  passes?: number;
  mcp_connected?: number;
  mcp_failed?: number;
  bridge_sessions?: number;
  output_style?: string;
  keybindings?: Record<string, string>;
  config_dir?: string;
}

export type BackendEventType =
  | "ready"
  | "state_snapshot"
  | "tasks_snapshot"
  | "transcript_item"
  | "compact_progress"
  | "assistant_delta"
  | "assistant_complete"
  | "line_complete"
  | "tool_started"
  | "tool_completed"
  | "clear_transcript"
  | "modal_request"
  | "select_request"
  | "todo_update"
  | "plan_mode_change"
  | "swarm_status"
  | "error"
  | "shutdown"
  | "project_switched";

export interface BackendEvent {
  type: BackendEventType;
  message?: string;
  item?: TranscriptItem;
  state?: AppStatePayload;
  tasks?: TaskSnapshot[];
  mcp_servers?: Array<Record<string, unknown>>;
  bridge_sessions?: Array<Record<string, unknown>>;
  commands?: string[];
  modal?: {
    kind?: "permission" | "question" | "select";
    request_id?: string;
    tool_name?: string;
    reason?: string;
    question?: string;
    title?: string;
    command?: string;
  };
  select_options?: Array<{
    value: string;
    label?: string;
    description?: string;
    active?: boolean;
  }>;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  output?: string;
  is_error?: boolean;
  todo_markdown?: string;
  plan_mode?: string;
  // compact_progress
  compact_phase?: string;
  compact_trigger?: string;
  attempt?: number;
  compact_checkpoint?: string;
  compact_metadata?: Record<string, unknown>;
  // swarm_status
  swarm_teammates?: Array<Record<string, unknown>>;
  swarm_notifications?: Array<Record<string, unknown>>;
  // project_switched
  project_id?: string;
  project_path?: string;
}

export type FrontendRequestType =
  | "submit_line"
  | "permission_response"
  | "question_response"
  | "list_sessions"
  | "select_command"
  | "apply_select_command"
  | "interrupt"
  | "shutdown";

export interface FrontendRequest {
  type: FrontendRequestType;
  line?: string;
  command?: string;
  value?: string;
  request_id?: string;
  allowed?: boolean;
  answer?: string;
}
