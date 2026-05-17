import type { BackendEvent, FrontendRequest } from "./types";

const TOKEN_STORAGE_KEY = "oh_token";
const REFRESH_TOKEN_STORAGE_KEY = "oh_refresh_token";
const ACCESS_EXPIRES_STORAGE_KEY = "oh_access_expires_at";
const REFRESH_EXPIRES_STORAGE_KEY = "oh_refresh_expires_at";
const DEFAULT_PASSWORD_STORAGE_KEY = "oh_is_default_password";
const TOKEN_COOKIE_NAME = "oh_token";

export interface AuthSessionSnapshot {
  authenticated: boolean;
  isDefaultPassword: boolean;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  access_expires_in: number;
  refresh_expires_in: number;
  is_default_password: boolean;
}

export type RefreshResponse = Omit<LoginResponse, "is_default_password"> & {
  is_default_password?: boolean;
};

export interface AuthStatusResponse {
  is_default_password?: boolean;
}

interface ApiRequestInit extends RequestInit {
  auth?: boolean;
  retryOnUnauthorized?: boolean;
}

class AuthenticationRequiredError extends Error {
  constructor() {
    super("Authentication required");
    this.name = "AuthenticationRequiredError";
  }
}

const authListeners = new Set<(snapshot: AuthSessionSnapshot) => void>();
let refreshPromise: Promise<boolean> | null = null;

function readDefaultPasswordState(): boolean {
  return localStorage.getItem(DEFAULT_PASSWORD_STORAGE_KEY) === "true";
}

function notifyAuthChanged(authenticated: boolean): void {
  const snapshot = { authenticated, isDefaultPassword: readDefaultPasswordState() };
  authListeners.forEach((listener) => listener(snapshot));
}

export function subscribeAuthChanges(listener: (snapshot: AuthSessionSnapshot) => void): () => void {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

function persistAccessToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${TOKEN_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; SameSite=Strict${secure}`;
}

function persistAuthTokens(tokens: RefreshResponse): AuthSessionSnapshot {
  persistAccessToken(tokens.access_token);
  localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, tokens.refresh_token);
  localStorage.setItem(ACCESS_EXPIRES_STORAGE_KEY, String(Date.now() + tokens.access_expires_in * 1000));
  localStorage.setItem(REFRESH_EXPIRES_STORAGE_KEY, String(Date.now() + tokens.refresh_expires_in * 1000));
  if (typeof tokens.is_default_password === "boolean") {
    localStorage.setItem(DEFAULT_PASSWORD_STORAGE_KEY, String(tokens.is_default_password));
  }
  const snapshot = { authenticated: true, isDefaultPassword: readDefaultPasswordState() };
  notifyAuthChanged(true);
  return snapshot;
}

function persistAuthStatus(status: AuthStatusResponse): void {
  if (typeof status.is_default_password === "boolean") {
    localStorage.setItem(DEFAULT_PASSWORD_STORAGE_KEY, String(status.is_default_password));
    notifyAuthChanged(Boolean(localStorage.getItem(TOKEN_STORAGE_KEY)));
  }
}

function readExpiry(storageKey: string): number | null {
  const raw = localStorage.getItem(storageKey);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function isExpiringSoon(storageKey: string): boolean {
  const expiry = readExpiry(storageKey);
  return expiry !== null && Date.now() + 5000 >= expiry;
}

function getRefreshToken(): string {
  if (isExpiringSoon(REFRESH_EXPIRES_STORAGE_KEY)) {
    return "";
  }
  return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) || "";
}

export function getToken(): string {
  // 1. ?token=... in URL takes priority (one-time bootstrap from terminal).
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    persistAccessToken(fromUrl);
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
  persistAccessToken(token);
  notifyAuthChanged(true);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  localStorage.removeItem(ACCESS_EXPIRES_STORAGE_KEY);
  localStorage.removeItem(REFRESH_EXPIRES_STORAGE_KEY);
  localStorage.removeItem(DEFAULT_PASSWORD_STORAGE_KEY);
  document.cookie = `${TOKEN_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Strict`;
  notifyAuthChanged(false);
}

async function refreshAuthSessionOnce(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    clearToken();
    return false;
  }
  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      clearToken();
      return false;
    }
    persistAuthTokens((await res.json()) as RefreshResponse);
    return true;
  } catch {
    clearToken();
    return false;
  }
}

export async function refreshAuthSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshAuthSessionOnce().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function ensureFreshAccessToken(): Promise<void> {
  if (getToken() && isExpiringSoon(ACCESS_EXPIRES_STORAGE_KEY)) {
    await refreshAuthSession();
  }
}

function buildHeaders(init: ApiRequestInit, token: string): Headers {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export async function apiRequest(path: string, init: ApiRequestInit = {}): Promise<Response> {
  const { auth = true, retryOnUnauthorized = true, ...requestInit } = init;
  if (auth) {
    await ensureFreshAccessToken();
  }
  const makeRequest = () => {
    const token = auth ? getToken() : "";
    return fetch(path, {
      ...requestInit,
      headers: buildHeaders(init, token),
    });
  };

  let res = await makeRequest();
  if (auth && retryOnUnauthorized && res.status === 401) {
    const refreshed = await refreshAuthSession();
    if (!refreshed) {
      throw new AuthenticationRequiredError();
    }
    res = await makeRequest();
    if (res.status === 401) {
      clearToken();
      throw new AuthenticationRequiredError();
    }
  }
  return res;
}

export async function apiFetch<T>(path: string, init?: ApiRequestInit): Promise<T> {
  const res = await apiRequest(path, init);
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

export async function bootstrapAuthSession(): Promise<AuthSessionSnapshot> {
  const accessToken = getToken();
  if (!accessToken && getRefreshToken()) {
    const refreshed = await refreshAuthSession();
    return { authenticated: refreshed, isDefaultPassword: readDefaultPasswordState() };
  }
  if (!accessToken) {
    return { authenticated: false, isDefaultPassword: false };
  }
  try {
    const status = await api.authStatus();
    persistAuthStatus(status);
    return { authenticated: true, isDefaultPassword: readDefaultPasswordState() };
  } catch (error) {
    if (error instanceof AuthenticationRequiredError) {
      return { authenticated: false, isDefaultPassword: false };
    }
    return { authenticated: true, isDefaultPassword: readDefaultPasswordState() };
  }
}

export interface ModesPayload {
  permission_mode: string;
  model?: string;
  fast_mode: boolean;
  vim_enabled: boolean;
  notifications_enabled?: boolean;
  auto_compact_threshold_tokens?: number | null;
  effort: string;
  passes: number;
  output_style: string;
  theme: string;
}

export interface ModesPatch {
  permission_mode?: string;
  model?: string;
  effort?: string;
  passes?: number;
  fast_mode?: boolean;
  vim_enabled?: boolean;
  notifications_enabled?: boolean;
  auto_compact_threshold_tokens?: number | null;
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
  health_label?: "Ready" | "Healthy" | "Probe failing";
  reachable?: boolean | null;
  probed?: boolean | null;
  last_verified_at?: string | null;
  verification_latency_ms?: number | null;
  model_count?: number | null;
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
  latency_ms?: number;
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

export interface AutopilotPolicyAgentsResponse {
  implement_agent: string | null;
  review_agent: string | null;
  operational_agents: string[];
}

// ---------------- Cron Schedule Config ----------------

export interface CronConfigResponse {
  enabled: boolean;
  scan_cron: string;
  tick_cron: string;
  timezone: string;
  install_mode: string;
  project_path: string;
  scheduler_running: boolean;
  scan_cron_description: string;
  tick_cron_description: string;
  next_scan_runs: string[];
  next_tick_runs: string[];
  install_result?: {
    success: boolean;
    message: string;
    scan_installed: boolean;
    tick_installed: boolean;
    scan_line: string;
    tick_line: string;
    manual_commands: string[];
  };
}

export interface CronConfigPatch {
  enabled?: boolean;
  scan_cron?: string;
  tick_cron?: string;
  timezone?: string;
  install_mode?: string;
}

// ---------------- Scheduler Diagnostics ----------------

export interface SchedulerDiagnosticsResponse {
  scheduling_feature_enabled: boolean;
  cron_entries_installed: number;
  cron_entries_enabled: number;
  scheduler_process_alive: boolean;
  scheduler_pid: number | null;
  last_tick_at: string | null;
  last_scan_at: string | null;
  active_worker_count: number;
  stale_worker_count: number;
  last_error: string | null;
}

// ---------------- Projects ----------------

export interface Project {
  id: string;
  name: string;
  path: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
  is_active: boolean;
  exists?: boolean;
  is_temp_like?: boolean;
  is_worktree_like?: boolean;
  last_seen_at?: string | null;
}

export interface ProjectsResponse {
  projects: Project[];
  active_project_id: string | null;
}

export interface ProjectCleanupRequest {
  missing_only?: boolean;
  temp_like_only?: boolean;
  worktree_like_only?: boolean;
  confirmed?: boolean;
}

export interface ProjectCreate {
  name: string;
  path: string;
  description?: string | null;
}

export interface ProjectUpdate {
  name?: string | null;
  description?: string | null;
}

export const api = {
  login: async (password: string) => {
    const result = await apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
      auth: false,
      retryOnUnauthorized: false,
    });
    return persistAuthTokens(result);
  },
  authStatus: () => apiFetch<AuthStatusResponse>("/api/auth/status"),
  logout: async () => {
    try {
      await apiFetch<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
    } finally {
      clearToken();
    }
  },
  changePassword: async (oldPassword: string, newPassword: string) => {
    const result = await apiFetch<{ ok: boolean }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
    localStorage.setItem(DEFAULT_PASSWORD_STORAGE_KEY, "false");
    notifyAuthChanged(true);
    return result;
  },
  health: () => apiFetch<{ status: string; version: string }>("/api/health"),
  meta: () => apiFetch<{ cwd?: string; model?: string; permission_mode?: string }>("/api/meta"),
  createSession: (resumeId?: string, projectId?: string) => {
    const params = new URLSearchParams();
    if (resumeId) params.set("resume_id", resumeId);
    if (projectId) params.set("project_id", projectId);
    const query = params.toString() ? `?${params.toString()}` : "";
    return apiFetch<{ session_id: string; resumed_from?: string | null }>(`/api/sessions${query}`, {
      method: "POST",
      body: resumeId ? JSON.stringify({ resume_id: resumeId }) : undefined,
      headers: resumeId ? { "Content-Type": "application/json" } : undefined,
    });
  },
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
  getCronConfig: () => apiFetch<CronConfigResponse>("/api/cron/config"),
  getSchedulerDiagnostics: () => apiFetch<SchedulerDiagnosticsResponse>("/api/cron/diagnostics"),
  patchCronConfig: (patch: CronConfigPatch) =>
    apiFetch<CronConfigResponse>("/api/cron/config", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
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
  verifyAllProviders: () =>
    apiFetch<{ results: Record<string, ProviderVerifyResponse> }>("/api/providers/verify", {
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
  getAutopilotPolicyAgents: () => apiFetch<AutopilotPolicyAgentsResponse>("/api/pipeline/policy/agents"),
  getAgent: (name: string) => apiFetch<AgentDetail>(`/api/agents/${encodeURIComponent(name)}`),
  patchAgent: (name: string, patch: AgentPatch) =>
    apiFetch<AgentProfile>(`/api/agents/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  cloneAgent: (name: string, newName: string) =>
    apiFetch<AgentProfile>(`/api/agents/${encodeURIComponent(name)}/clone`, {
      method: "POST",
      body: JSON.stringify({ new_name: newName }),
    }),
  validateAgent: (name: string, patch: AgentPatch) =>
    apiFetch<{ valid: boolean; errors: string[] }>(
      `/api/agents/${encodeURIComponent(name)}/validate`,
      { method: "POST", body: JSON.stringify(patch) },
    ),
  listProjects: () => apiFetch<ProjectsResponse>("/api/projects"),
  getProject: (projectId: string) =>
    apiFetch<Project>(`/api/projects/${encodeURIComponent(projectId)}`),
  createProject: (body: ProjectCreate) =>
    apiFetch<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
  updateProject: (projectId: string, body: ProjectUpdate) =>
    apiFetch<Project>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    }),
  deleteProject: (projectId: string) =>
    apiFetch<{ ok: boolean }>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "DELETE",
    }),
  cleanupProjects: (body: ProjectCleanupRequest) =>
    apiFetch<{ ok: boolean; preview_count?: number; deleted_count?: number; deleted_ids?: string[] }>(
      "/api/projects/cleanup",
      { method: "POST", body: JSON.stringify(body) },
    ),
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
  let refreshedAuth = false;
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
      if (!manuallyClosed && ev.code === 1008 && !refreshedAuth) {
        refreshedAuth = true;
        void refreshAuthSession().then((refreshed) => {
          if (!refreshed || manuallyClosed) return;
          currentState = "connecting";
          onStatus("connecting", "refreshing auth");
          ws = new WebSocket(url);
          attach(ws);
        });
        return;
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
