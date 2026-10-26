"use client";

import { useState } from "react";
import type { AlertView, Flight, MissionChoice, Trajectory } from "@/lib/types";
import { titleCase } from "@/lib/format";
import { MissionPicker } from "./MissionPicker";

const MARK = {
  auto: "bg-auto",
  ask_crew: "bg-alarm",
  escalate: "bg-ground",
} as const;

// Points per fault. A crew fix earns more the faster it lands.
const POINTS = { auto: 20, escalate: 10, crew: 100, perSecondLeft: 2 } as const;
const RANKS: [number, string][] = [
  [0.85, "Commander"],
  [0.65, "Flight engineer"],
  [0.4, "Mission specialist"],
  [0, "Cadet"],
];
// How long the "+points" flash stays after a fault is cleared.
const FLASH_MS = 6000;

type Scored = { alertId: string; points: number; best: number; text: string; at: number };

function score(flight: Flight, alerts: Map<string, AlertView>): Scored[] {
  return flight.events.flatMap((e) => {
    const a = alerts.get(e.alert_id);
    if (!a) return [];
    const at = Date.parse(a.decision.time);
    const status = a.decision.status;
    if (a.authority === "auto") return [{ alertId: a.alert_id, points: POINTS.auto, best: POINTS.auto, text: `${a.subsystem} fixed by SafeMode`, at }];
    if (a.authority === "escalate") return [{ alertId: a.alert_id, points: POINTS.escalate, best: POINTS.escalate, text: `${a.subsystem} handed to ground`, at }];
    const best = POINTS.crew + flight.decision_limit_s * POINTS.perSecondLeft;
    if (status === "approved") {
      const left = Math.max(0, flight.decision_limit_s - (e.response_s ?? flight.decision_limit_s));
      const took = e.response_s === null ? "" : ` in ${Math.round(e.response_s)} s`;
      return [{ alertId: a.alert_id, points: Math.round(POINTS.crew + left * POINTS.perSecondLeft), best, text: `${a.subsystem} fixed${took}`, at }];
    }
    if (status === "rejected" || status === "timed_out") return [{ alertId: a.alert_id, points: 0, best, text: `${a.subsystem} left open`, at }];
    return [];
  });
}

function rank(points: number, best: number): string {
  const share = best ? points / best : 0;
  return RANKS.find(([min]) => share >= min)![1];
}

type Props = {
  flight: Flight | null;
  mission: Trajectory | null;
  missions: MissionChoice[];
  alerts: Map<string, AlertView>;
  now: number | null;
  onSelect: (id: string) => Promise<void>;
  onStart: (speed: number) => Promise<void>;
  onControl: (action: "pause" | "resume" | "speed", speed?: number) => Promise<void>;
  onStop: () => Promise<void>;
  onOpen: (alertId: string) => void;
};

function milestones(dest: string): { at: number; label: string }[] {
  if (dest === "moon") {
    return [
      { at: 0.34, label: "translunar" },
      { at: 0.7, label: "coast" },
      { at: 0.9, label: "approach" },
    ];
  }
  return [
    { at: 0.25, label: "deep space" },
    { at: 0.5, label: "halfway" },
    { at: 0.8, label: `${titleCase(dest)} approach` },
  ];
}

/** The mission at a glance: a sped-up flight Earth → destination, with every fault pinned where it happened. */
export function FlightProgress({ flight, mission, missions, alerts, now, onSelect, onStart, onControl, onStop, onOpen }: Props) {
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };
  const dest = mission?.destination ?? "mars";

  if (!flight) {
    return <MissionPicker missions={missions} mission={mission} onSelect={onSelect} onStart={onStart} />;
  }

  const hold = flight.hold_alert_id;
  const left = flight.decision_left_s;
  const urgent = left !== null && left <= 15;
  const counts = flight.events.reduce(
    (c, e) => {
      const a = alerts.get(e.alert_id);
      if (a) c[a.authority] += 1;
      return c;
    },
    { auto: 0, ask_crew: 0, escalate: 0 },
  );
  const arrived = flight.finished && !flight.failed;
  const scored = score(flight, alerts);
  const points = scored.reduce((s, x) => s + x.points, 0);
  const best = scored.reduce((s, x) => s + x.best, 0);
  const title = rank(points, best);
  const fixed = scored.filter((x) => x.points > 0).length;
  const flash = now === null ? undefined : [...scored].sort((a, b) => b.at - a.at).find((x) => now - x.at < FLASH_MS);
  const marks = milestones(dest);

  return (
    <div className={`border-b px-6 py-3 ${flight.failed ? "border-alarm bg-alarm/10" : hold ? "border-alarm/60 bg-alarm/5" : "border-line bg-panel/60"}`}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-1 font-mono text-xs tabular">
        <div className="flex items-baseline gap-4">
          <span className="uppercase tracking-[0.14em] text-ink">{mission?.mission ?? "Mission"}{mission?.site ? ` · ${mission.site}` : ""} · day {Math.floor(flight.elapsed_days) + 1} / {Math.round(flight.transit_days)}</span>
          <span className="text-faint">{Math.round(flight.progress * 100)}%</span>
          <span className="text-faint">
            faults <span className="text-ink">{fixed}</span> fixed of {flight.events.length} · {flight.remaining_events} ahead
          </span>
          <span className="text-crew">
            {points.toLocaleString()} pts · {title}
          </span>
          {flash && (
            <span key={flash.alertId} className={`arrive ${flash.points > 0 ? "text-auto" : "text-alarm"}`}>
              {flash.points > 0 ? `+${flash.points}` : "+0"} · {flash.text}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {!flight.finished && (
            <>
              {flight.speeds.map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={busy}
                  onClick={() => run(() => onControl("speed", s))}
                  aria-pressed={flight.speed === s}
                  className={`rounded px-1.5 py-0.5 ${flight.speed === s ? "bg-line text-ink" : "text-faint hover:text-dim"}`}
                >
                  {s}×
                </button>
              ))}
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => onControl(flight.paused ? "resume" : "pause"))}
                className="ml-2 rounded border border-line px-2 py-0.5 text-dim hover:border-dim hover:text-ink"
              >
                {flight.paused ? "▶ resume" : "❚❚ pause"}
              </button>
            </>
          )}
          {flight.finished ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => onStart(flight.speed))}
                className="ml-2 rounded border border-auto/60 px-2 py-0.5 text-auto hover:bg-auto/10"
              >
                ↻ fly again
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => run(onStop)}
                className="ml-2 rounded border border-line px-2 py-0.5 text-dim hover:border-dim hover:text-ink"
              >
                change mission
              </button>
            </>
          ) : (
            <button type="button" disabled={busy} onClick={() => run(onStop)} className="ml-2 px-1 text-faint hover:text-alarm">
              abort
            </button>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3 pb-3">
        <span className="font-mono text-[10px] tracking-[0.14em] text-ground">EARTH</span>
        <div className="relative h-2 flex-1 rounded-full bg-line">
          <div
            className={`absolute inset-y-0 left-0 rounded-full ${flight.failed ? "bg-alarm/60" : "bg-auto/60"}`}
            style={{ width: `${flight.progress * 100}%`, transition: "width 1.5s linear" }}
          />
          {marks.map((m) => (
            <span
              key={m.label}
              className={`pointer-events-none absolute top-full mt-1 -translate-x-1/2 whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.12em] ${flight.progress >= m.at ? "text-auto" : "text-faint"}`}
              style={{ left: `${m.at * 100}%` }}
            >
              {flight.progress >= m.at ? "✓ " : ""}
              {m.label}
            </span>
          ))}
          {flight.events.map((e) => {
            const a = alerts.get(e.alert_id);
            return (
              <button
                key={e.alert_id}
                type="button"
                onClick={() => onOpen(e.alert_id)}
                title={a ? `Day ${Math.floor(e.day) + 1} · ${a.subsystem} · ${a.proposed_action}` : e.alert_id}
                className={`absolute top-1/2 h-3.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-sm ring-2 ring-void hover:scale-150 ${a ? MARK[a.authority] : "bg-faint"} ${e.alert_id === hold ? "heartbeat" : ""}`}
                style={{ left: `${e.progress * 100}%` }}
              />
            );
          })}
          <span
            className={`pointer-events-none absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm ${flight.failed ? "text-alarm" : "text-ink"}`}
            style={{ left: `${flight.progress * 100}%`, transition: "left 1.5s linear" }}
            aria-hidden
          >
            ▶
          </span>
        </div>
        <span className="font-mono text-[10px] tracking-[0.14em] text-crew">{dest.toUpperCase()}</span>
      </div>

      {flight.failed ? (
        <p className="mt-2.5 text-sm text-alarm">
          <span className="mr-2 font-mono text-xs font-bold uppercase tracking-[0.18em]">Mission lost.</span>{" "}
          {flight.failed.text}{" "}
          <button type="button" onClick={() => onOpen(flight.failed!.alert_id)} className="ml-2 font-mono text-xs text-dim underline hover:text-ink">
            see alert
          </button>
        </p>
      ) : arrived ? (
        <p className="mt-2.5 text-sm text-auto">
          <span className="mr-2 font-mono text-xs font-bold uppercase tracking-[0.18em]">Arrived at {titleCase(dest)}</span>
          {flight.events.length} faults on the way: {counts.auto} fixed by SafeMode, {counts.ask_crew} crew calls, {counts.escalate} sent to ground. Final score{" "}
          {points.toLocaleString()} of {best.toLocaleString()}, rank {title}.
        </p>
      ) : hold && left !== null ? (
        <div className="mt-2.5 flex items-center gap-3">
          <span className={`font-mono text-xs font-bold uppercase tracking-[0.18em] text-alarm ${urgent ? "heartbeat" : ""}`}>Mission hold</span>
          <span className="text-xs text-ink">{alerts.get(hold)?.subsystem ?? "Crew"} decision required</span>
          <div className="h-1.5 w-40 overflow-hidden rounded-full bg-line">
            <div
              className={urgent ? "h-full bg-alarm" : "h-full bg-crew"}
              style={{ width: `${(left / flight.decision_limit_s) * 100}%`, transition: "width 1.5s linear" }}
            />
          </div>
          <span className={`font-mono text-xs tabular ${urgent ? "text-alarm" : "text-crew"}`}>{Math.ceil(left)} seconds</span>
          <button type="button" onClick={() => onOpen(hold)} className="rounded border border-alarm/60 px-2 py-0.5 font-mono text-xs text-alarm hover:bg-alarm/10">
            act now →
          </button>
        </div>
      ) : flight.caution ? (
        <p className="arrive mt-2.5 text-xs text-crew">
          <span className="mr-2 font-mono font-bold uppercase tracking-[0.18em]">⚠ Caution</span>
          <span className="mr-2 font-mono text-dim">{flight.caution.channel}</span>
          {flight.caution.text}. SafeMode is watching.
        </p>
      ) : flight.paused ? (
        <p className="mt-2.5 font-mono text-xs uppercase tracking-[0.14em] text-faint">paused</p>
      ) : (
        <p className="mt-2.5 font-mono text-xs uppercase tracking-[0.14em] text-faint">coasting · all systems nominal</p>
      )}
    </div>
  );
}

