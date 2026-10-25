import type { VoyageResult } from "@/lib/types";
import { duration, mass, titleCase } from "@/lib/format";
import { OrbitDiagram } from "./OrbitDiagram";

export function VoyageCard({ v }: { v: VoyageResult }) {
  const consumables = v.oxygen_kg + v.water_kg + v.food_kg;
  const rows: [string, string][] = [
    ["Δv", `${(v.delta_v_m_s / 1000).toFixed(2)} km/s`],
    ["coast", duration(v.travel_time_days)],
    ["propellant", mass(v.propellant_kg)],
    ["window", v.launch_window_utc ? v.launch_window_utc.slice(0, 10) : "daily"],
    ["oxygen", mass(v.oxygen_kg)],
    ["water", mass(v.water_kg)],
    ["food", mass(v.food_kg)],
    ["consumables", mass(consumables)],
  ];
  return (
    <div className="arrive flex flex-wrap items-center gap-5 rounded-lg border border-line bg-panel p-4">
      <OrbitDiagram destination={v.destination} />
      <div className="min-w-[220px] flex-1">
        <p className="text-[11px] uppercase tracking-[0.14em] text-faint">Voyage · Hohmann transfer</p>
        <h3 className="mb-3 text-base font-medium">
          {v.origin === "leo" ? "LEO" : titleCase(v.origin)} → {titleCase(v.destination)} · {v.crew} crew
        </h3>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-xs tabular">
          {rows.map(([k, val]) => (
            <div key={k} className="flex justify-between gap-3 border-b border-line/60 pb-1">
              <dt className="text-faint">{k}</dt>
              <dd className="text-ink">{val}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
