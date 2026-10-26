"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ActionsTable } from "@/components/ActionsTable";
import { AlertNotice } from "@/components/AlertNotice";
import { ChatMessage } from "@/components/ChatMessage";
import { DecisionModal } from "@/components/DecisionModal";
import { FlightProgress } from "@/components/FlightProgress";
import { SidePanel } from "@/components/SidePanel";
import { WarningBar } from "@/components/WarningBar";
import { connectAgent, type Agent } from "@/lib/agent";
import { api } from "@/lib/api";
import type { AlertView, FeedEntry, Message, State } from "@/lib/types";
import { speak, spoken, stop, warn } from "@/lib/voice";

const POLL_MS = 1500;
// Alerts already queued when the console opens. Only the newest few join the feed.
const BACKLOG = 2;
const MAX_SUGGESTIONS = 5;

const GENERAL = [
  "Status report",
  "What should I worry about right now?",
  "How many days of oxygen margin do we have after arrival?",
  "When is the earliest ground could answer us?",
  "Plan Earth to Mars for 4 crew, 12 tons dry, 450 second engines",
];

/** What the crew actually asks for depends on what is going on: an open call, a declined fix, a quiet coast. */
function suggestions(alerts: AlertView[]): string[] {
  const latest = [...alerts].reverse();
  const find = (status: string) => latest.find((a) => a.decision.status === status);
  const out: string[] = [];
  const open = find("awaiting_crew");
  if (open) {
    out.push(`Walk me through the ${open.subsystem} procedure`, `What happens if I reject the ${open.subsystem} fix?`, "Do we have time to wait for ground?");
  }
  const declined = find("rejected");
  if (declined) out.push(`What risk are we carrying from the ${declined.subsystem} fault?`);
  const ground = find("escalated");
  if (ground) out.push(`What should we do while ground looks at ${ground.subsystem}?`);
  const auto = find("executed");
  if (auto) out.push(`Why did SafeMode ${lowerFirst(auto.proposed_action)}?`);
  return [...new Set([...out, ...GENERAL])].slice(0, MAX_SUGGESTIONS);
}

function lowerFirst(s: string): string {
  return s.charAt(0).toLowerCase() + s.slice(1);
}

const EXAMPLES = [
  "Walk me through the procedure step by step",
  "Why did SafeMode switch the reaction wheel?",
  "Status report",
  "Plan Earth to Mars for 4 crew, 12 tons dry, 450 second engines",
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
type Call = "off" | "connecting" | "live";

export default function Console() {
  const [state, setState] = useState<State | null>(null);
  const [feed, setFeed] = useState<FeedEntry[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [offline, setOffline] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const [voice, setVoice] = useState(true);
  const [call, setCall] = useState<Call>("off");
  const [level, setLevel] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);
  const [view, setView] = useState<View>("chat");
  const [modalId, setModalId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const voiceOn = useRef(true);
  const agentRef = useRef<Agent | null>(null);
  const liveId = useRef<string | null>(null);
  const talkGen = useRef(0);
  const endCall = useRef<() => void>(() => {});
  const sayRef = useRef<(text: string, urgent?: boolean) => void>(() => {});
  const briefCrewRef = useRef<(speech: string) => void>(() => {});
  const startCallRef = useRef<() => Promise<void>>(async () => {});
  const connectingRef = useRef(false);
  const pendingBrief = useRef<string | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const lostSeen = useRef<string | null>(null);
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
    if (!next) {
      stop();
      endCall.current();
      return;
    }
    if (!agentRef.current) speak("Voice on.", { interrupt: true });
  };

  const absorb = useCallback((next: State) => {
    setState(next);
    const lost = next.flight?.failed;
    if (lost && lostSeen.current !== lost.alert_id) {
      lostSeen.current = lost.alert_id;
      setModalId(null);
      pendingBrief.current = null;
      // Once, and only the outcome. The banner stays on screen; reading it aloud repeats every poll.
      if (claim(`lost:${lost.alert_id}`)) {
        stop();
        sayRef.current("Mission failed.");
      }
    }
    if (seen.current === null) {
      const keep = new Set(next.alerts.slice(-BACKLOG).map((a) => a.alert_id));
      const crew = next.alerts.filter((a) => a.decision.status === "awaiting_crew");
      crew.forEach((a) => keep.add(a.alert_id));
      seen.current = new Set(next.alerts.map((a) => a.alert_id));
      setFeed(next.alerts.filter((a) => keep.has(a.alert_id)).map((a) => ({ kind: "alert", id: `a-${a.alert_id}`, alertId: a.alert_id })));
      if (crew.length) setModalId(crew[crew.length - 1].alert_id);
      return;
    }
    const fresh = next.alerts.filter((a) => !seen.current!.has(a.alert_id));
    if (!fresh.length) return;
    fresh.forEach((a) => seen.current!.add(a.alert_id));
    const crew = fresh.filter((a) => a.decision.status === "awaiting_crew");
    if (crew.length) setModalId(crew[crew.length - 1].alert_id);
    // Auto-fixes stay silent: nothing is asked of the crew. Each line has its own speak button.
    const unspoken = fresh.filter((a) => a.authority !== "auto" && claim(a.alert_id));
    const loud = unspoken.filter((a) => a.decision.status === "awaiting_crew");
    // The flight is over, so a late alert must not start another warning or a voice call.
    if (!lost) {
      if (loud.length) briefCrewRef.current(alertSpeech(loud[0], loud.length - 1));
      else if (unspoken.length) sayRef.current(alertSpeech(unspoken[unspoken.length - 1], 0));
    }
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

  useEffect(() => () => agentRef.current?.hangup(), []);

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

  const hangup = () => {
    talkGen.current += 1;
    connectingRef.current = false;
    pendingBrief.current = null;
    agentRef.current?.hangup();
    agentRef.current = null;
    const id = liveId.current;
    liveId.current = null;
    if (id) {
      setFeed((f) => f.map((e) => (e.kind === "message" && e.id === id ? { ...e, message: { ...e.message, live: undefined } } : e)));
    }
    setCall("off");
    setLevel(0);
  };
  endCall.current = hangup;

  const tellAgent = (agent: Agent, text: string) => {
    try {
      agent.notify(text);
    } catch (e) {
      setMicError((e as Error).message);
    }
  };

  sayRef.current = (text, urgent = false) => {
    if (agentRef.current) {
      tellAgent(agentRef.current, text);
      return;
    }
    if (!voiceOn.current) return;
    if (urgent) warn(text);
    else speak(text, { interrupt: true });
  };

  const startCall = async () => {
    if (agentRef.current || connectingRef.current) return;
    connectingRef.current = true;
    const gen = ++talkGen.current;
    setMicError(null);
    setCall("connecting");
    stop();
    voiceOn.current = true;
    setVoice(true);
    localStorage.setItem(VOICE_KEY, "on");
    try {
      const agent = await connectAgent({
        onStatus: (status) => {
          if (talkGen.current !== gen) return;
          if (status === "listening") setCall("live");
          if (status === "closed") {
            agentRef.current = null;
            const id = liveId.current;
            liveId.current = null;
            if (id) {
              setFeed((f) => f.map((e) => (e.kind === "message" && e.id === id ? { ...e, message: { ...e.message, live: undefined } } : e)));
            }
            setCall("off");
            setLevel(0);
            setMicError("Voice call ended.");
          }
        },
        onLevel: (n) => {
          if (talkGen.current === gen) setLevel(n);
        },
        onError: (message) => {
          if (talkGen.current === gen) setMicError(message);
        },
        onUser: (text) => {
          if (talkGen.current !== gen || !text.trim()) return;
          const message: Message = { role: "user", content: text.trim() };
          const id = `m-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
          setMessages((m) => [...m, message]);
          setFeed((f) => {
            const entry: FeedEntry = { kind: "message", id, message };
            const live = liveId.current;
            if (!live) return [...f, entry];
            const i = f.findIndex((e) => e.id === live);
            if (i < 0) return [...f, entry];
            return [...f.slice(0, i), entry, ...f.slice(i)];
          });
        },
        onReply: ({ text, calls, final }) => {
          if (talkGen.current !== gen) return;
          if (!text && calls.length === 0 && !liveId.current) return;
          const id = liveId.current ?? `m-live-${Date.now()}`;
          liveId.current = final ? null : id;
          const message: Message = { role: "assistant", content: text, calls, live: final ? undefined : true };
          if (final && !text && calls.length === 0) {
            setFeed((f) => f.filter((e) => e.id !== id));
            return;
          }
          setFeed((f) => {
            const entry: FeedEntry = { kind: "message", id, message };
            return f.some((e) => e.id === id) ? f.map((e) => (e.id === id ? entry : e)) : [...f, entry];
          });
          if (final) setMessages((m) => [...m, { role: "assistant", content: text, calls }]);
        },
      });
      if (talkGen.current !== gen) {
        agent.hangup();
        return;
      }
      agentRef.current = agent;
      setCall("live");
      const brief = pendingBrief.current;
      pendingBrief.current = null;
      if (brief) tellAgent(agent, brief);
    } catch (e) {
      if (talkGen.current !== gen) return;
      setCall("off");
      setLevel(0);
      const err = e as Error;
      setMicError(err.name === "NotAllowedError" ? "Microphone access is blocked for this page." : err.message);
    } finally {
      if (talkGen.current === gen) connectingRef.current = false;
    }
  };
  startCallRef.current = startCall;

  briefCrewRef.current = (speech: string) => {
    // Crew alerts are spoken by the live agent, not the text-to-speech voice. The call stays up.
    stop();
    const notice = `A crew alert just opened on the console. Tell the crew what is happening in one or two short sentences, then stop and listen. They will ask questions on this same call while the alert stays on screen. Approve and reject stay on the card. Say it in your own words: ${speech}`;
    if (agentRef.current) {
      tellAgent(agentRef.current, notice);
      return;
    }
    pendingBrief.current = notice;
    if (!connectingRef.current) void startCallRef.current();
  };

  const talk = () => {
    if (agentRef.current || connectingRef.current) {
      hangup();
      return;
    }
    void startCall();
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content) return;
    if (agentRef.current) {
      const user: Message = { role: "user", content };
      setMessages((m) => [...m, user]);
      setFeed((f) => [...f, { kind: "message", id: `m-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, message: user }]);
      setDraft("");
      try {
        agentRef.current.sendText(content);
      } catch (e) {
        setMicError((e as Error).message);
      }
      return;
    }
    if (thinking) return;
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
      const urgent = calls.some((c) => c.name === "mission_status" && c.result.overall === "action_needed");
      sayRef.current(speech, urgent);
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

  const speakAlert = (a: AlertView) => {
    const summary = a.narration ? ` ${spoken(a.narration)}` : "";
    const text = `${alertSpeech(a, 0)}${summary}`;
    if (agentRef.current) {
      try {
        agentRef.current.notify(text);
      } catch (e) {
        setMicError((e as Error).message);
      }
      return;
    }
    speak(text, { interrupt: true });
  };

  const askAbout = (a: AlertView) => {
    setView("chat");
    const ask =
      a.decision.status === "awaiting_crew"
        ? `Walk me through the ${a.subsystem} procedure. What happens if I reject it?`
        : a.authority === "auto"
          ? `Why did SafeMode ${lowerFirst(a.proposed_action)}, and what should we watch now?`
          : `Explain the ${a.subsystem} alert. What is the next move and who has it?`;
    send(`${ask} (alert ${a.alert_id})`);
  };

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

  const fresh = async () => {
    seen.current = null;
    lostSeen.current = null;
    setMessages([]);
    setModalId(null);
    setExpanded(new Set());
    absorb(await api.state());
  };

  const reset = async () => {
    await api.reset();
    await fresh();
  };

  const chooseMission = async (id: string) => {
    await api.selectMission(id);
    absorb(await api.state());
  };

  const launch = async (speed: number) => {
    const name = state?.mission.mission ?? "the mission";
    await api.flightStart(speed);
    await fresh();
    sayRef.current(`Launch, ${name}. SafeMode is watching telemetry.`);
  };

  const controlFlight = async (action: "pause" | "resume" | "speed", speed?: number) => {
    await api.flightControl(action, speed);
    absorb(await api.state());
  };

  const abortFlight = async () => {
    await api.flightStop();
    await fresh();
  };

  const modalAlert = modalId ? alerts.get(modalId) : undefined;
  const othersWaiting = awaitingList.filter((a) => a.alert_id !== modalId);
  let liveLine: string | null = null;
  for (let i = feed.length - 1; i >= 0; i--) {
    const entry = feed[i];
    if (entry.kind === "message" && entry.message.role === "assistant" && entry.message.live) {
      liveLine = entry.message.content;
      break;
    }
  }

  return (
    <div className="flex h-full flex-col">
      <Header state={state} now={now} offline={offline} awaiting={awaiting} voice={voice} onVoice={toggleVoice} />
      <WarningBar awaiting={awaitingList} onReview={() => setModalId(awaitingList[0]?.alert_id ?? null)} />
      <FlightProgress
        flight={state?.flight ?? null}
        mission={state?.mission ?? null}
        missions={state?.missions ?? []}
        alerts={alerts}
        now={now}
        onSelect={chooseMission}
        onStart={launch}
        onControl={controlFlight}
        onStop={abortFlight}
        onOpen={focus}
      />

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
                {feed.length === 0 && !thinking && <Empty send={send} />}
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
                        onSpeak={() => speakAlert(alert)}
                        onAsk={() => askAbout(alert)}
                      />
                    </div>
                  );
                })}
                {thinking && <p className="font-mono text-xs text-faint heartbeat">otto is working…</p>}
                <div ref={bottom} />
              </div>
            )}
          </div>

          {view === "chat" && !modalAlert && (
            <Composer
              draft={draft}
              setDraft={setDraft}
              send={send}
              thinking={thinking}
              suggestions={suggestions(state?.alerts ?? [])}
              call={call}
              level={level}
              micError={micError}
              onTalk={talk}
            />
          )}
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
          decisionLeftS={state?.flight?.hold_alert_id === modalAlert.alert_id ? state.flight.decision_left_s : null}
          onDecide={(approved) => decide(modalAlert.alert_id, approved)}
          onReopen={() => reopen(modalAlert.alert_id)}
          onNext={() => setModalId(othersWaiting[0]?.alert_id ?? null)}
          onClose={() => setModalId(null)}
        />
      )}
      {modalAlert && (
        <div className="fixed inset-x-0 bottom-0 z-[60]">
          <Composer
            draft={draft}
            setDraft={setDraft}
            send={send}
            thinking={thinking}
            suggestions={suggestions(state?.alerts ?? [])}
            call={call}
            level={level}
            micError={micError}
            onTalk={talk}
            docked
            liveLine={liveLine}
          />
        </div>
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

function Empty({ send }: { send: (s: string) => void }) {
  return (
    <div className="pt-10">
      <p className="text-center font-mono text-xs uppercase tracking-[0.2em] text-faint">all quiet</p>
      <p className="mt-2 text-center text-sm text-dim">
        SafeMode is watching telemetry. otto is your CAPCOM on board: type, or press ● for a live call.
      </p>
      <div className="mx-auto mt-8 flex max-w-md flex-col items-center gap-2">
        {EXAMPLES.map((ask) => (
          <button key={ask} type="button" onClick={() => send(ask)} className="text-center text-xs text-dim hover:text-ink">
            “{ask}”
          </button>
        ))}
      </div>
    </div>
  );
}

type ComposerProps = {
  draft: string;
  setDraft: (s: string) => void;
  send: (s: string) => void;
  thinking: boolean;
  suggestions: string[];
  call: Call;
  level: number;
  micError: string | null;
  onTalk: () => void;
  /** Sits above a crew-decision modal so the live call stays on screen. */
  docked?: boolean;
  liveLine?: string | null;
};

function Composer({ draft, setDraft, send, thinking, suggestions, call, level, micError, onTalk, docked, liveLine }: ComposerProps) {
  const live = call === "live";
  const placeholder =
    call === "connecting" ? "Connecting the headset…" : live ? "Listening… type to talk on this call" : "Ask otto, or press ● for a live call";
  return (
    <div className={`border-t border-line bg-void px-6 py-4 ${docked ? "shadow-[0_-16px_40px_rgba(0,0,0,0.55)]" : ""}`}>
      <div className="mx-auto max-w-3xl space-y-3">
        {docked && (
          <p className="flex items-center gap-2 font-mono text-xs text-ink">
            <span className={`h-2 w-2 shrink-0 rounded-full ${live ? "bg-alarm heartbeat" : call === "connecting" ? "bg-crew heartbeat" : "bg-faint"}`} />
            <span className={live ? "text-alarm" : "text-dim"}>{live ? "Live call" : call === "connecting" ? "Connecting" : "Voice"}</span>
            <span className="min-w-0 truncate text-dim">{live ? liveLine || "Listening. Ask Otto about this alert." : "Talk it through from here. The alert stays open."}</span>
          </p>
        )}
        {!thinking && !docked && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {suggestions.map((s) => (
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
          className={`flex items-center gap-3 rounded-lg border bg-panel px-4 py-2.5 ${live ? "border-alarm/60" : "border-line focus-within:border-dim"}`}
        >
          <button
            type="button"
            onClick={onTalk}
            disabled={call === "connecting"}
            aria-pressed={live}
            title={live ? "Hang up" : "Live voice call"}
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] disabled:opacity-30 ${
              live ? "border-alarm text-alarm" : "border-line text-dim hover:border-dim hover:text-ink"
            }`}
            style={live ? { boxShadow: `0 0 0 ${Math.min(8, level * 120)}px color-mix(in srgb, var(--color-alarm) 35%, transparent)` } : undefined}
          >
            {call === "connecting" ? "…" : live ? "■" : "●"}
          </button>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={call === "connecting"}
            placeholder={placeholder}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
          />
          <button
            type="submit"
            disabled={call === "connecting" || !draft.trim() || (thinking && !live)}
            className="font-mono text-xs text-dim hover:text-ink disabled:opacity-30"
          >
            send ↵
          </button>
        </form>
        {live && <p className="font-mono text-[11px] text-dim">Live call. Otto hears this mic and answers out loud.</p>}
        {micError && <p className="font-mono text-[11px] text-alarm">{micError}</p>}
      </div>
    </div>
  );
}
