// Thin API client. Tokens live in sessionStorage (cleared when the tab closes) — see
// docs/SECURITY_AND_PRIVACY.md for the trade-off and the httpOnly-cookie roadmap item.

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "cp-token";
const CACHE_PREFIX = "cp-cache:";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

function storage(kind: "session" | "local"): Storage | null {
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return storage("session")?.getItem(TOKEN_KEY) ?? null;
}

export function setToken(token: string | null): void {
  const s = storage("session");
  if (!s) return;
  if (token) s.setItem(TOKEN_KEY, token);
  else s.removeItem(TOKEN_KEY);
}

export function clearLocalData(): void {
  setToken(null);
  const l = storage("local");
  if (!l) return;
  Object.keys(l)
    .filter((k) => k.startsWith(CACHE_PREFIX) || k === "cp-report-queue")
    .forEach((k) => l.removeItem(k));
}

export async function api<T>(path: string, init: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (init.form) body = init.form;
  else if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  const res = await fetch(`${API_BASE}${path}`, { method: init.method ?? "GET", headers, body });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : `HTTP ${res.status}`;
    if (res.status === 401) setToken(null);
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export interface Cached<T> {
  data: T;
  fromCache: boolean;
  fetchedAt: string;
}

/** GET with an offline fallback. Cached copies always carry the time they were fetched,
 * and the UI must display it — a cached assessment must never look current. */
export async function apiCached<T>(path: string): Promise<Cached<T>> {
  const l = storage("local");
  try {
    const data = await api<T>(path);
    const fetchedAt = new Date().toISOString();
    try {
      l?.setItem(CACHE_PREFIX + path, JSON.stringify({ data, fetchedAt }));
    } catch {
      /* quota exceeded: caching is best-effort */
    }
    return { data, fromCache: false, fetchedAt };
  } catch (err) {
    const isNetwork = !(err instanceof ApiError);
    const raw = isNetwork ? l?.getItem(CACHE_PREFIX + path) : null;
    if (raw) {
      const parsed = JSON.parse(raw) as { data: T; fetchedAt: string };
      return { data: parsed.data, fromCache: true, fetchedAt: parsed.fetchedAt };
    }
    throw err;
  }
}
