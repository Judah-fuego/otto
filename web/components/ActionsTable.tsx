"use client";

import { useState } from "react";
import type { AlertView, LogEntry } from "@/lib/types";
import { clock } from "@/lib/format";
import { STATUS } from "./AlertNotice";

const KIND = {
  auto: { text: "text-auto", label: "auto" },
  crew: { text: "text-alarm", label: "crew" },
  ground: { text: "text-ground", label: "ground" },
} as const;

type Filter = "all" | LogEntry["kind"];
const FILTERS: Filter[] = ["all", "auto", "crew", "ground"];

type Props = { log: LogEntry[]; alerts: Map<string, AlertView>; onOpen: (alertId: string) => void };

/** Every action SafeMode and the crew took, newest first. Kept out of the chat on purpose. */
export function ActionsTable({ log, alerts, onOpen }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const rows = [...log].reverse().filter((e) => filter === "all" || e.kind === filter);
  const count = (k: LogEntry["kind"]) => log.filter((e) => e.kind === k).length;

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={`rounded-full border px-3 py-1 font-mono text-xs ${filter === f ? "border-dim text-ink" : "border-line text-faint hover:text-dim"}`}
            >
              {f} <span className="tabular text-faint">{f === "all" ? log.length : count(f)}</span>
            </button>
          ))}
        </div>
        <p className="font-mono text-xs text-faint">click a row to open the alert</p>
      </div>

      {rows.length === 0 ? (
        <p className="pt-10 text-center text-sm text-faint">No actions yet. Simulate an alert from the side panel.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-panel font-mono uppercase tracking-[0.12em] text-faint">
              <tr>
                <th className="px-3 py-2 font-normal">time</th>
                <th className="px-3 py-2 font-normal">by</th>
                <th className="px-3 py-2 font-normal">subsystem</th>
                <th className="px-3 py-2 font-normal">channel</th>
                <th className="px-3 py-2 text-right font-normal">confidence</th>
                <th className="px-3 py-2 font-normal">action</th>
                <th className="px-3 py-2 font-normal">now</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((e, i) => {
                const a = alerts.get(e.alert_id);
                const status = a && STATUS[a.decision.status];
                return (
                  <tr key={`${e.time}-${i}`} onClick={() => a && onOpen(e.alert_id)} className={a ? "cursor-pointer hover:bg-line/40" : "opacity-60"}>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-faint tabular">{clock(e.time)}</td>
                    <td className={`px-3 py-2 font-mono uppercase ${KIND[e.kind].text}`}>{KIND[e.kind].label}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-ink">{a?.subsystem ?? "—"}</td>
                    <td className="px-3 py-2 font-mono text-dim">{a?.channel ?? e.alert_id}</td>
                    <td className="px-3 py-2 text-right font-mono text-dim tabular">{a ? `${Math.round(a.confidence * 100)}%` : "—"}</td>
                    <td className="min-w-[260px] px-3 py-2 text-ink/90">{e.text}</td>
                    <td className={`whitespace-nowrap px-3 py-2 font-mono uppercase ${status?.text ?? "text-faint"}`}>{status?.label ?? "cleared"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
