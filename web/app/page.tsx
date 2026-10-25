"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ActionsTable } from "@/components/ActionsTable";
import { AlertNotice } from "@/components/AlertNotice";
import { ChatMessage } from "@/components/ChatMessage";
import { DecisionModal } from "@/components/DecisionModal";
import { SidePanel } from "@/components/SidePanel";
import { WarningBar } from "@/components/WarningBar";
import { api } from "@/lib/api";
import type { AlertView, FeedEntry, Message, State } from "@/lib/types";
import { speak, spoken, stop, warn } from "@/lib/voice";

const POLL_MS = 1500;
// Alerts already queued when the console opens. Only the newest few join the feed.
const BACKLOG = 2;

const SUGGESTIONS = [
  "otto, how is the mission going?",
  "Plan Earth to Mars for 4 crew, 12 t dry, 450 s engines",
  "What is SafeMode seeing right now?",
  "Diagnose the latest alert",
  "How long would Jupiter take on a 900 s nuclear engine?",
];

const VOICE_KEY = "otto.voice";
const SPOKEN_KEY = "otto.spoken";

/** True only the first time any open tab asks, so several tabs or a reload never repeat an alert aloud. */
function claim(alertId: string): boolean {
  const ids: string[] = JSON.parse(localStorage.getItem(SPOKEN_KEY) ?? "[]");
  if (ids.includes(alertId)) return false;
  localStorage.setItem(SPOKEN_KEY, JSON.stringify([...ids.slice(-200), alertId]));
  return true;
}

function alertSpeech(a: AlertView, more: number): string {
  const action = a.proposed_action.charAt(0).toLowerCase() + a.proposed_action.slice(1);
  const next = {
    auto: `SafeMode has already acted. It will ${action}. This can be undone.`,
    ask_crew: `Crew decision needed. Proposed: ${action}. This cannot be undone. The decision is on screen.`,
    escalate: `Sent to ground control. Proposed: ${action}.`,
  }[a.authority];
  const also = more > 0 ? ` ${more} more waiting.` : "";
  return `${a.subsystem} anomaly, ${Math.round(a.confidence * 100)} percent confidence. ${next}${also}`;
}

type View = "chat" | "actions";

export default function Console() {
  const [state, setState] = useState<State | null>(null);
  const [feed, setFeed] = useState<FeedEntry[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [offline, setOffline] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const [voice, setVoice] = useState(true);
  const [view, setView] = useState<View>("chat");
  const [modalId, setModalId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const voiceOn = useRef(true);
  const seen = useRef<Set<string> | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = localStorage.getItem(VOICE_KEY) !== "off";
    voiceOn.current = saved;
    const id = setTimeout(() => setVoice(saved), 0);
    return () => clearTimeout(id);
  }, []);

  const toggleVoice = () => {
    const next = !voiceOn.current;
    voiceOn.current = next;
    setVoice(next);
    localStorage.setItem(VOICE_KEY, next ? "on" : "off");
    if (next) speak("Voice on.", { interrupt: true });
    else stop();
  };

  const absorb = useCallback((next: State) => {
    setState(next);
    if (seen.current === null) {
      const keep = new Set(next.alerts.slice(-BACKLOG).map((a) => a.alert_id));
      next.alerts.filter((a) => a.decision.status === "awaiting_crew").forEach((a) => keep.add(a.alert_id));
      seen.current = new Set(next.alerts.map((a) => a.alert_id));
      setFeed(next.alerts.filter((a) => keep.has(a.alert_id)).map((a) => ({ kind: "alert", id: `a-${a.alert_id}`, alertId: a.alert_id })));
      return;
    }
    const fresh = next.alerts.filter((a) => !seen.current!.has(a.alert_id));
    if (!fresh.length) return;
    fresh.forEach((a) => seen.current!.add(a.alert_id));
    const crew = fresh.filter((a) => a.decision.status === "awaiting_crew");
    if (crew.length) setModalId((open) => open ?? crew[0].alert_id);
    const unspoken = fresh.filter((a) => claim(a.alert_id));
    const loud = unspoken.filter((a) => a.decision.status === "awaiting_crew");
    if (voiceOn.current && loud.length) warn(alertSpeech(loud[0], loud.length - 1));
    else if (voiceOn.current && unspoken.length) speak(alertSpeech(unspoken[unspoken.length - 1], 0));
    setFeed((f) => [...f, ...fresh.map((a) => ({ kind: "alert" as const, id: `a-${a.alert_id}`, alertId: a.alert_id }))]);
  }, []);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const next = await api.state();
        if (alive) {
          absorb(next);
          setOffline(false);
        }
      } catch {
        if (alive) setOffline(true);
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [absorb]);

  useEffect(() => {
    const first = setTimeout(() => setNow(Date.now()), 0);
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [feed.length, thinking]);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || thinking) return;
    const user: Message = { role: "user", content };
    const history = [...messages, user];
    setMessages(history);
    setFeed((f) => [...f, { kind: "message", id: `m-${f.length}-${Date.now()}`, message: user }]);
    setDraft("");
    setThinking(true);
    try {
      const { text: reply, spoken: summary, calls } = await api.chat(history);
      const speech = summary ?? spoken(reply);
      const msg: Message = { role: "assistant", content: reply, speech, calls };
      setMessages((m) => [...m, msg]);
      setFeed((f) => [...f, { kind: "message", id: `m-${f.length}-${Date.now()}`, message: msg }]);
      if (voiceOn.current) {
        const urgent = calls.some((c) => c.name === "mission_status" && c.result.overall === "action_needed");
        if (urgent) warn(speech);
        else speak(speech, { interrupt: true });
      }
    } catch (e) {
      const msg: Message = { role: "assistant", content: `I couldn't reach Grok: ${(e as Error).message}` };
      setFeed((f) => [...f, { kind: "message", id: `m-${f.length}-${Date.now()}`, message: msg }]);
    } finally {
      setThinking(false);
    }
  };

  const replace = (updated: AlertView) =>
    setState((s) => s && { ...s, alerts: s.alerts.map((a) => (a.alert_id === updated.alert_id ? updated : a)) });

  const decide = async (alertId: string, approved: boolean) => replace(await api.decide(alertId, approved));

  const reopen = async (alertId: string) => replace(await api.reopen(alertId));

  const alerts = new Map<string, AlertView>((state?.alerts ?? []).map((a) => [a.alert_id, a]));
  const awaitingList = (state?.alerts ?? []).filter((a) => a.decision.status === "awaiting_crew");
  const awaiting = awaitingList.length;

  const toggle = (alertId: string, open?: boolean) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (open ?? !next.has(alertId)) next.add(alertId);
      else next.delete(alertId);
      return next;
    });

  const focus = (alertId: string) => {
    if (alerts.get(alertId)?.decision.status === "awaiting_crew") {
      setModalId(alertId);
      return;
    }
    setView("chat");
    toggle(alertId, true);
    if (!feed.some((e) => e.kind === "alert" && e.alertId === alertId)) {
      setFeed((f) => [...f, { kind: "alert", id: `a-${alertId}`, alertId }]);
    }
    requestAnimationFrame(() => document.getElementById(`a-${alertId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  };

  const simulate = async (scenario: string) => {
    await api.simulate(scenario);
    absorb(await api.state());
  };

  const reset = async () => {
    await api.reset();
    seen.current = null;
    setMessages([]);
    setModalId(null);
    setExpanded(new Set());
    absorb(await api.state());
  };

  const modalAlert = modalId ? alerts.get(modalId) : undefined;
  const othersWaiting = awaitingList.filter((a) => a.alert_id !== modalId);

  return (
    <div className="flex h-full flex-col">
      <Header state={state} now={now} offline={offline} awaiting={awaiting} voice={voice} onVoice={toggleVoice} />
      <WarningBar awaiting={awaitingList} onReview={() => setModalId(awaitingList[0]?.alert_id ?? null)} />

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px]">
        <main className="flex min-h-0 min-w-0 flex-col">
          <nav className="flex gap-5 border-b border-line px-6 font-mono text-xs">
            {(["chat", "actions"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                aria-pressed={view === v}
                className={`-mb-px border-b-2 py-2 uppercase tracking-[0.14em] ${view === v ? "border-ink text-ink" : "border-transparent text-faint hover:text-dim"}`}
              >
                {v === "chat" ? "chat" : `AI actions (${state?.log.length ?? 0})`}
              </button>
            ))}
          </nav>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {view === "actions" ? (
              <ActionsTable log={state?.log ?? []} alerts={alerts} onOpen={focus} />
            ) : (
              <div className="mx-auto max-w-3xl space-y-3 px-6 py-6">
                {feed.length === 0 && !thinking && <Empty />}
                {feed.map((entry) => {
                  if (entry.kind === "message") return <ChatMessage key={entry.id} message={entry.message} />;
                  const alert = alerts.get(entry.alertId);
                  if (!alert || now === null) return null;
                  return (
                    <div key={entry.id} id={entry.id}>
                      <AlertNotice
                        alert={alert}
                        expanded={expanded.has(alert.alert_id)}
                        now={now}
                        lightDelayS={state!.ground_light_delay_s}
                        onToggle={() => toggle(alert.alert_id)}
                        onReview={() => setModalId(alert.alert_id)}
                        onDecide={(approved) => decide(alert.alert_id, approved)}
                        onReopen={() => reopen(alert.alert_id)}
                      />
                    </div>
                  );
                })}
                {thinking && <p className="font-mono text-xs text-faint heartbeat">otto is working…</p>}
                <div ref={bottom} />
              </div>
            )}
          </div>

          {view === "chat" && <Composer draft={draft} setDraft={setDraft} send={send} thinking={thinking} showSuggestions={messages.length === 0} />}
        </main>

        <SidePanel
          mission={state?.mission ?? null}
          safemode={state?.safemode ?? null}
          alerts={state?.alerts ?? []}
          log={state?.log ?? []}
          onFocus={focus}
          onOpenTable={() => setView("actions")}
          onSimulate={simulate}
          onReset={reset}
        />
      </div>

      {modalAlert && now !== null && (
        <DecisionModal
          alert={modalAlert}
          remaining={othersWaiting.length}
          now={now}
          lightDelayS={state!.ground_light_delay_s}
          onDecide={(approved) => decide(modalAlert.alert_id, approved)}
          onReopen={() => reopen(modalAlert.alert_id)}
          onNext={() => setModalId(othersWaiting[0]?.alert_id ?? null)}
          onClose={() => setModalId(null)}
        />
      )}
    </div>
  );
}

type HeaderProps = {
  state: State | null;
  now: number | null;
  offline: boolean;
  awaiting: number;
  voice: boolean;
  onVoice: () => void;
};

function Header({ state, now, offline, awaiting, voice, onVoice }: HeaderProps) {
  const running = state?.safemode.running;
  const utc = now === null ? "--:--:--" : new Date(now).toISOString().slice(11, 19);
  return (
    <header className="flex items-center justify-between border-b border-line px-6 py-3">
      <div className="flex items-baseline gap-4">
        <span className="font-mono text-lg font-medium tracking-tight">otto</span>
        <span className="hidden text-xs text-faint sm:inline">The crew keeps the final say.</span>
      </div>
      <div className="flex items-center gap-6 font-mono text-xs tabular">
        {awaiting > 0 && <span className="text-alarm">{awaiting} awaiting crew</span>}
        <button type="button" onClick={onVoice} aria-pressed={voice} className={voice ? "text-ink hover:text-dim" : "text-faint hover:text-dim"}>
          {voice ? "voice on" : "voice off"}
        </button>
        <span className="flex items-center gap-2 text-dim">
          <span className={`h-2 w-2 rounded-full ${offline ? "bg-alarm" : running ? "bg-auto heartbeat" : "bg-faint"}`} />
          {offline ? "link lost" : running ? "SafeMode live" : "SafeMode idle"}
        </span>
        <span className="text-ink">{utc} UTC</span>
      </div>
    </header>
  );
}

function Empty() {
  return (
    <div className="pt-16 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-faint">all quiet</p>
      <p className="mt-2 text-sm text-dim">SafeMode is watching telemetry. Ask about the voyage, or wait for it to speak up.</p>
    </div>
  );
}

type ComposerProps = {
  draft: string;
  setDraft: (s: string) => void;
  send: (s: string) => void;
  thinking: boolean;
  showSuggestions: boolean;
};

function Composer({ draft, setDraft, send, thinking, showSuggestions }: ComposerProps) {
  return (
    <div className="border-t border-line bg-void px-6 py-4">
      <div className="mx-auto max-w-3xl space-y-3">
        {showSuggestions && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                className="shrink-0 whitespace-nowrap rounded-full border border-line px-3 py-1 text-xs text-dim hover:border-dim hover:text-ink"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
          className="flex items-center gap-3 rounded-lg border border-line bg-panel px-4 py-2.5 focus-within:border-dim"
        >
          <span className="font-mono text-xs text-faint">›</span>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask otto"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
          />
          <button type="submit" disabled={thinking || !draft.trim()} className="font-mono text-xs text-dim hover:text-ink disabled:opacity-30">
            send ↵
          </button>
        </form>
      </div>
    </div>
  );
}
