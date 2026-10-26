"use client";

import { useEffect, useState } from "react";
import type { MissionChoice, Trajectory } from "@/lib/types";
import { duration, mass, placeName } from "@/lib/format";

const GROUPS = [
  { id: "flown", label: "Apollo" },
  { id: "mars", label: "Mars" },
  { id: "jupiter", label: "Jupiter" },
  { id: "expedition", label: "Further" },
] as const;

type Props = {
  missions: MissionChoice[];
  mission: Trajectory | null;
  onSelect: (id: string) => Promise<void>;
  onStart: (speed: number) => Promise<void>;
};

/** A short row of missions. Choosing one opens the launch card. */
export function MissionPicker({ missions, mission, onSelect, onStart }: Props) {
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const chosen = missions.find((m) => m.id === mission?.id);
  const open = missions.find((m) => m.id === openId) ?? null;

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };

  const pick = (id: string) => {
    setOpenId(id);
    if (id !== chosen?.id) void run(() => onSelect(id));
  };

  if (!chosen || !mission) {
    return (
      <div className="flex items-center gap-3 border-b border-line bg-panel/60 px-6 py-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Mission</span>
        <span className="text-xs text-dim">Loading the catalog.</span>
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center gap-3 border-b border-line bg-panel/60 px-6 py-1.5">
        <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Mission</span>
        <div className="flex min-w-0 flex-1 items-center gap-3 overflow-x-auto">
        {GROUPS.map((group) => {
          const rows = missions.filter((m) => m.group === group.id);
          if (!rows.length) return null;
          return (
            <div key={group.id} className="flex shrink-0 items-center gap-1" role="radiogroup" aria-label={group.label}>
              <span className="mr-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">{group.label}</span>
              {rows.map((m) => {
                const on = m.id === chosen.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    title={`${m.name}. ${m.blurb}`}
                    disabled={busy && openId === m.id}
                    onClick={() => pick(m.id)}
                    className={`rounded border px-1.5 py-0.5 text-[11px] disabled:opacity-40 ${on ? "border-auto/70 bg-auto/10 text-ink" : "border-line text-dim hover:border-dim hover:text-ink"}`}
                  >
                    {m.name}
                  </button>
                );
              })}
            </div>
          );
        })}
        </div>
      </div>
      {open && (
        <LaunchModal
          choice={open}
          mission={mission.id === open.id ? mission : null}
          busy={busy}
          onClose={() => setOpenId(null)}
          onLaunch={() => run(() => onStart(1))}
        />
      )}
    </>
  );
}

type ModalProps = {
  choice: MissionChoice;
  /** The live trajectory, once the server has this mission staged. */
  mission: Trajectory | null;
  busy: boolean;
  onClose: () => void;
  onLaunch: () => void;
};

function LaunchModal({ choice, mission, busy, onClose, onLaunch }: ModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const coast = mission ? (mission.transit_days >= 730 ? duration(mission.transit_days) : `${Math.round(mission.transit_days)} days`) : null;
  const ready = mission !== null && !busy;
  const facts: [string, string][] = [
    ["crew", String(choice.crew)],
    ["ship", `${mass(choice.spacecraft_mass_kg)} dry`],
    ["engines", `${choice.isp_s} seconds`],
    ["coast", coast ?? "staging…"],
    ["launch", choice.launch_utc.slice(0, 10)],
    ["played in", "about 5 minutes"],
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-6 backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="launch-title"
        className="arrive w-full max-w-md rounded-xl border border-line bg-void shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-line px-5 py-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-faint">
            {choice.year} · {placeName(choice.destination)}
          </p>
          <h2 id="launch-title" className="mt-1 text-lg font-medium">
            {choice.name}
          </h2>
          <p className="mt-1 text-sm text-dim">
            {placeName(choice.origin)} → {placeName(choice.destination)} · {choice.site}
          </p>
          {choice.crew_names && <p className="mt-2 text-xs text-dim">{choice.crew_names}</p>}
        </div>

        <div className="space-y-4 px-5 py-4">
          <p className="text-sm text-ink">{choice.blurb}</p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-xs tabular">
            {facts.map(([k, val]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-line/60 pb-1">
                <dt className="text-faint">{k}</dt>
                <dd className="text-right text-ink">{val}</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-faint">Thirteen faults on the way. A crew call has 60 seconds.</p>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-line px-5 py-3">
          <button type="button" onClick={onClose} className="font-mono text-xs text-faint hover:text-dim">
            back (esc)
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={onLaunch}
            className="rounded-md border border-auto/60 bg-auto/10 px-5 py-2 font-mono text-xs uppercase tracking-[0.16em] text-auto hover:bg-auto/20 disabled:opacity-40"
          >
            {ready ? `Launch ${choice.name}` : "Staging…"}
          </button>
        </div>
      </div>
    </div>
  );
}
