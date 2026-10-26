"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AlertView } from "@/lib/types";
import { HoldButton } from "./HoldButton";

type GameProps = { seed: number; disabled?: boolean; onDone: () => void };
type Step = { title: string; hint: string; play: (p: GameProps) => React.ReactNode };
type Procedure = { name: string; steps: Step[]; commit: string };

const MODULES = ["Node 1", "Lab", "Hab", "Airlock", "Galley", "Stowage"];

/** The crew works the fix by hand before the irreversible step. Every procedure still ends on a hold.
 *  Keys are the `procedure` app/gate.py gives each crew action. */
const PROCEDURES: Record<string, Procedure> = {
  thruster_isolation: {
    name: "Thruster isolation",
    steps: [
      {
        title: "Find the leaking branch",
        hint: "Feed pressures update live. Tap the branch that keeps falling.",
        play: (p) => <Spot {...p} items={["Branch A", "Branch B", "Branch C", "Branch D"]} unit="psi" base={268} rate={-0.9} decimals={1} cols={4} clear="is holding pressure." />,
      },
      {
        title: "Repressurize the healthy branch",
        hint: "Hold to pump propellant into tank A. Let go inside the green band.",
        play: (p) => <Fill {...p} label="tank A" unit="psi" from={0} scale={2.8} action="hold to pump" active="pumping…" over="Overpressure. The relief valve vented the tank." />,
      },
      { title: "Re-point the engines", hint: "Swing the gimbal until the thrust vector sits on the target, then lock it.", play: (p) => <GimbalAlign {...p} /> },
    ],
    commit: "Hold to fire pyro valve",
  },
  cabin_leak: {
    name: "Module isolation",
    steps: [
      {
        title: "Find the leak",
        hint: "One module is losing pressure. Watch the readings and tap it.",
        play: (p) => <Spot {...p} items={MODULES} unit="kPa" base={101.3} rate={-0.09} decimals={2} clear="is holding pressure. Keep looking." />,
      },
      {
        title: "How long do you have?",
        hint: "Work out the time before the crew must suit up. Pick the closest answer.",
        play: (p) => (
          <Quiz
            {...p}
            make={(r) => {
              const now = round1(96 + r() * 4);
              const rate = round1(0.6 + r() * 0.9);
              const answer = Math.floor((now - 70) / rate);
              return {
                question: `Cabin is at ${now} kPa and falling ${rate} kPa a minute. Suits go on at 70 kPa. How long until then?`,
                answer,
                decoys: [Math.floor(now / rate), Math.round(answer / 2), Math.round((now - 70) * rate)],
                unit: "min",
                explain: `(${now} − 70) ÷ ${rate} ≈ ${answer} min.`,
              };
            }}
          />
        ),
      },
      {
        title: "Close the hatches",
        hint: "Close them in the order shown so nobody is cut off.",
        play: (p) => <Sequence {...p} items={["H1", "H2", "H3", "H4"]} done="sealed" open="open" wrong={(h) => `${h} was out of order. Crew still in transit. All hatches reopened.`} />,
      },
    ],
    commit: "Hold to vent module",
  },
  antenna_deploy: {
    name: "Forced deployment",
    steps: [
      {
        title: "Warm the hinge",
        hint: "The hinge is cold-welded. Hold the heater until it sits in the green band.",
        play: (p) => <Fill {...p} label="hinge" unit="°C" from={-60} scale={1} action="hold to heat" active="heating…" over="Too hot, the motor grease is thinning. Let it cool." />,
      },
      {
        title: "Arm the pyro circuit",
        hint: "Flip the safeties in order: SAFE A, SAFE B, then MASTER ARM.",
        play: (p) => <Switches {...p} items={["SAFE A", "SAFE B", "MASTER ARM"]} />,
      },
      {
        title: "Time the release",
        hint: "The boom sways with the ship. Release while the marker is in the window.",
        play: (p) => <Timing {...p} label="boom sway" action="release" miss="The boom was out of position, try again." />,
      },
    ],
    commit: "Hold to fire release",
  },
  co2_scrubber: {
    name: "Scrubber bed swap",
    steps: [
      {
        title: "Find the saturated bed",
        hint: "Each bed's outlet CO2 updates live. The saturated one keeps rising. Tap it.",
        play: (p) => <Spot {...p} items={["Bed A", "Bed B", "Bed C", "Bed D"]} unit="ppm" base={420} rate={9} decimals={0} cols={4} clear="is scrubbing normally." />,
      },
      {
        title: "Reroute the airflow",
        hint: "Close the bed's inlet, open the bypass, close the outlet, then unlatch the bed.",
        play: (p) => (
          <Sequence
            {...p}
            fixed
            items={["Close inlet", "Open bypass", "Close outlet", "Unlatch bed"]}
            done="done"
            open="ready"
            wrong={(v) => `${v} out of order. Cabin air would bypass the scrubbers. Valves reset.`}
          />
        ),
      },
      {
        title: "Check the spare",
        hint: "Make sure the spare bed lasts long enough before you throw the old one away.",
        play: (p) => (
          <Quiz
            {...p}
            make={(r) => {
              const holds = 20 + Math.floor(r() * 5) * 4;
              const answer = holds / 4;
              return {
                question: `The spare bed holds ${holds} kg of CO2. Four crew breathe out about 1 kg each a day. How many days does it last?`,
                answer,
                decoys: [holds, holds / 2, holds * 4],
                unit: "days",
                explain: `${holds} kg ÷ (4 crew × 1 kg a day) = ${answer} days.`,
              };
            }}
          />
        ),
      },
    ],
    commit: "Hold to jettison bed",
  },
  battery_runaway: {
    name: "Battery isolation",
    steps: [
      {
        title: "Find the hot cell",
        hint: "Cell temperatures update live. One is running away. Tap it.",
        play: (p) => <Spot {...p} items={Array.from({ length: 8 }, (_, i) => `Cell ${i + 1}`)} unit="°C" base={24} rate={0.25} decimals={1} cols={4} clear="is at normal temperature." />,
      },
      {
        title: "Open the breakers",
        hint: "Open CHARGE, then DISCHARGE, then BUS TIE, so the pack never back-feeds the bus.",
        play: (p) => <Switches {...p} items={["CHARGE", "DISCHARGE", "BUS TIE"]} />,
      },
      {
        title: "Time the jettison",
        hint: "The pack has to clear the radiator. Jettison while the marker is in the gap.",
        play: (p) => <Timing {...p} label="radiator gap" action="jettison" miss="The pack would hit the radiator. Wait for the gap." />,
      },
    ],
    commit: "Hold to jettison battery 3",
  },
  avionics_fire: {
    name: "Fire suppression",
    steps: [
      {
        title: "Find the fire",
        hint: "Smoke detector readings update live. Tap the rack that keeps climbing.",
        play: (p) => <Spot {...p} items={Array.from({ length: 6 }, (_, i) => `Rack ${i + 1}`)} unit="% obs" base={0.4} rate={0.05} decimals={2} clear="is clear." />,
      },
      {
        title: "Make the bay safe",
        hint: "Masks first so nobody breathes smoke, fans off so the fire starves, then power, then seal it in.",
        play: (p) => (
          <Sequence
            {...p}
            fixed
            items={["Masks on", "Fans off", "Rack power off", "Bay hatch shut"]}
            done="done"
            open="ready"
            wrong={(v) => `${v} out of order. Start the fire checklist again from the top.`}
          />
        ),
      },
      {
        title: "Charge the suppressant bottle",
        hint: "Hold to pressurize the CO2 bottle. Let go inside the green band.",
        play: (p) => <Fill {...p} label="bottle" unit="bar" from={0} scale={0.9} action="hold to charge" active="charging…" over="Bottle over pressure. The burst disc vented it." />,
      },
    ],
    commit: "Hold to flood the bay",
  },
  detumble: {
    name: "Tumble recovery",
    steps: [
      { title: "Null the spin", hint: "Pulse the RCS against the spin until the rate is under 0.15 °/s, then hold attitude.", play: (p) => <Detumble {...p} /> },
      {
        title: "Check the landing reserve",
        hint: "The burn comes out of the propellant you need to land. Work out what is left.",
        play: (p) => (
          <Quiz
            {...p}
            make={(r) => {
              const reserve = 300 + Math.floor(r() * 8) * 20;
              const burn = 20 + Math.floor(r() * 5) * 5;
              const answer = reserve - burn * 2;
              return {
                question: `The landing reserve holds ${reserve} kg. The detumble burn runs ${burn} s at 2 kg/s. What is left?`,
                answer,
                decoys: [reserve - burn, reserve - burn * 4, burn * 2],
                unit: "kg",
                explain: `${burn} s × 2 kg/s = ${burn * 2} kg used, so ${reserve} − ${burn * 2} = ${answer} kg.`,
              };
            }}
          />
        ),
      },
      {
        title: "Re-lock the star tracker",
        hint: "Lock while the reference star crosses the boresight window.",
        play: (p) => <Timing {...p} label="reference star" action="lock star tracker" miss="No star in the boresight. Wait for it to cross." />,
      },
    ],
    commit: "Hold to fire RCS",
  },
  solar_flare: {
    name: "Storm shelter",
    steps: [
      {
        title: "Read the dose forecast",
        hint: "Work out how long the crew can stay outside the shelter. Pick the closest answer.",
        play: (p) => (
          <Quiz
            {...p}
            make={(r) => {
              const rate = 2 + Math.floor(r() * 7) * 0.5;
              const margin = 30 + Math.floor(r() * 5) * 10;
              const answer = round1(margin / rate);
              return {
                question: `The forecast dose rate outside the shelter is ${rate} mSv an hour. The crew has ${margin} mSv left before the career limit. How long is that?`,
                answer,
                decoys: [round1(margin / rate / 2), round1((margin * 2) / rate), margin - rate],
                unit: "h",
                explain: `${margin} mSv ÷ ${rate} mSv an hour ≈ ${answer} h.`,
              };
            }}
          />
        ),
      },
      {
        title: "Call the crew in",
        hint: "Call them in the order shown: farthest from the shelter first.",
        play: (p) => (
          <Sequence
            {...p}
            items={["Commander", "Pilot", "Engineer", "Specialist"]}
            done="inside"
            open="outside"
            wrong={(c) => `${c} isn't next. Someone farther out is still exposed. Start the call again.`}
          />
        ),
      },
      {
        title: "Find the corrupted memory bank",
        hint: "Error counts update live. The bank the protons hit keeps climbing. Tap it.",
        play: (p) => <Spot {...p} items={Array.from({ length: 6 }, (_, i) => `Bank ${i}`)} unit="err/s" base={3} rate={0.9} decimals={0} clear="is scrubbing clean." />,
      },
    ],
    commit: "Hold to wipe the bank",
  },
};

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Deterministic per alert, so a re-render or a reopened modal shows the same puzzle. */
function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle<T>(items: T[], seed: number): T[] {
  const r = rng(seed);
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

type Props = { alert: AlertView; disabled?: boolean; onApprove: () => void; onReject: () => void };

export function CrewTask({ alert, disabled, onApprove, onReject }: Props) {
  const procedure = alert.procedure ? PROCEDURES[alert.procedure] : undefined;
  const steps = procedure?.steps ?? [];
  const [step, setStep] = useState(0);
  const seed = useMemo(() => hash(alert.alert_id), [alert.alert_id]);
  const current = steps[step];
  const ready = step >= steps.length;

  return (
    <section className="border-t border-line px-4 py-3">
      {procedure && (
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-alarm">Procedure · {procedure.name}</p>
          <ol className="flex items-center gap-1.5 font-mono text-[10px] text-faint">
            {[...steps.map((s) => s.title), procedure.commit].map((t, i) => (
              <li
                key={t}
                title={t}
                className={`h-1.5 w-6 rounded-full ${i < step ? "bg-auto" : i === step ? "bg-alarm heartbeat" : "bg-line"}`}
              />
            ))}
          </ol>
        </div>
      )}

      {current && (
        <div key={step} className="arrive rounded-md border border-line bg-void/50 p-3">
          <p className="text-sm font-medium">
            <span className="mr-2 font-mono text-xs text-faint">{step + 1}/{steps.length + 1}</span>
            {current.title}
          </p>
          <p className="mb-3 text-xs text-dim">{current.hint}</p>
          {current.play({ seed: seed + step, disabled, onDone: () => setStep((s) => s + 1) })}
        </div>
      )}

      {step > 0 && (
        <ul className="mt-2 space-y-0.5 font-mono text-[11px] text-auto">
          {steps.slice(0, step).map((s) => (
            <li key={s.title}>✓ {s.title}</li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={onReject}
          className="rounded-md border border-line px-4 py-2 text-sm text-dim hover:border-dim hover:text-ink disabled:opacity-40"
        >
          Reject
        </button>
        {ready ? (
          <HoldButton label={procedure?.commit ?? "Hold to approve"} holdMs={procedure ? 1500 : 2000} disabled={disabled} onConfirm={onApprove} />
        ) : (
          <span className="rounded-md border border-line px-4 py-2 font-mono text-xs text-faint">finish the procedure to commit</span>
        )}
      </div>
    </section>
  );
}

function Feedback({ text, tone = "alarm" }: { text: string | null; tone?: "alarm" | "dim" }) {
  if (!text) return null;
  return <p className={`arrive mt-2 font-mono text-[11px] ${tone === "alarm" ? "text-alarm" : "text-dim"}`}>{text}</p>;
}

const COLS = { 3: "grid-cols-3", 4: "grid-cols-4" } as const;

type SpotProps = GameProps & {
  items: string[];
  unit: string;
  base: number;
  /** How far the faulty reading moves each tick. The others only wobble. */
  rate: number;
  decimals?: number;
  cols?: keyof typeof COLS;
  clear: string;
};

/** Readings update live. Only one keeps moving the wrong way. */
function Spot({ seed, disabled, onDone, items, unit, base, rate, decimals = 2, cols = 3, clear }: SpotProps) {
  const bad = Math.floor(rng(seed)() * items.length);
  const [tick, setTick] = useState(0);
  const [cleared, setCleared] = useState<Set<number>>(new Set());
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 450);
    return () => clearInterval(id);
  }, []);

  const reading = (i: number) => base + (i === bad ? rate * tick : 0) + Math.sin(i * 13.7 + tick * 1.3) * Math.abs(rate) * 0.6;

  const pick = (i: number) => {
    if (i === bad) return onDone();
    setCleared((s) => new Set(s).add(i));
    setNote(`${items[i]} ${clear}`);
  };

  return (
    <div>
      <div className={`grid ${COLS[cols]} gap-1.5`}>
        {items.map((m, i) => (
          <button
            key={m}
            type="button"
            disabled={disabled || cleared.has(i)}
            onClick={() => pick(i)}
            className="rounded border border-line bg-panel px-2 py-2 text-left hover:border-dim disabled:opacity-40"
          >
            <span className="block text-xs">{m}</span>
            <span className="font-mono text-[11px] text-dim tabular">
              {reading(i).toFixed(decimals)} {unit}
            </span>
          </button>
        ))}
      </div>
      <Feedback text={note} tone="dim" />
    </div>
  );
}

type FillProps = GameProps & { label: string; unit: string; from: number; scale: number; action: string; active: string; over: string };

/** Hold to fill; let go inside the band. Overfilling vents it back down. */
function Fill({ seed, disabled, onDone, label, unit, from, scale, action, active, over }: FillProps) {
  const r = rng(seed);
  const lo = Math.round(58 + r() * 18);
  const hi = lo + 12;
  const [level, setLevel] = useState(20);
  const [filling, setFilling] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const levelRef = useRef(20);
  const frame = useRef<number | null>(null);
  const last = useRef<number | null>(null);
  const show = (v: number) => `${Math.round(from + v * scale)} ${unit}`;

  const tick = (t: number) => {
    const dt = last.current === null ? 0 : (t - last.current) / 1000;
    last.current = t;
    // Fills faster as it goes, so stopping in the band takes attention.
    levelRef.current += dt * (18 + levelRef.current * 0.35);
    if (levelRef.current >= 100) {
      levelRef.current = 30;
      setLevel(30);
      setNote(`${over} Back to ${show(30)}.`);
      setFilling(false);
      frame.current = null;
      last.current = null;
      return;
    }
    setLevel(levelRef.current);
    frame.current = requestAnimationFrame(tick);
  };

  const press = () => {
    if (disabled || frame.current) return;
    setNote(null);
    setFilling(true);
    frame.current = requestAnimationFrame(tick);
  };

  const release = () => {
    if (!frame.current) return;
    cancelAnimationFrame(frame.current);
    frame.current = null;
    setFilling(false);
    last.current = null;
    const v = levelRef.current;
    if (v >= lo && v <= hi) onDone();
    else if (v < lo) setNote(`${show(v)}. Not there yet, keep going.`);
    else {
      levelRef.current = 40;
      setLevel(40);
      setNote(`${show(v)}. Over the band, bled back to ${show(40)}.`);
    }
  };

  useEffect(() => () => {
    if (frame.current) cancelAnimationFrame(frame.current);
  }, []);

  const inBand = level >= lo && level <= hi;
  return (
    <div>
      <div className="relative h-6 overflow-hidden rounded border border-line bg-panel">
        <div className="absolute inset-y-0 bg-auto/20 ring-1 ring-auto/60" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
        <div className={`absolute inset-y-0 left-0 ${inBand ? "bg-auto/70" : level > hi ? "bg-alarm/70" : "bg-crew/60"}`} style={{ width: `${level}%` }} />
        <span className="absolute inset-0 flex items-center justify-center font-mono text-[11px] text-ink tabular">
          {label} · {show(level)}
        </span>
      </div>
      <button
        type="button"
        disabled={disabled}
        onPointerDown={press}
        onPointerUp={release}
        onPointerLeave={release}
        onKeyDown={(e) => (e.key === " " || e.key === "Enter") && !e.repeat && press()}
        onKeyUp={release}
        className="mt-2 w-full rounded-md border border-crew/60 px-3 py-2 font-mono text-xs uppercase tracking-[0.12em] text-crew select-none touch-none hover:bg-crew/10 disabled:opacity-40"
      >
        {filling ? active : action}
      </button>
      <Feedback text={note} />
    </div>
  );
}

/** Drag the nozzle onto the target vector. The gimbal drifts, so lock it while it is on. */
function GimbalAlign({ seed, disabled, onDone }: GameProps) {
  const r = rng(seed);
  const target = Math.round((8 + r() * 12) * (r() > 0.5 ? 1 : -1) * 2) / 2;
  const [angle, setAngle] = useState(0);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let phase = 0;
    const id = setInterval(() => {
      phase += 0.35;
      setAngle((a) => Math.max(-25, Math.min(25, a + Math.sin(phase) * 0.35)));
    }, 120);
    return () => clearInterval(id);
  }, []);

  const off = angle - target;
  const aligned = Math.abs(off) <= 1.5;
  const lock = () => {
    if (aligned) onDone();
    else setNote(`Off by ${Math.abs(off).toFixed(1)}°. The thrust vector must be within 1.5°.`);
  };

  return (
    <div>
      <div className="flex items-center gap-4">
        <svg viewBox="-60 -10 120 80" className="h-24 w-36 shrink-0" aria-hidden>
          <rect x="-14" y="-6" width="28" height="16" rx="2" fill="var(--color-raised)" stroke="var(--color-line)" />
          <g transform={`rotate(${target} 0 10)`}>
            <line x1="0" y1="10" x2="0" y2="72" stroke="var(--color-auto)" strokeDasharray="3 3" />
          </g>
          <g transform={`rotate(${angle} 0 10)`}>
            <path d="M -6 10 L 6 10 L 13 38 L -13 38 Z" fill={aligned ? "var(--color-auto)" : "var(--color-crew)"} opacity="0.85" />
            <line x1="0" y1="38" x2="0" y2="62" stroke={aligned ? "var(--color-auto)" : "var(--color-alarm)"} strokeWidth="2" />
          </g>
        </svg>
        <dl className="grid gap-1 font-mono text-[11px] tabular">
          <div className="flex gap-2"><dt className="text-faint">target</dt><dd>{target.toFixed(1)}°</dd></div>
          <div className="flex gap-2"><dt className="text-faint">gimbal</dt><dd className={aligned ? "text-auto" : "text-crew"}>{angle.toFixed(1)}°</dd></div>
          <div className="flex gap-2"><dt className="text-faint">error</dt><dd>{off >= 0 ? "+" : ""}{off.toFixed(1)}°</dd></div>
        </dl>
      </div>
      <div className="mt-2 flex items-center gap-3">
        <input
          type="range"
          min={-25}
          max={25}
          step={0.5}
          value={angle}
          disabled={disabled}
          onChange={(e) => setAngle(Number(e.target.value))}
          aria-label="Engine gimbal angle"
          className="flex-1 accent-[var(--color-crew)]"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={lock}
          className={`rounded-md border px-3 py-1.5 font-mono text-xs uppercase tracking-[0.12em] disabled:opacity-40 ${aligned ? "border-auto/70 text-auto hover:bg-auto/10" : "border-line text-dim"}`}
        >
          lock gimbal
        </button>
      </div>
      <Feedback text={note} />
    </div>
  );
}

type SequenceProps = GameProps & {
  items: string[];
  /** The order is the list as given and the panel is shuffled. Otherwise the order is called out at random. */
  fixed?: boolean;
  done: string;
  open: string;
  wrong: (item: string) => string;
};

/** Work through the called order. A wrong press undoes the lot. */
function Sequence({ seed, disabled, onDone, items, fixed, done, open, wrong }: SequenceProps) {
  const order = useMemo(() => (fixed ? items : shuffle(items, seed)), [fixed, items, seed]);
  const layout = useMemo(() => (fixed ? shuffle(items, seed) : items), [fixed, items, seed]);
  const [completed, setCompleted] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const wide = items.some((i) => i.length > 6);

  const press = (item: string) => {
    if (order[completed.length] !== item) {
      setCompleted([]);
      setNote(wrong(item));
      return;
    }
    const next = [...completed, item];
    setCompleted(next);
    setNote(null);
    if (next.length === order.length) onDone();
  };

  return (
    <div>
      <p className="mb-2 font-mono text-xs text-ink">
        order:{" "}
        {order.map((h, i) => (
          <span key={h} className={i < completed.length ? "text-auto" : i === completed.length ? "text-crew" : "text-dim"}>
            {h}{i < order.length - 1 ? " → " : ""}
          </span>
        ))}
      </p>
      <div className={`grid gap-1.5 ${wide ? "grid-cols-2" : "grid-cols-4"}`}>
        {layout.map((item) => {
          const finished = completed.includes(item);
          return (
            <button
              key={item}
              type="button"
              disabled={disabled || finished}
              onClick={() => press(item)}
              className={`rounded border px-2 py-3 font-mono text-xs ${finished ? "border-auto/60 bg-auto/15 text-auto" : "border-line bg-panel text-dim hover:border-dim hover:text-ink"}`}
            >
              {item}
              <span className="block text-[10px] uppercase">{finished ? done : open}</span>
            </button>
          );
        })}
      </div>
      <Feedback text={note} />
    </div>
  );
}

/** Switch covers in a shuffled panel layout; the order is the list as given and only the hint says it. */
function Switches({ seed, disabled, onDone, items }: GameProps & { items: string[] }) {
  const layout = useMemo(() => shuffle(items, seed), [items, seed]);
  const [armed, setArmed] = useState(0);
  const [note, setNote] = useState<string | null>(null);

  const flip = (s: string) => {
    if (items[armed] !== s) {
      setArmed(0);
      setNote(`${s} out of sequence. Circuit safed, start again.`);
      return;
    }
    setNote(null);
    if (armed + 1 === items.length) onDone();
    setArmed(armed + 1);
  };

  return (
    <div>
      <div className="grid grid-cols-3 gap-2">
        {layout.map((s) => {
          const on = items.indexOf(s) < armed;
          return (
            <button
              key={s}
              type="button"
              disabled={disabled || on}
              onClick={() => flip(s)}
              className={`flex flex-col items-center gap-1.5 rounded border px-2 py-2 font-mono text-[10px] uppercase tracking-[0.1em] ${on ? "border-alarm/70 bg-alarm/15 text-alarm" : "border-line bg-panel text-dim hover:border-dim"}`}
            >
              <span className={`relative h-6 w-3 rounded-full ${on ? "bg-alarm/60" : "bg-line"}`}>
                <span className={`absolute left-0 h-3 w-3 rounded-full bg-ink transition-all ${on ? "top-0" : "top-3"}`} />
              </span>
              {s}
            </button>
          );
        })}
      </div>
      <Feedback text={note} />
    </div>
  );
}

/** A marker sweeps back and forth; act inside the window. */
function Timing({ seed, disabled, onDone, label, action, miss }: GameProps & { label: string; action: string; miss: string }) {
  const r = rng(seed);
  const lo = Math.round(20 + r() * 55);
  const hi = lo + 12;
  const period = 380 + r() * 120;
  const [pos, setPos] = useState(0);
  const [misses, setMisses] = useState(0);
  const posRef = useRef(0);

  useEffect(() => {
    let frame = requestAnimationFrame(function step(t) {
      posRef.current = 50 + 50 * Math.sin(t / period);
      setPos(posRef.current);
      frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [period]);

  const act = () => {
    const p = posRef.current;
    if (p >= lo && p <= hi) onDone();
    else setMisses((m) => m + 1);
  };

  return (
    <div>
      <div className="relative h-6 rounded border border-line bg-panel">
        <div className="absolute inset-y-0 bg-auto/20 ring-1 ring-auto/60" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />
        <div className="absolute inset-y-0 w-1 -translate-x-1/2 bg-crew" style={{ left: `${pos}%` }} />
        <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center font-mono text-[10px] uppercase tracking-[0.1em] text-faint">{label}</span>
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={act}
        className="mt-2 w-full rounded-md border border-crew/60 px-3 py-2 font-mono text-xs uppercase tracking-[0.12em] text-crew hover:bg-crew/10 disabled:opacity-40"
      >
        {action}
      </button>
      <Feedback text={misses ? `Missed ${misses}×. ${miss}` : null} />
    </div>
  );
}

type QuizSpec = { question: string; answer: number; decoys: number[]; unit: string; explain: string };

/** The arithmetic a crew does on the back of a checklist card before committing. */
function Quiz({ seed, disabled, onDone, make }: GameProps & { make: (r: () => number) => QuizSpec }) {
  const spec = useMemo(() => make(rng(seed)), [make, seed]);
  const options = useMemo(() => {
    const decoys = [...new Set(spec.decoys.map(round1))].filter((d) => d > 0 && d !== spec.answer).slice(0, 3);
    return shuffle([spec.answer, ...decoys], seed);
  }, [spec, seed]);
  const [wrong, setWrong] = useState<Set<number>>(new Set());

  const pick = (v: number) => {
    if (v === spec.answer) return onDone();
    setWrong((s) => new Set(s).add(v));
  };

  return (
    <div>
      <p className="mb-2 text-sm text-ink">{spec.question}</p>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {options.map((v) => (
          <button
            key={v}
            type="button"
            disabled={disabled || wrong.has(v)}
            onClick={() => pick(v)}
            className="rounded border border-line bg-panel px-2 py-2 font-mono text-xs text-ink tabular hover:border-dim disabled:line-through disabled:opacity-40"
          >
            {v.toLocaleString()} {spec.unit}
          </button>
        ))}
      </div>
      <Feedback text={wrong.size ? `Not quite. ${spec.explain}` : null} />
    </div>
  );
}

const PULSE = 0.35;
const PULSE_BUDGET = 16;
const NULLED = 0.15;

/** A stuck thruster keeps spinning the ship up. Pulse against it until the rate is nulled. */
function Detumble({ seed, disabled, onDone }: GameProps) {
  const r = rng(seed);
  const start = round1((2.4 + r() * 1.6) * (r() > 0.5 ? 1 : -1));
  const push = start > 0 ? 0.012 : -0.012;
  const [ship, setShip] = useState({ rate: start, angle: 0 });
  const [pulses, setPulses] = useState(0);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    const id = setInterval(() => setShip((s) => ({ rate: s.rate + push, angle: (s.angle + s.rate * 4) % 360 })), 100);
    return () => clearInterval(id);
  }, [push]);

  const fire = (dir: 1 | -1) => {
    if (pulses + 1 > PULSE_BUDGET) {
      setShip({ rate: start, angle: 0 });
      setPulses(0);
      setNote("Out of RCS budget for this attempt. The ship spun back up. Try again with fewer pulses.");
      return;
    }
    setNote(null);
    setPulses((p) => p + 1);
    setShip((s) => ({ ...s, rate: s.rate + dir * PULSE }));
  };

  const nulled = Math.abs(ship.rate) <= NULLED;
  const hold = () => {
    if (nulled) onDone();
    else setNote(`Still turning at ${Math.abs(ship.rate).toFixed(2)} °/s. Get it under ${NULLED}.`);
  };

  return (
    <div>
      <div className="flex items-center gap-4">
        <svg viewBox="-40 -40 80 80" className="h-20 w-20 shrink-0" aria-hidden>
          <circle r="34" fill="none" stroke="var(--color-line)" strokeDasharray="2 4" />
          <g transform={`rotate(${ship.angle})`}>
            <rect x="-6" y="-16" width="12" height="32" rx="2" fill={nulled ? "var(--color-auto)" : "var(--color-crew)"} opacity="0.85" />
            <rect x="-28" y="-4" width="20" height="8" fill="var(--color-raised)" stroke="var(--color-line)" />
            <rect x="8" y="-4" width="20" height="8" fill="var(--color-raised)" stroke="var(--color-line)" />
          </g>
        </svg>
        <dl className="grid gap-1 font-mono text-[11px] tabular">
          <div className="flex gap-2"><dt className="text-faint">body rate</dt><dd className={nulled ? "text-auto" : "text-crew"}>{ship.rate >= 0 ? "+" : ""}{ship.rate.toFixed(2)} °/s</dd></div>
          <div className="flex gap-2"><dt className="text-faint">pulses</dt><dd>{pulses} / {PULSE_BUDGET}</dd></div>
        </dl>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2">
        <button type="button" disabled={disabled} onClick={() => fire(-1)} className="rounded-md border border-crew/60 px-3 py-2 font-mono text-xs text-crew hover:bg-crew/10 disabled:opacity-40">
          ◀ pulse −
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={hold}
          className={`rounded-md border px-3 py-2 font-mono text-xs uppercase tracking-[0.1em] disabled:opacity-40 ${nulled ? "border-auto/70 text-auto hover:bg-auto/10" : "border-line text-dim"}`}
        >
          hold attitude
        </button>
        <button type="button" disabled={disabled} onClick={() => fire(1)} className="rounded-md border border-crew/60 px-3 py-2 font-mono text-xs text-crew hover:bg-crew/10 disabled:opacity-40">
          pulse + ▶
        </button>
      </div>
      <Feedback text={note} />
    </div>
  );
}
