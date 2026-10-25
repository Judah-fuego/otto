import type { AlertView, Message, State, ToolCall } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  state: () => fetch("/api/state", { cache: "no-store" }).then((r) => json<State>(r)),

  decide: (alertId: string, approved: boolean) =>
    fetch(`/api/alerts/${encodeURIComponent(alertId)}/decision`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approved }),
    }).then((r) => json<AlertView>(r)),

  reopen: (alertId: string) =>
    fetch(`/api/alerts/${encodeURIComponent(alertId)}/reopen`, { method: "POST" }).then((r) => json<AlertView>(r)),

  chat: (messages: Message[]) =>
    fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: messages.map(({ role, content }) => ({ role, content })) }),
    }).then((r) => json<{ text: string; spoken: string | null; calls: ToolCall[] }>(r)),

  simulate: (scenario: string) =>
    fetch(`/api/simulate/${encodeURIComponent(scenario)}`, { method: "POST" }).then((r) => json<AlertView>(r)),

  reset: () => fetch("/api/reset", { method: "POST" }).then((r) => json<unknown>(r)),
};
