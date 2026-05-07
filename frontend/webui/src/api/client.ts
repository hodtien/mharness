import type { BackendEvent, FrontendRequest } from "./types";

const TOKEN_STORAGE_KEY = "oh_token";
const TOKEN_COOKIE_NAME = "oh_token";

function persistToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${TOKEN_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; SameSite=Strict${secure}`;
}

export function getToken(): string {
  // 1. ?token=... in URL takes priority (one-time bootstrap from terminal).
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    persistToken(fromUrl);
    // Clean URL so the token isn't visible / leaked in history.
    params.delete("token");
    const cleaned = `${window.location.pathname}${
      params.toString() ? "?" + params.toString() : ""
    }${window.location.hash}`;
    window.history.replaceState({}, "", cleaned);
    return fromUrl;
  }
  return localStorage.getItem(TOKEN_STORAGE_KEY) || "";
}

export function setToken(token: string): void {
  persistToken(token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  document.cookie = `${TOKEN_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Strict`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  const contentLength = res.headers?.get?.("content-length");
  if (contentLength === "0") {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export interface ModesPayload {
  permission_mode: string;
  fast_mode: boolean;
  vim_enabled: boolean;
  effort: string;
  passes: number;
  output_style: string;
  theme: string;
}

export interface ModesPatch {
  permission_mode?: string;
  effort?: string;
  passes?: number;
  fast_mode?: boolean;
  vim_enabled?: boolean;
  output_style?: string;
  theme?: string;
}

export interface ProviderProfile {
  id: string;
  label: string;
  provider: string;
  api_format: string;
  default_model: string;
  base_url?: string | null;
  has_credentials: boolean;
  is_active: boolean;
}

export interface ProviderListResponse {
  providers: ProviderProfile[];
}

export interface ProviderCredentialsPatch {
  api_key?: string;
  base_url?: string;
}

export interface ProviderVerifyResponse {
  ok: boolean;
  error?: string;
  models?: string[];
}

export interface ProviderActivateResponse {
  ok: boolean;
  model?: string;
}

export interface ModelProfile {
  id: string;
  label: string;
  context_window?: number | null;
  is_default: boolean;
  is_custom: boolean;
}

export type ModelsResponse = Record<string, ModelProfile[]>;

export interface CustomModelBody {
  provider: string;
  model_id: string;
  label?: string;
  context_window?: number;
}

export interface AgentProfile {
  name: string;
  description: string;
  model?: string | null;
  effort?: string | null;
  permission_mode?: string | null;
  tools_count?: number | null;
  has_system_prompt: boolean;
  source_file?: string | null;
}

export interface AgentDetail {
  name: string;
  description: string;
  system_prompt: string | null;
  tools: string[] | null;
  model: string | null;
  effort: string | null;
  permission_mode: string | null;
  source_file: string | null;
  has_system_prompt: boolean;
}

export interface AgentPatch {
  model?: string;
  effort?: string;
  permission_mode?: string;
}

// ---------------- Projects ----------------

export interface ProjectProfile {
  id: string;
  name: string;
  path: string;
  description: string | null;
  created_at: string | null;
}

export interface ProjectsResponse {
  projects: ProjectProfile[];
  active_project_id: string | null;
}

export interface ProjectCreateBody {
  name: string;
  path: string;
  description?: string | null;
}

export interface ProjectUpdateBody {
  name?: string | null;
  description?: string | null;
}

export const api = {
  health: () => apiFetch<{ status: string; version: string }>("/api/health"),
  meta: () => apiFetch<{ cwd?: string; model?: string; permission_mode?: string }>("/api/meta"),
  createSession: (resumeId?: string) =>
    apiFetch<{ session_id: string; resumed_from?: string | null }>("/api/sessions", {
      method: "POST",
      body: resumeId ? JSON.stringify({ resume_id: resumeId }) : undefined,
      headers: resumeId ? { "Content-Type": "application/json" } : undefined,
    }),
  listSessions: () =>
    apiFetch<{ sessions: Array<{ id: string; created_at: number; active: boolean }> }>(
      "/api/sessions",
    ),
  listTasks: () =>
    apiFetch<{ tasks: Array<{ id: string; type: string; status: string; description: string }> }>(
      "/api/tasks",
    ),
  listCron: () =>
    apiFetch<{ jobs: Array<Record<string, unknown>>; error?: string }>("/api/cron/jobs"),
  getModes: () => apiFetch<ModesPayload>("/api/modes"),
  patchModes: (patch: ModesPatch) =>
    apiFetch<ModesPayload>("/api/modes", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  listProviders: () => apiFetch<ProviderListResponse>("/api/providers"),
  saveProviderCredentials: (name: string, patch: ProviderCredentialsPatch) =>
    apiFetch<{ ok: boolean; api_key_suffix?: string; base_url?: string }>(
      `/api/providers/${encodeURIComponent(name)}/credentials`,
      {
        method: "POST",
        body: JSON.stringify(patch),
      },
    ),
  verifyProvider: (name: string) =>
    apiFetch<ProviderVerifyResponse>(`/api/providers/${encodeURIComponent(name)}/verify`, {
      method: "POST",
    }),
  activateProvider: (name: string) =>
    apiFetch<ProviderActivateResponse>(`/api/providers/${encodeURIComponent(name)}/activate`, {
      method: "POST",
    }),
  listModels: () => apiFetch<ModelsResponse>("/api/models"),
  addCustomModel: (body: CustomModelBody) =>
    apiFetch<{ ok: boolean; provider: string; model_id: string }>("/api/models", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchPipelineCardModel: (cardId: string, model: string | null) =>
    apiFetch<Record<string, unknown>>(`/api/pipeline/cards/${encodeURIComponent(cardId)}/model`, {
      method: "PATCH",
      body: JSON.stringify({ model }),
    }),
  deleteCustomModel: (provider: string, modelId: string) =>
    apiFetch<{ ok: boolean; provider: string; model_id: string }>(
      `/api/models/${encodeURIComponent(provider)}/${encodeURIComponent(modelId)}`,
      { method: "DELETE" },
    ),
  listAgents: () => apiFetch<AgentProfile[]>("/api/agents"),
  getAgent: (name: string) => apiFetch<AgentDetail>(`/api/agents/${encodeURIComponent(name)}`),
  patchAgent: (name: string, patch: AgentPatch) =>
    apiFetch<AgentProfile>(`/api/agents/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  listProjects: () => apiFetch<ProjectsResponse>("/api/projects"),
  createProject: (body: ProjectCreateBody) =>
    apiFetch<ProjectProfile>("/api/projects", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
  patchProject: (projectId: string, body: ProjectUpdateBody) =>
    apiFetch<ProjectProfile>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
  deleteProject: (projectId: string) =>
    apiFetch<{ ok: boolean }>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "DELETE",
    }),
  activateProject: (projectId: string) =>
    apiFetch<{ ok: boolean }>(`/api/projects/${encodeURIComponent(projectId)}/activate`, {
      method: "POST",
    }),
};

// ---------------- WebSocket session ----------------

export interface WsHandle {
  send(req: FrontendRequest): void;
  close(): void;
  readonly state: () => "connecting" | "open" | "closed";
}

// WebSocket close codes that should not trigger reconnect attempts:
//   1000 — client-side manual close (we already handle this via manuallyClosed)
//   1008 — policy violation (auth failure / unknown session)
//   1011 — server told us it had an unrecoverable error
const NON_RETRYABLE_CLOSE_CODES = new Set([1008, 1011]);

export function openWebSocket(
  sessionId: string,
  onEvent: (evt: BackendEvent) => void,
  onStatus: (status: "connecting" | "open" | "closed", detail?: string) => void,
): WsHandle {
  getToken();
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/api/ws/${sessionId}`;
  let ws: WebSocket = new WebSocket(url);
  let currentState: "connecting" | "open" | "closed" = "connecting";
  let manuallyClosed = false;
  let reconnectAttempts = 0;
  const MAX_RETRIES = 2;

  const attach = (socket: WebSocket) => {
    socket.onopen = () => {
      currentState = "open";
      reconnectAttempts = 0;
      onStatus("open");
    };
    socket.onmessage = (msg) => {
      try {
        const evt = JSON.parse(msg.data) as BackendEvent;
        onEvent(evt);
      } catch (err) {
        console.error("bad event", msg.data, err);
      }
    };
    socket.onclose = (ev) => {
      currentState = "closed";
      // Distinguish expected closes (clean 1000, explicit client close) from
      // abnormal/aborted closes (1006, 1005) that warrant retry or a banner.
      if (ev.code === 1001) {
        // 1001 = "going away" — server is shutting down; treat as non-fatal.
        onStatus("closed", "Server restarting");
      } else if (ev.code === 1008) {
        // 1008 = policy violation (auth failure)
        onStatus("closed", "Authentication failed (code=1008)");
      } else if (ev.code === 1011) {
        // 1011 = unexpected server error
        onStatus("closed", "Server error (code=1011)");
      } else if (ev.code !== 1000 && !manuallyClosed) {
        onStatus("closed", `code=${ev.code}`);
      } else if (manuallyClosed) {
        onStatus("closed");
      } else {
        onStatus("closed", `code=${ev.code}`);
      }
      if (!manuallyClosed && ev.code !== 1000 && !NON_RETRYABLE_CLOSE_CODES.has(ev.code)) {
        reconnectAttempts++;
        if (reconnectAttempts <= MAX_RETRIES) {
          setTimeout(() => {
            if (manuallyClosed) return;
            currentState = "connecting";
            onStatus("connecting", "reconnecting");
            ws = new WebSocket(url);
            attach(ws);
          }, 1500);
        }
      }
    };
    socket.onerror = () => {
      onStatus(currentState, "error");
    };
  };
  attach(ws);

  return {
    send(req) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(req));
      }
    },
    close() {
      manuallyClosed = true;
      ws.close(1000, "client closing");
    },
    state: () => currentState,
  };
}
