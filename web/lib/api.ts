import type { AlertView, Flight, Message, State, ToolCall, Trajectory } from "./types";

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

  selectMission: (id: string) =>
    fetch("/api/mission", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id }),
    }).then((r) => json<Trajectory>(r)),

  flightStart: (speed = 1) =>
    fetch("/api/flight/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ speed }),
    }).then((r) => json<Flight>(r)),

  flightControl: (action: "pause" | "resume" | "speed", speed?: number) =>
    fetch("/api/flight/control", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action, speed }),
    }).then((r) => json<Flight>(r)),

  flightStop: () => fetch("/api/flight/stop", { method: "POST" }).then((r) => json<unknown>(r)),

  voiceSession: () =>
    fetch("/api/voice/session", { method: "POST" }).then((r) =>
      json<{
        value: string;
        expires_at: number | null;
        model: string;
        realtime_url: string;
        session: Record<string, unknown>;
      }>(r),
    ),

  voiceTool: (name: string, args: Record<string, unknown>) =>
    fetch("/api/voice/tool", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, arguments: args }),
    }).then((r) => json<Record<string, unknown>>(r)),

  reset: () => fetch("/api/reset", { method: "POST" }).then((r) => json<unknown>(r)),
};
