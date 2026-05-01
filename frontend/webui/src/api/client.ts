import type { BackendEvent, FrontendRequest } from "./types";

const TOKEN_STORAGE_KEY = "oh_token";

export function getToken(): string {
  // 1. ?token=... in URL takes priority (one-time bootstrap from terminal).
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    localStorage.setItem(TOKEN_STORAGE_KEY, fromUrl);
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
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
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
};

// ---------------- WebSocket session ----------------

export interface WsHandle {
  send(req: FrontendRequest): void;
  close(): void;
  readonly state: () => "connecting" | "open" | "closed";
}

export function openWebSocket(
  sessionId: string,
  onEvent: (evt: BackendEvent) => void,
  onStatus: (status: "connecting" | "open" | "closed", detail?: string) => void,
): WsHandle {
  const token = getToken();
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/api/ws/${sessionId}?token=${encodeURIComponent(token)}`;
  let ws: WebSocket = new WebSocket(url);
  let currentState: "connecting" | "open" | "closed" = "connecting";
  let manuallyClosed = false;

  const attach = (socket: WebSocket) => {
    socket.onopen = () => {
      currentState = "open";
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
      onStatus("closed", `code=${ev.code}`);
      if (!manuallyClosed && ev.code !== 1008) {
        // brief retry once
        setTimeout(() => {
          if (manuallyClosed) return;
          currentState = "connecting";
          onStatus("connecting", "reconnecting");
          ws = new WebSocket(url);
          attach(ws);
        }, 1500);
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
      ws.close();
    },
    state: () => currentState,
  };
}
