import type { ApiErrorBody, AuthUser, LoginResponse } from "../types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

// The access token lives in memory only (never localStorage); the httpOnly refresh cookie restores it.
let accessToken: string | null = null;
let refreshing: Promise<LoginResponse | null> | null = null;
let listener: ((user: AuthUser | null) => void) | null = null;

export const session = {
  setToken(token: string | null) {
    accessToken = token;
  },
  /** Notified when a silent refresh succeeds (user) or fails (null) so the UI can follow. */
  onChange(fn: (user: AuthUser | null) => void) {
    listener = fn;
    return () => {
      if (listener === fn) listener = null;
    };
  },
};

async function send(path: string, init?: RequestInit): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  };
  try {
    return await fetch(path, { ...init, credentials: "include", headers });
  } catch {
    throw new ApiError("Cannot reach the server", "network_error", 0);
  }
}

/** Single-flight: concurrent callers (StrictMode, parallel 401s) share one rotation of the refresh cookie. */
export function refreshSession(): Promise<LoginResponse | null> {
  refreshing ??= (async () => {
    try {
      const response = await send("/api/auth/refresh", { method: "POST" });
      if (!response.ok) throw new ApiError("Session expired", "unauthorized", response.status);
      const data = (await response.json()) as LoginResponse;
      accessToken = data.accessToken;
      listener?.(data.user);
      return data;
    } catch {
      accessToken = null;
      listener?.(null);
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response = await send(path, init);
  if (response.status === 401 && accessToken && !path.startsWith("/api/auth/")) {
    if (await refreshSession()) response = await send(path, init);
  }
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(
      body?.error.message ?? `Request failed (${response.status})`,
      body?.error.code ?? "http_error",
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
