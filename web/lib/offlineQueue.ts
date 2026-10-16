// Queue for farmer problem reports submitted while offline. Each report carries a
// client_ref so the API treats replays idempotently. Photos are not queued (size).

import { api, ApiError } from "@/lib/api";

const KEY = "cp-report-queue";

export interface QueuedReport {
  fieldId: string;
  body: Record<string, unknown> & { client_ref: string };
  queuedAt: string;
}

function read(): QueuedReport[] {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "[]") as QueuedReport[];
  } catch {
    return [];
  }
}

function write(items: QueuedReport[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* ignore */
  }
}

export function newClientRef(): string {
  const a = new Uint8Array(12);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function enqueue(r: QueuedReport): void {
  write([...read(), r]);
}

export function pending(): QueuedReport[] {
  return read();
}

/** Try to send queued reports. Network failures keep them queued; validation errors drop them. */
export async function flush(): Promise<{ sent: number; remaining: number; dropped: number }> {
  const items = read();
  const keep: QueuedReport[] = [];
  let sent = 0;
  let dropped = 0;
  for (const it of items) {
    try {
      await api(`/api/v1/fields/${it.fieldId}/reports`, { method: "POST", body: it.body });
      sent++;
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 401 && e.status !== 429) dropped++;
      else keep.push(it);
    }
  }
  write(keep);
  return { sent, remaining: keep.length, dropped };
}
