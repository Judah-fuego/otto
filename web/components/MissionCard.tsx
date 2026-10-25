import type { MissionStatus, SystemItem } from "@/lib/types";
import { mass, titleCase } from "@/lib/format";
import { MissionMap } from "./MissionMap";

const OVERALL = {
  nominal: { label: "Nominal", text: "text-auto", border: "border-auto/30", dot: "bg-auto" },
  watch: { label: "Watch", text: "text-ground", border: "border-ground/40", dot: "bg-ground" },
  action_needed: { label: "Action needed", text: "text-crew", border: "border-crew/60", dot: "bg-crew" },
} as const;

const STATUS_TEXT: Record<SystemItem["status"], string> = {
  executed: "done",
  approved: "crew approved",
  rejected: "crew rejected",
  escalated: "with ground",
  awaiting_crew: "awaiting crew",
};

export function MissionCard({ m }: { m: MissionStatus }) {
  const t = m.trajectory;
  const tone = OVERALL[m.overall];
  const open = [...m.systems.awaiting_crew, ...m.systems.with_ground, ...(m.systems.crew_declined ?? [])];
  return (
    <div className={`arrive rounded-lg border bg-panel ${tone.border} ${m.overall === "action_needed" ? "crew-glow" : ""}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <span className={`flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] ${tone.text}`}>
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
            {tone.label}
          </span>
          <h3 className="text-sm font-medium">
            {t.mission} · {titleCase(t.origin)} → {titleCase(t.destination)} · {t.crew} crew
          </h3>
        </div>
        <span className="font-mono text-xs text-faint tabular">day {t.mission_day} of {t.transit_days}</span>
      </header>

      <div className="flex flex-wrap items-center gap-5 p-4">
        <MissionMap t={t} />
        <div className="min-w-[240px] flex-1 space-y-4">
          <div>
            <div className="mb-1.5 flex justify-between font-mono text-xs tabular">
              <span className="text-faint">to {t.destination}</span>
              <span className="text-ink">{Math.round(t.progress * 100)}% · {Math.round(t.days_to_arrival)} d left</span>
            </div>
            <Bar fraction={t.progress} className="bg-auto" />
            <div className="mt-1 flex justify-between font-mono text-[11px] text-faint tabular">
              <span>{t.launch_utc.slice(0, 10)}</span>
              <span>arrive {t.arrival_utc.slice(0, 10)}</span>
            </div>
          </div>

          <dl className="space-y-1.5 font-mono text-xs tabular">
            <Row k="from Earth" v={`${(t.distance_to_earth_km / 1e6).toFixed(1)} M km`} />
            <Row k="light delay" v={`${t.one_way_light_delay_min} min`} />
          </dl>

          <div className="space-y-2">
            {Object.entries(m.consumables).map(([name, s]) => (
              <div key={name}>
                <div className="mb-1 flex justify-between font-mono text-[11px] tabular">
                  <span className="text-faint">{name}</span>
                  <span className={s.margin_days_after_arrival < 0 ? "text-alarm" : "text-dim"}>
                    {mass(s.remaining_kg)} · {s.margin_days_after_arrival >= 0 ? "+" : ""}{s.margin_days_after_arrival} d spare
                  </span>
                </div>
                <Bar fraction={s.remaining_fraction} className={s.margin_days_after_arrival < 0 ? "bg-alarm" : "bg-ground/70"} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {(open.length > 0 || m.systems.handled.length > 0) && (
        <ul className="space-y-1.5 border-t border-line px-4 py-3 text-xs">
          {[...open, ...m.systems.handled].map((s, i) => (
            <li key={i} className="flex justify-between gap-4">
              <span><span className="text-ink">{s.subsystem}</span> <span className="text-dim">· {s.action}</span></span>
              <span className={`shrink-0 font-mono uppercase tracking-[0.1em] ${s.status === "awaiting_crew" ? "text-crew" : s.status === "escalated" || s.status === "rejected" ? "text-ground" : "text-faint"}`}>
                {STATUS_TEXT[s.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Bar({ fraction, className }: { fraction: number; className: string }) {
  return (
    <div className="h-1.5 overflow-hidden rounded bg-line">
      <div className={`h-full ${className}`} style={{ width: `${Math.min(1, Math.max(0, fraction)) * 100}%` }} />
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-line/60 pb-1">
      <dt className="text-faint">{k}</dt>
      <dd className="text-ink">{v}</dd>
    </div>
  );
}
