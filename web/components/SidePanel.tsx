"use client";

import { useState } from "react";
import type { AlertView, LogEntry, SafeModeStatus, Trajectory } from "@/lib/types";
import { clock } from "@/lib/format";
import { MissionMap } from "./MissionMap";

const KIND = {
  auto: { text: "text-auto", border: "border-l-auto" },
  crew: { text: "text-alarm", border: "border-l-alarm" },
  ground: { text: "text-ground", border: "border-l-ground" },
} as const;
const LOG_COLLAPSED = 5;

// The gate, not this list, decides who acts. `expect` is only the label.
const SCENARIOS = [
  { id: "reaction_wheel", label: "Reaction wheel", expect: "auto" },
  { id: "power_bus", label: "Power bus", expect: "auto" },
  { id: "cooling_loop", label: "Cooling loop", expect: "auto" },
  { id: "transponder", label: "Transponder", expect: "ground" },
  { id: "cabin_leak", label: "Cabin leak", expect: "crew" },
  { id: "thruster_valve", label: "Thruster valve", expect: "crew" },
] as const;

type Props = {
  mission: Trajectory | null;
  safemode: SafeModeStatus | null;
  alerts: AlertView[];
  log: LogEntry[];
  onFocus: (alertId: string) => void;
  onOpenTable: () => void;
  onSimulate: (scenario: string) => Promise<void>;
  onReset: () => void;
};

export function SidePanel({ mission, safemode, alerts, log, onFocus, onOpenTable, onSimulate, onReset }: Props) {
  const awaiting = alerts.filter((a) => a.decision.status === "awaiting_crew");
  const [busy, setBusy] = useState(false);
  const simulate = async (id: string) => {
    setBusy(true);
    try {
      await onSimulate(id);
    } finally {
      setBusy(false);
    }
  };
  return (
    <aside className="flex min-h-0 flex-col gap-6 overflow-y-auto border-l border-line bg-panel/60 px-5 py-5">
      <Section title="Needs crew">
        {awaiting.length === 0 ? (
          <p className="text-xs text-faint">Nothing waiting on you.</p>
        ) : (
          <ul className="space-y-2">
            {awaiting.map((a) => (
              <li key={a.alert_id}>
                <button
                  type="button"
                  onClick={() => onFocus(a.alert_id)}
                  className="w-full rounded-md border border-alarm/60 px-3 py-2 text-left text-xs hover:bg-alarm/10"
                >
                  <span className="block font-medium text-alarm">{a.subsystem}</span>
                  <span className="text-dim">{a.proposed_action}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {mission && (
        <Section title={`${mission.mission} · day ${mission.mission_day}`}>
          <div className="flex justify-center">
            <MissionMap t={mission} size={220} />
          </div>
          <div className="mt-2 h-1 overflow-hidden rounded bg-line">
            <div className="h-full bg-auto/70" style={{ width: `${mission.progress * 100}%` }} />
          </div>
          <dl className="mt-2 space-y-1.5 font-mono text-xs tabular">
            <Row k="to arrival" v={`${Math.round(mission.days_to_arrival)} d`} />
            <Row k="from Earth" v={`${(mission.distance_to_earth_km / 1e6).toFixed(1)} M km`} />
            <Row k="light delay" v={`${mission.one_way_light_delay_min} min`} />
          </dl>
        </Section>
      )}

      <ActionLog log={log} onFocus={onFocus} onOpenTable={onOpenTable} />

      <Section title="Simulate an alert">
        <div className="grid grid-cols-2 gap-1.5">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              disabled={busy}
              onClick={() => simulate(s.id)}
              className={`rounded border border-line border-l-2 ${KIND[s.expect].border} px-2 py-1.5 text-left text-xs text-dim hover:bg-line/40 hover:text-ink disabled:opacity-40`}
            >
              {s.label}
              <span className={`block font-mono text-[10px] uppercase ${KIND[s.expect].text}`}>{s.expect}</span>
            </button>
          ))}
        </div>
      </Section>

      <Section title="SafeMode">
        <dl className="space-y-1.5 font-mono text-xs tabular">
          <Row k="monitor" v={safemode?.running ? "running" : "idle"} />
          <Row k="alerts" v={String(alerts.length)} />
          <Row k="source" v={safemode?.alert_source ?? "—"} />
          <Row k="channels" v={String(safemode?.channels?.length ?? "—")} />
        </dl>
        {safemode?.progress != null && (
          <div className="mt-3 h-1 overflow-hidden rounded bg-line">
            <div className="h-full bg-auto/70" style={{ width: `${safemode.progress * 100}%` }} />
          </div>
        )}
        {safemode?.note && <p className="mt-2 text-xs text-faint">{safemode.note}</p>}
      </Section>

      <button type="button" onClick={onReset} className="mt-auto self-start font-mono text-[11px] text-faint hover:text-dim">
        reset demo
      </button>
    </aside>
  );
}

function ActionLog({ log, onFocus, onOpenTable }: { log: LogEntry[]; onFocus: (alertId: string) => void; onOpenTable: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const entries = [...log].reverse();
  const shown = expanded ? entries : entries.slice(0, LOG_COLLAPSED);
  const hidden = entries.length - shown.length;

  return (
    <section className="rounded-lg border border-line bg-void/40 p-3">
      <div className="mb-2.5 flex items-baseline justify-between">
        <h2 className="text-xs font-medium uppercase tracking-[0.16em] text-ink">Action log</h2>
        <button type="button" onClick={onOpenTable} className="font-mono text-[11px] text-faint hover:text-dim">
          table ({entries.length}) →
        </button>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs text-faint">No actions yet.</p>
      ) : (
        <ol className={`space-y-1.5 ${expanded ? "max-h-[60vh] overflow-y-auto pr-1" : ""}`}>
          {shown.map((e, i) => (
            <li key={`${e.time}-${i}`}>
              <button
                type="button"
                onClick={() => onFocus(e.alert_id)}
                className={`w-full rounded-r border-l-2 ${KIND[e.kind].border} px-2.5 py-1.5 text-left hover:bg-line/40 ${i === 0 ? "bg-line/30" : ""}`}
              >
                <span className="flex items-baseline justify-between gap-2 font-mono text-[11px] tabular">
                  <span className={`${KIND[e.kind].text} uppercase`}>{e.kind}</span>
                  <span className="text-faint">{e.alert_id} · {clock(e.time)}</span>
                </span>
                <span className="mt-0.5 block text-xs leading-snug text-ink/90">{e.text}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {(hidden > 0 || expanded) && entries.length > LOG_COLLAPSED && (
        <button type="button" onClick={() => setExpanded((v) => !v)} className="mt-2 font-mono text-[11px] text-faint hover:text-dim">
          {expanded ? "− show latest only" : `+ show all (${hidden} more)`}
        </button>
      )}
    </section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2.5 text-[11px] uppercase tracking-[0.16em] text-faint">{title}</h2>
      {children}
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-faint">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  );
}
